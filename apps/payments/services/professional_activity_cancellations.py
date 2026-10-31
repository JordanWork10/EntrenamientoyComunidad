"""Cancelación del organizador de ACTIVIDADES profesionales (V131.71).

Movimiento estrictamente sandbox: sin pasarela bancaria ni transferencias.
Reservas individuales de servicios profesionales NO forman parte de este flujo.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.activities.models import Activity, ActivityRegistration

from ..models import Payment, Refund, Settlement
from .cancellation_policy import (
    PAYMENTS_POLICY_VERSION,
    calculate_forced_full_refund,
)
from .commissions import recalculate_payment_after_refund
from .refunds import activity_service_end, activity_service_start
from .settlements import sync_activity_settlement


class ProfessionalActivityCancellationError(Exception):
    """No se puede cancelar automáticamente; requiere corrección o revisión."""


@dataclass(frozen=True)
class ProfessionalActivityCancellationOutcome:
    activity: Activity
    cancelled_registrations: int
    refunds_created: int
    total_refunded_clp: int
    pending_payments_cancelled: int


@transaction.atomic
def cancel_professional_activity(activity, organizer, reason, cancelled_at=None):
    cancelled_at = cancelled_at or timezone.now()
    reason = (reason or '').strip()

    if not 10 <= len(reason) <= 1000:
        raise ProfessionalActivityCancellationError(
            'Indica un motivo de cancelación entre 10 y 1000 caracteres.'
        )

    locked_activity = (
        Activity.objects
        .select_for_update()
        .get(pk=activity.pk)
    )

    if (
        locked_activity.organizer_id != organizer.pk
        or locked_activity.activity_type != Activity.ActivityType.PROFESSIONAL
    ):
        raise ProfessionalActivityCancellationError(
            'Esta actividad no pertenece a tu perfil profesional.'
        )

    if locked_activity.status != Activity.Status.PUBLISHED:
        raise ProfessionalActivityCancellationError(
            'Solo se pueden cancelar actividades profesionales publicadas.'
        )

    if cancelled_at >= activity_service_start(locked_activity):
        raise ProfessionalActivityCancellationError(
            'La actividad ya comenzó. Solicita revisión administrativa.'
        )

    payments = list(
        Payment.objects
        .select_for_update()
        .filter(activity=locked_activity)
        .order_by('pk')
    )
    registrations = list(
        ActivityRegistration.objects
        .select_for_update()
        .filter(activity=locked_activity)
        .order_by('pk')
    )
    registrations_by_id = {
        registration.pk: registration for registration in registrations
    }
    settlements = list(
        Settlement.objects
        .select_for_update()
        .filter(
            scope_type=Settlement.ScopeType.ACTIVITY,
            activity=locked_activity,
        )
    )

    if any(
        settlement.status in {
            Settlement.Status.ON_HOLD,
            Settlement.Status.SETTLED,
        }
        for settlement in settlements
    ):
        raise ProfessionalActivityCancellationError(
            'La liquidación está retenida o cerrada. Solicita revisión administrativa.'
        )

    if any(
        payment.settlement_status in {
            Payment.SettlementStatus.ON_HOLD,
            Payment.SettlementStatus.SETTLED,
        }
        for payment in payments
    ):
        raise ProfessionalActivityCancellationError(
            'Hay pagos retenidos o liquidados. Solicita revisión administrativa.'
        )

    if payments and Refund.objects.filter(
        payment_id__in=[payment.pk for payment in payments],
        status__in=[
            Refund.Status.REQUESTED,
            Refund.Status.APPROVED,
            Refund.Status.FAILED,
        ],
    ).exists():
        raise ProfessionalActivityCancellationError(
            'Hay reembolsos pendientes o con incidencias. Solicita revisión administrativa.'
        )

    # Evita efectuar devoluciones sobre saldos históricos inconsistentes.
    processed_amounts = {
        row['payment_id']: row['total'] or 0
        for row in Refund.objects.filter(
            payment_id__in=[payment.pk for payment in payments],
            status=Refund.Status.PROCESSED,
        )
        .values('payment_id')
        .annotate(total=Sum('amount_clp'))
    }
    if any(
        payment.refunded_amount_clp != processed_amounts.get(payment.pk, 0)
        for payment in payments
    ):
        raise ProfessionalActivityCancellationError(
            'Existen saldos históricos de reembolso inconsistentes. '
            'Solicita revisión administrativa.'
        )

    # Una inscripción cancelada voluntariamente antes no debe recibir
    # retrospectivamente el saldo que la política le retuvo.
    active_payments = []
    for payment in payments:
        if payment.status not in {
            Payment.Status.APPROVED,
            Payment.Status.PARTIALLY_REFUNDED,
        }:
            continue
        registration = registrations_by_id.get(payment.registration_id)
        if (
            payment.status == Payment.Status.PARTIALLY_REFUNDED
            and registration is not None
            and registration.status == ActivityRegistration.Status.CANCELLED
        ):
            continue
        active_payments.append(payment)

    if active_payments and not getattr(settings, 'PAYMENTS_SANDBOX', False):
        raise ProfessionalActivityCancellationError(
            'Este reembolso automático solo funciona en el entorno sandbox.'
        )

    # Todas las operaciones económicas activas deben pertenecer a inscripciones
    # vigentes. Si hay un registro inconsistente, no alteramos nada.
    for payment in active_payments:
        registration = registrations_by_id.get(payment.registration_id)
        if (
            registration is None
            or registration.member_id != payment.payer_id
            or registration.status != ActivityRegistration.Status.REGISTERED
        ):
            raise ProfessionalActivityCancellationError(
                'Existe un pago sin inscripción vigente. Solicita revisión administrativa.'
            )

    refunds_created = 0
    total_refunded = 0
    pending_cancelled = 0
    refundable_ids = {payment.pk for payment in active_payments}
    for payment in payments:
        if payment.status == Payment.Status.PENDING:
            payment.status = Payment.Status.CANCELLED
            payment.failure_reason = (
                'Actividad cancelada por su organizador.'
            )
            payment.save(
                update_fields=['status', 'failure_reason', 'updated_at']
            )
            pending_cancelled += 1
            continue

        if payment.pk not in refundable_ids:
            continue

        outstanding = payment.refundable_amount_clp
        if outstanding <= 0:
            raise ProfessionalActivityCancellationError(
                'Existe un saldo de pago inconsistente. Solicita revisión administrativa.'
            )

        decision = calculate_forced_full_refund(outstanding)
        refund = Refund(
            payment=payment,
            requested_by=organizer,
            refund_type=(
                Refund.RefundType.FULL
                if outstanding == payment.amount_clp
                else Refund.RefundType.PARTIAL
            ),
            reason=Refund.Reason.PROFESSIONAL_CANCELLATION,
            amount_clp=decision.refund_amount_clp,
            policy_percentage_snapshot=Decimal('100.00'),
            hours_before_service_snapshot=Decimal(
                str(
                    (activity_service_start(locked_activity) - cancelled_at)
                    .total_seconds() / 3600
                )
            ).quantize(Decimal('0.01')),
            policy_version_snapshot=PAYMENTS_POLICY_VERSION,
            status=Refund.Status.PROCESSED,
            notes=(
                f'Cancelación del organizador de actividad '
                f'#{locked_activity.pk}. Motivo: {reason} '
                'Reembolso contable sandbox del saldo íntegro.'
            ),
            provider_reference=(
                f'RFDA-SBX-{str(payment.public_id).split("-")[0].upper()}'
            ),
            resolved_at=cancelled_at,
            processed_at=cancelled_at,
        )
        refund.full_clean()
        refund.save()

        payment.refunded_amount_clp += decision.refund_amount_clp
        payment.status = Payment.Status.REFUNDED
        payment.failure_reason = ''
        recalculate_payment_after_refund(payment, save=False)
        payment.full_clean()
        payment.save(
            update_fields=[
                'refunded_amount_clp',
                'status',
                'failure_reason',
                'commission_base_clp',
                'commission_amount_clp',
                'net_amount_clp',
                'updated_at',
            ]
        )
        refunds_created += 1
        total_refunded += decision.refund_amount_clp

    cancelled_registrations = 0
    for registration in registrations:
        if registration.status == ActivityRegistration.Status.REGISTERED:
            registration.status = ActivityRegistration.Status.CANCELLED
            registration.save(update_fields=['status', 'updated_at'])
            cancelled_registrations += 1

    locked_activity.status = Activity.Status.CANCELLED
    locked_activity.cancelled_by = organizer
    locked_activity.cancelled_at = cancelled_at
    locked_activity.cancellation_reason = reason
    locked_activity.save(
        update_fields=[
            'status',
            'cancelled_by',
            'cancelled_at',
            'cancellation_reason',
            'updated_at',
        ]
    )

    if any(
        payment.status in {
            Payment.Status.REFUNDED,
            Payment.Status.APPROVED,
            Payment.Status.PARTIALLY_REFUNDED,
        }
        for payment in payments
    ):
        sync_activity_settlement(
            locked_activity,
            service_end=activity_service_end(locked_activity),
            now=cancelled_at,
        )

    return ProfessionalActivityCancellationOutcome(
        activity=locked_activity,
        cancelled_registrations=cancelled_registrations,
        refunds_created=refunds_created,
        total_refunded_clp=total_refunded,
        pending_payments_cancelled=pending_cancelled,
    )
