"""V131.67: cancelaciones pagadas de espacios, solo sandbox.

Solicitar NO cancela la reserva y NO modifica el importe. La reserva sigue
ocupando su horario hasta que un administrador revise la petición.
Las resoluciones solo registran movimientos CONTABLES de prueba.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.spaces.models import SpaceBooking, SpaceBookingHistory

from ..models import Payment, Refund, Settlement, SpaceCancellationRequest
from .commissions import recalculate_payment_after_refund
from .settlements import sync_space_day_settlement
from .space_policy import (
    SPACE_POLICY_VERSION,
    calculate_space_member_cancellation,
)


class SpaceCancellationError(Exception):
    pass


def _require_sandbox():
    if not getattr(settings, 'PAYMENTS_SANDBOX', False):
        raise SpaceCancellationError(
            'La revisión económica de arriendos solo está disponible en sandbox.'
        )


def _service_start(booking):
    return timezone.make_aware(
        datetime.combine(booking.session_date, booking.start_time),
        timezone.get_current_timezone(),
    )


def _reviewer_allowed(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perm('payments.change_settlement')
    )


def _hold_marker(request_id):
    return f'Cancelación de arriendo pagado #{request_id} pendiente de revisión.'


def _can_automate_member_cancellation(requested_role, payment):
    return bool(
        requested_role == SpaceCancellationRequest.RequestedRole.MEMBER
        and payment.policy_version == SPACE_POLICY_VERSION
        and payment.policy_accepted_at is not None
        and payment.approved_at is not None
    )


@transaction.atomic
def request_paid_space_cancellation(*, booking_id, actor, reason):
    """Registra una solicitud futura, manteniendo bloqueada la reserva.

    Idempotente para la misma cuenta y la misma solicitud pendiente. El
    bloqueo de SpaceBooking impide crear dos solicitudes a la vez.
    """
    _require_sandbox()
    reason = (reason or '').strip()
    if len(reason) < 5 or len(reason) > 1000:
        raise SpaceCancellationError('El motivo debe tener entre 5 y 1000 caracteres.')

    booking = (
        SpaceBooking.objects.select_for_update()
        .select_related('provider_profile')
        .get(pk=booking_id)
    )
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise SpaceCancellationError('Debes iniciar sesión para solicitar la revisión.')
    if actor.pk == booking.booked_by_id:
        requested_role = SpaceCancellationRequest.RequestedRole.MEMBER
    elif actor.pk == booking.provider_profile.user_id:
        requested_role = SpaceCancellationRequest.RequestedRole.PROVIDER
    else:
        raise SpaceCancellationError('No tienes autorización sobre esta reserva.')

    if booking.status != SpaceBooking.Status.CONFIRMED:
        raise SpaceCancellationError(
            'Solo una reserva confirmada admite revisión de cancelación pagada.'
        )
    if timezone.now() >= _service_start(booking):
        raise SpaceCancellationError(
            'El arriendo ya comenzó. Este caso necesita una incidencia administrativa.'
        )

    pending = (
        SpaceCancellationRequest.objects.select_for_update()
        .filter(booking=booking, status=SpaceCancellationRequest.Status.PENDING)
        .first()
    )
    if pending:
        if pending.requested_by_id == actor.pk:
            return pending, False
        raise SpaceCancellationError(
            'Esta reserva ya tiene una solicitud de cancelación en revisión.'
        )

    payment = (
        Payment.objects.select_for_update()
        .filter(
            space_booking=booking,
            activity__isnull=True,
            economic_scope=Payment.EconomicScope.SPACE_BOOKING,
            status__in=(Payment.Status.APPROVED, Payment.Status.PARTIALLY_REFUNDED),
        )
        .order_by('-approved_at', '-pk')
        .first()
    )
    if not payment:
        raise SpaceCancellationError('No existe un pago vigente que pueda revisarse.')
    if payment.settlement_status == Payment.SettlementStatus.SETTLED:
        raise SpaceCancellationError('El pago ya está liquidado; requiere un ajuste excepcional.')
    if payment.settlement_status == Payment.SettlementStatus.ON_HOLD:
        raise SpaceCancellationError('El pago ya tiene una retención económica que debe revisarse.')
    if payment.refunds.filter(
        status__in=(Refund.Status.REQUESTED, Refund.Status.APPROVED, Refund.Status.FAILED)
    ).exists():
        raise SpaceCancellationError('El pago ya tiene un reembolso sin resolución.')

    settlement = None
    if payment.settlement_id:
        settlement = Settlement.objects.select_for_update().get(pk=payment.settlement_id)
        if settlement.status == Settlement.Status.SETTLED:
            raise SpaceCancellationError('La jornada ya está liquidada.')

    cancellation = SpaceCancellationRequest(
        booking=booking,
        payment=payment,
        requested_by=actor,
        requested_role=requested_role,
        reason=reason,
    )
    cancellation.full_clean()
    cancellation.save()

    marker = _hold_marker(cancellation.pk)
    payment.settlement_status = Payment.SettlementStatus.ON_HOLD
    payment.settlement_hold_reason = marker
    payment.save(update_fields=['settlement_status', 'settlement_hold_reason', 'updated_at'])

    if settlement and settlement.status != Settlement.Status.ON_HOLD:
        settlement.status = Settlement.Status.ON_HOLD
        settlement.hold_reason = marker[:255]
        settlement.save(update_fields=['status', 'hold_reason', 'updated_at'])

    # Únicamente los pagos que aceptaron la política V1 son automáticos.
    # Todos los pagos anteriores conservan la revisión administrativa.
    if _can_automate_member_cancellation(requested_role, payment):
        decision = calculate_space_member_cancellation(
            payment.amount_clp,
            _service_start(booking),
            paid_at=payment.approved_at,
        )
        additional_refund = min(
            payment.refundable_amount_clp,
            max(decision.refund_amount_clp - payment.refunded_amount_clp, 0),
        )
        # La resolución usa el mismo bloqueo transaccional e historial que
        # la revisión administrativa; nunca se registra dos veces.
        cancellation, _ = resolve_paid_space_cancellation(
            cancellation_id=cancellation.pk,
            reviewer=None,
            approve=True,
            refund_amount_clp=additional_refund,
            review_notes=(
                f'Cancelación automática según {SPACE_POLICY_VERSION}: '
                f'{decision.bucket}; reembolso {decision.refund_percent}% '
                'del pago original, menos reembolsos previos; solo sandbox.'
            ),
            automated=True,
        )

    return cancellation, True


@transaction.atomic
def resolve_paid_space_cancellation(
    *,
    cancellation_id,
    reviewer,
    approve,
    refund_amount_clp=0,
    review_notes='',
    automated=False,
):
    """Resuelve una solicitud con trazabilidad y saldos contables en sandbox.

    No hay cargo ni abono bancario. Los reintentos sobre una solicitud resuelta
    devuelven el registro sin volver a crear Refund ni repetir el historial.
    """
    _require_sandbox()
    if not automated and not _reviewer_allowed(reviewer):
        raise SpaceCancellationError('Solo un administrador autorizado puede resolverla.')
    if automated and reviewer is not None:
        raise SpaceCancellationError('Una resolución automática no puede suplantar a un administrador.')

    review_notes = (review_notes or '').strip()
    if len(review_notes) < 5 or len(review_notes) > 1500:
        raise SpaceCancellationError(
            'La revisión debe explicar la decisión en 5 a 1500 caracteres.'
        )
    if type(refund_amount_clp) is not int or refund_amount_clp < 0:
        raise SpaceCancellationError('El reembolso debe ser un monto entero no negativo.')

    # Mismo orden de bloqueos que las vistas de reservas: Booking primero.
    # La lectura inicial solo resuelve el identificador de Booking.
    reference = SpaceCancellationRequest.objects.only('booking_id').get(
        pk=cancellation_id
    )
    booking = (
        SpaceBooking.objects.select_for_update()
        .select_related('space')
        .get(pk=reference.booking_id)
    )
    cancellation = (
        SpaceCancellationRequest.objects.select_for_update()
        .get(pk=cancellation_id, booking=booking)
    )
    if cancellation.status != SpaceCancellationRequest.Status.PENDING:
        return cancellation, False
    payment = Payment.objects.select_for_update().get(pk=cancellation.payment_id)
    if payment.space_booking_id != booking.pk:
        raise SpaceCancellationError('El pago y la reserva de la solicitud no coinciden.')
    if payment.settlement_status == Payment.SettlementStatus.SETTLED:
        raise SpaceCancellationError('No se puede modificar un pago ya liquidado.')
    if payment.status not in (Payment.Status.APPROVED, Payment.Status.PARTIALLY_REFUNDED):
        raise SpaceCancellationError('El estado de este pago ya no permite resolver la solicitud.')
    if booking.status != SpaceBooking.Status.CONFIRMED:
        raise SpaceCancellationError('La reserva cambió de estado durante la revisión.')

    marker = _hold_marker(cancellation.pk)
    if (
        payment.settlement_status != Payment.SettlementStatus.ON_HOLD
        or payment.settlement_hold_reason != marker
    ):
        raise SpaceCancellationError(
            'La retención del pago no coincide con esta solicitud. Revisión manual necesaria.'
        )
    if payment.refunds.filter(
        status__in=(Refund.Status.REQUESTED, Refund.Status.APPROVED, Refund.Status.FAILED)
    ).exists():
        raise SpaceCancellationError('Existe otro reembolso pendiente.')

    if automated:
        if (
            not approve
            or cancellation.requested_role != SpaceCancellationRequest.RequestedRole.MEMBER
            or cancellation.requested_by_id != booking.booked_by_id
            or payment.policy_version != SPACE_POLICY_VERSION
            or payment.policy_accepted_at is None
            or payment.approved_at is None
        ):
            raise SpaceCancellationError('La reserva no admite resolución automática.')
        try:
            decision = calculate_space_member_cancellation(
                payment.amount_clp,
                _service_start(booking),
                paid_at=payment.approved_at,
            )
        except (ValueError, TypeError) as exc:
            raise SpaceCancellationError(str(exc)) from exc
        expected_refund = min(
            payment.refundable_amount_clp,
            max(decision.refund_amount_clp - payment.refunded_amount_clp, 0),
        )
        if refund_amount_clp != expected_refund:
            raise SpaceCancellationError('El importe automático no coincide con la política aceptada.')

    settlement = None
    if payment.settlement_id:
        settlement = Settlement.objects.select_for_update().get(pk=payment.settlement_id)
        if settlement.status == Settlement.Status.SETTLED:
            raise SpaceCancellationError('Esta jornada ya está liquidada.')

    available = payment.refundable_amount_clp
    if approve:
        if refund_amount_clp > available:
            raise SpaceCancellationError('El reembolso supera el saldo disponible.')
        if (
            cancellation.requested_role == SpaceCancellationRequest.RequestedRole.PROVIDER
            and refund_amount_clp != available
        ):
            raise SpaceCancellationError(
                'Si cancela el proveedor, se devuelve el saldo completo al miembro.'
            )
    elif refund_amount_clp:
        raise SpaceCancellationError('Una solicitud rechazada no puede generar reembolso.')

    now = timezone.now()
    refund = None
    if approve:
        if refund_amount_clp:
            refund = Refund(
                payment=payment,
                requested_by=cancellation.requested_by,
                refund_type=(
                    Refund.RefundType.FULL
                    if refund_amount_clp == available
                    else Refund.RefundType.PARTIAL
                ),
                reason=(
                    Refund.Reason.PROVIDER_CANCELLATION
                    if cancellation.requested_role == SpaceCancellationRequest.RequestedRole.PROVIDER
                    else Refund.Reason.MEMBER_CANCELLATION
                ),
                amount_clp=refund_amount_clp,
                policy_percentage_snapshot=(
                    Decimal(refund_amount_clp) * Decimal('100') / Decimal(payment.amount_clp)
                ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
                policy_version_snapshot=(
                    SPACE_POLICY_VERSION if automated else 'SPACE_MANUAL_REVIEW_V1'
                ),
                status=Refund.Status.PROCESSED,
                notes=f'Reembolso contable sandbox. Resolución: {review_notes}',
                provider_reference=(
                    f'RFD-SPC-SBX-{str(payment.public_id).split("-")[0].upper()}'
                ),
                resolved_at=now,
                processed_at=now,
            )
            refund.full_clean()
            refund.save()
            payment.refunded_amount_clp += refund_amount_clp
            payment.status = (
                Payment.Status.REFUNDED
                if payment.refunded_amount_clp == payment.amount_clp
                else Payment.Status.PARTIALLY_REFUNDED
            )
            recalculate_payment_after_refund(payment, save=False)

        old_state = booking.audit_snapshot()
        booking.status = SpaceBooking.Status.CANCELLED
        booking.cancelled_at = now
        booking.cancellation_reason = cancellation.reason
        booking.save(update_fields=[
            'status', 'cancelled_at', 'cancellation_reason', 'updated_at',
        ])
        SpaceBookingHistory.objects.create(
            booking=booking,
            action=SpaceBookingHistory.Action.CANCELLED,
            previous_data=old_state,
            new_data=booking.audit_snapshot(),
            changed_by=cancellation.requested_by if automated else reviewer,
            reason=(
                f'Solicitud económica #{cancellation.pk} aprobada '
                + ('automáticamente. ' if automated else 'por administración. ')
                + review_notes
            )[:500],
        )
        cancellation.status = SpaceCancellationRequest.Status.APPROVED
        cancellation.refund_amount_clp = refund_amount_clp
        cancellation.refund = refund
    else:
        cancellation.status = SpaceCancellationRequest.Status.REJECTED

    cancellation.reviewed_by = reviewer
    cancellation.reviewed_at = now
    cancellation.review_notes = review_notes
    cancellation.full_clean()
    cancellation.save()

    payment.settlement_status = Payment.SettlementStatus.PENDING
    payment.settlement_hold_reason = ''
    payment.full_clean()
    payment.save(update_fields=[
        'status', 'refunded_amount_clp', 'commission_base_clp',
        'commission_amount_clp', 'net_amount_clp',
        'settlement_status', 'settlement_hold_reason', 'updated_at',
    ])

    # Solo levantamos la retención que puso ESTA solicitud. Una retención
    # anterior o ajena se conserva para una evaluación humana posterior.
    if settlement and settlement.hold_reason == marker[:255]:
        settlement.status = Settlement.Status.PENDING
        settlement.hold_reason = ''
        settlement.save(update_fields=['status', 'hold_reason', 'updated_at'])

    sync_space_day_settlement(booking.space, booking.session_date)
    return cancellation, True
