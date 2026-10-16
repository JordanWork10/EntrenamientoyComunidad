from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.activities.models import ActivityRegistration

from ..models import Payment, Refund
from .cancellation_policy import (
    PAYMENTS_POLICY_VERSION,
    CancellationDecision,
    calculate_member_cancellation,
)
from .commissions import recalculate_payment_after_refund
from .settlements import sync_activity_settlement


class RefundProcessingError(Exception):
    pass


@dataclass(frozen=True)
class RefundOutcome:
    payment: Payment
    refund: Refund
    decision: CancellationDecision


def _aware_activity_datetime(activity, time_value, add_day=False):
    value = datetime.combine(
        activity.date,
        time_value,
    )

    if add_day:
        value += timedelta(days=1)

    if timezone.is_naive(value):
        value = timezone.make_aware(
            value,
            timezone.get_current_timezone(),
        )

    return value


def activity_service_start(activity):
    return _aware_activity_datetime(
        activity,
        activity.start_time,
    )


def activity_service_end(activity):
    crosses_midnight = activity.end_time <= activity.start_time

    return _aware_activity_datetime(
        activity,
        activity.end_time,
        add_day=crosses_midnight,
    )


def preview_member_activity_cancellation(payment, cancelled_at=None):
    cancelled_at = cancelled_at or timezone.now()

    return calculate_member_cancellation(
        amount_clp=payment.amount_clp,
        service_start=activity_service_start(payment.activity),
        cancelled_at=cancelled_at,
    )


def validate_member_activity_cancellation(
    payment,
    member,
    cancelled_at=None,
    registration=None,
):
    if payment.payer_id != member.id:
        raise RefundProcessingError(
            'Este pago no pertenece a tu cuenta.'
        )

    if payment.status != Payment.Status.APPROVED:
        raise RefundProcessingError(
            'Este pago ya no admite una cancelación automática.'
        )

    if payment.registration_id is None:
        raise RefundProcessingError(
            'Esta inscripción ya no se encuentra activa.'
        )

    if registration is None:
        registration = (
            ActivityRegistration.objects
            .filter(pk=payment.registration_id)
            .only('id', 'status')
            .first()
        )

    if (
        registration is None
        or registration.status
        != ActivityRegistration.Status.REGISTERED
    ):
        raise RefundProcessingError(
            'Esta inscripción ya no se encuentra activa.'
        )

    if (
        payment.policy_version != PAYMENTS_POLICY_VERSION
        or payment.policy_accepted_at is None
    ):
        raise RefundProcessingError(
            'Este pago fue realizado antes de la política automática vigente. '
            'No puede procesarse desde este flujo.'
        )

    if payment.settlement_status == Payment.SettlementStatus.SETTLED:
        raise RefundProcessingError(
            'Este pago ya fue liquidado y requiere una revisión especial.'
        )

    decision = preview_member_activity_cancellation(
        payment,
        cancelled_at=cancelled_at,
    )

    if decision.hours_before_service <= 0:
        raise RefundProcessingError(
            'La actividad ya comenzó. '
            'La cancelación automática ya no está disponible.'
        )

    if decision.refund_amount_clp <= 0:
        raise RefundProcessingError(
            'Esta cancelación no genera un reembolso automático.'
        )

    if payment.refunds.filter(
        status=Refund.Status.PROCESSED,
    ).exists():
        raise RefundProcessingError(
            'Este pago ya registra un reembolso procesado.'
        )

    return decision


@transaction.atomic
def process_member_activity_cancellation(
    payment,
    member,
    cancelled_at=None,
):
    cancelled_at = cancelled_at or timezone.now()

    # IMPORTANTE:
    # Bloqueamos únicamente Payment. No usamos select_related('registration')
    # porque registration es nullable y PostgreSQL no permite FOR UPDATE
    # sobre el lado nullable de un OUTER JOIN.
    locked_payment = (
        Payment.objects
        .select_for_update()
        .get(pk=payment.pk)
    )

    registration = None

    if locked_payment.registration_id:
        registration = (
            ActivityRegistration.objects
            .select_for_update()
            .filter(pk=locked_payment.registration_id)
            .first()
        )

    decision = validate_member_activity_cancellation(
        locked_payment,
        member,
        cancelled_at=cancelled_at,
        registration=registration,
    )

    if registration is None:
        raise RefundProcessingError(
            'No se encontró la inscripción vinculada al pago.'
        )

    refund_type = (
        Refund.RefundType.FULL
        if decision.refund_amount_clp >= locked_payment.amount_clp
        else Refund.RefundType.PARTIAL
    )

    refund = Refund(
        payment=locked_payment,
        requested_by=member,
        refund_type=refund_type,
        reason=Refund.Reason.MEMBER_CANCELLATION,
        amount_clp=decision.refund_amount_clp,
        policy_percentage_snapshot=decision.refund_percent,
        hours_before_service_snapshot=decision.hours_before_service,
        policy_version_snapshot=decision.policy_version,
        status=Refund.Status.PROCESSED,
        notes=(
            'Reembolso automático por cancelación del Miembro '
            'según la política vigente.'
        ),
        provider_reference=(
            f'RFD-SBX-{str(locked_payment.public_id).split("-")[0].upper()}'
        ),
        resolved_at=cancelled_at,
        processed_at=cancelled_at,
    )
    refund.full_clean()
    refund.save()

    locked_payment.refunded_amount_clp = (
        locked_payment.refunded_amount_clp
        + decision.refund_amount_clp
    )

    if locked_payment.refunded_amount_clp >= locked_payment.amount_clp:
        locked_payment.status = Payment.Status.REFUNDED
    else:
        locked_payment.status = Payment.Status.PARTIALLY_REFUNDED

    locked_payment.failure_reason = ''

    recalculate_payment_after_refund(
        locked_payment,
        save=False,
    )

    locked_payment.full_clean()
    locked_payment.save(
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

    registration.status = ActivityRegistration.Status.CANCELLED
    registration.save(
        update_fields=[
            'status',
            'updated_at',
        ]
    )

    sync_activity_settlement(
        locked_payment.activity,
        service_end=activity_service_end(locked_payment.activity),
        now=cancelled_at,
    )

    return RefundOutcome(
        payment=locked_payment,
        refund=refund,
        decision=decision,
    )
