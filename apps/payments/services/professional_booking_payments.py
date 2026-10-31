"""Pagos sandbox y cancelaciones económicas de sesiones individuales.

Este módulo no transfiere dinero. Mantiene separados los pagos de sesiones,
actividades profesionales y arriendos de espacios.
"""

from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.bookings.models import Booking, BookingHistory
from apps.professionals.models import ProfessionalProfile

from ..models import Payment, Refund
from .cancellation_policy import (
    PAYMENTS_POLICY_VERSION,
    calculate_forced_full_refund,
    calculate_member_cancellation,
)
from .commissions import (
    apply_payment_commission_snapshot,
    recalculate_payment_after_refund,
)
from .settlements import refresh_payment_settlement_status


class ProfessionalBookingPaymentError(Exception):
    """Operación de pago o cancelación individual no permitida."""


@dataclass(frozen=True)
class BookingCancellationOutcome:
    booking: Booking
    payment: Payment | None
    refund: Refund | None


FINANCIAL_STATUSES = (
    Payment.Status.APPROVED,
    Payment.Status.PARTIALLY_REFUNDED,
)

PAID_HISTORY_STATUSES = (
    Payment.Status.APPROVED,
    Payment.Status.PARTIALLY_REFUNDED,
    Payment.Status.REFUNDED,
)


def _session_datetime(booking, *, end=False):
    session_time = booking.end_time if end else booking.start_time
    value = datetime.combine(booking.session_date, session_time)
    return timezone.make_aware(value, timezone.get_current_timezone())


def _sandbox_required():
    if not getattr(settings, 'PAYMENTS_SANDBOX', False):
        raise ProfessionalBookingPaymentError(
            'La simulación de pagos no está habilitada.'
        )


def _payment_allowed(booking, now):
    return (
        booking.status == Booking.Status.CONFIRMED
        and booking.price_clp > 0
        and booking.booked_by_id != booking.professional_profile.user_id
        and booking.professional_profile.verification_status
        == ProfessionalProfile.VerificationStatus.VERIFIED
        and _session_datetime(booking) > now
    )


@transaction.atomic
def open_professional_booking_payment(booking_id, member, now=None):
    """Recupera o crea un único intento pendiente para una sesión aceptada."""
    _sandbox_required()
    now = now or timezone.now()

    booking = (
        Booking.objects
        .select_for_update()
        .select_related('professional_profile__user')
        .get(pk=booking_id, booked_by=member)
    )

    active_payment = (
        Payment.objects
        .filter(professional_booking=booking, status__in=PAID_HISTORY_STATUSES)
        .order_by('-approved_at')
        .first()
    )
    if active_payment is not None:
        return active_payment

    if not _payment_allowed(booking, now):
        raise ProfessionalBookingPaymentError(
            'La reserva debe estar aceptada, vigente y habilitada para pagar.'
        )

    pending = (
        Payment.objects
        .select_for_update()
        .filter(
            professional_booking=booking,
            payer=member,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
            status=Payment.Status.PENDING,
            amount_clp=booking.price_clp,
        )
        .order_by('-created_at')
        .first()
    )
    if pending is not None:
        return pending

    payment = Payment(
        payer=member,
        professional_booking=booking,
        activity=None,
        space_booking=None,
        economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
        amount_clp=booking.price_clp,
        currency='CLP',
        provider=Payment.Provider.SANDBOX,
        status=Payment.Status.PENDING,
    )
    payment.full_clean()
    payment.save()
    return payment


def _payment_booking_id(payment_public_id, member):
    payment = (
        Payment.objects
        .filter(
            public_id=payment_public_id,
            payer=member,
            professional_booking__isnull=False,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
        )
        .values('pk', 'professional_booking_id')
        .first()
    )
    if payment is None:
        raise ProfessionalBookingPaymentError(
            'El pago solicitado no pertenece a esta cuenta.'
        )
    return payment['pk'], payment['professional_booking_id']


@transaction.atomic
def approve_professional_booking_payment(
    payment_public_id,
    member,
    *,
    accepts_policy=False,
    accepts_sandbox=False,
    now=None,
):
    """Aprueba un pago sandbox con bloqueo de reserva y precio histórico."""
    _sandbox_required()
    now = now or timezone.now()
    payment_id, booking_id = _payment_booking_id(payment_public_id, member)

    booking = (
        Booking.objects
        .select_for_update()
        .select_related('professional_profile__user')
        .get(pk=booking_id, booked_by=member)
    )
    payment = (
        Payment.objects
        .select_for_update()
        .get(pk=payment_id, payer=member, professional_booking=booking)
    )

    if payment.status == Payment.Status.APPROVED:
        return payment

    if payment.status != Payment.Status.PENDING:
        raise ProfessionalBookingPaymentError(
            'Este intento de pago ya finalizó; inicia uno nuevo.'
        )

    if not accepts_policy or not accepts_sandbox:
        raise ProfessionalBookingPaymentError(
            'Debes aceptar la política de cancelación y confirmar el sandbox.'
        )

    if not _payment_allowed(booking, now):
        raise ProfessionalBookingPaymentError(
            'La sesión ya no está habilitada para recibir pagos.'
        )

    if payment.amount_clp != booking.price_clp:
        raise ProfessionalBookingPaymentError(
            'El importe ya no coincide con el precio registrado en la reserva.'
        )

    if Payment.objects.filter(
        professional_booking=booking,
        status__in=PAID_HISTORY_STATUSES,
    ).exclude(pk=payment.pk).exists():
        raise ProfessionalBookingPaymentError(
            'Esta reserva ya registra un pago aprobado.'
        )

    payment.status = Payment.Status.APPROVED
    payment.approved_at = now
    payment.provider_reference = (
        f'SBX-PRF-{str(payment.public_id).split("-")[0].upper()}'
    )
    payment.failure_reason = ''
    payment.policy_version = PAYMENTS_POLICY_VERSION
    payment.policy_accepted_at = now

    apply_payment_commission_snapshot(payment, at=now, save=False)
    refresh_payment_settlement_status(
        payment,
        service_end=_session_datetime(booking, end=True),
        now=now,
        save=False,
    )

    payment.full_clean()
    payment.save(update_fields=[
        'status', 'approved_at', 'provider_reference', 'failure_reason',
        'policy_version', 'policy_accepted_at', 'plan_code_snapshot',
        'commission_rate_percent', 'commission_base_clp',
        'commission_amount_clp', 'net_amount_clp', 'settlement_status',
        'settlement_eligible_at', 'updated_at',
    ])

    Payment.objects.filter(
        professional_booking=booking,
        status=Payment.Status.PENDING,
    ).exclude(pk=payment.pk).update(
        status=Payment.Status.CANCELLED,
        failure_reason='Otro intento de esta reserva fue aprobado.',
        updated_at=now,
    )
    return payment


@transaction.atomic
def close_pending_professional_payment(
    payment_public_id, member, *, rejected=False,
):
    """Cierra solamente el intento, sin alterar la reserva aceptada."""
    _sandbox_required()
    payment_id, booking_id = _payment_booking_id(payment_public_id, member)
    booking = Booking.objects.select_for_update().get(
        pk=booking_id, booked_by=member,
    )
    payment = Payment.objects.select_for_update().get(
        pk=payment_id, payer=member, professional_booking=booking,
    )
    if payment.status != Payment.Status.PENDING:
        raise ProfessionalBookingPaymentError(
            'Este intento ya no puede modificarse.'
        )

    payment.status = (
        Payment.Status.FAILED if rejected else Payment.Status.CANCELLED
    )
    payment.failure_reason = (
        'Pago rechazado en sandbox.'
        if rejected else 'Intento cancelado por el Miembro.'
    )
    payment.save(update_fields=['status', 'failure_reason', 'updated_at'])
    return payment


@transaction.atomic
def cancel_professional_booking_with_refund(
    booking_id,
    actor,
    *,
    by_professional,
    reason,
    cancelled_at=None,
):
    """Cancela la reserva y registra su reembolso de forma indivisible.

    El bloqueo del Perfil Profesional es consistente con create_booking().
    Las cancelaciones hechas por el profesional permanecen bloqueadas en
    el calendario porque BookingHistory guarda al profesional como actor.
    """
    cancelled_at = cancelled_at or timezone.now()
    reason = (reason or '').strip()
    if len(reason) < 5:
        raise ProfessionalBookingPaymentError(
            'Debes indicar un motivo de al menos cinco caracteres.'
        )

    profile_id = (
        Booking.objects
        .filter(pk=booking_id)
        .values_list('professional_profile_id', flat=True)
        .first()
    )
    if profile_id is None:
        raise ProfessionalBookingPaymentError('La reserva no existe.')

    ProfessionalProfile.objects.select_for_update().get(pk=profile_id)
    booking = (
        Booking.objects
        .select_for_update()
        .select_related('professional_profile__user', 'service')
        .get(pk=booking_id)
    )

    authorized_user_id = (
        booking.professional_profile.user_id
        if by_professional else booking.booked_by_id
    )
    if actor.id != authorized_user_id:
        raise ProfessionalBookingPaymentError(
            'No tienes permiso para cancelar esta reserva.'
        )

    if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
        raise ProfessionalBookingPaymentError(
            'Esta reserva ya no admite cancelación.'
        )

    if not by_professional and cancelled_at >= _session_datetime(booking):
        raise ProfessionalBookingPaymentError(
            'La sesión ya comenzó y no admite cancelación automática.'
        )

    payment = (
        Payment.objects
        .select_for_update()
        .filter(professional_booking=booking, status__in=FINANCIAL_STATUSES)
        .order_by('-approved_at')
        .first()
    )
    refund = None

    if payment is not None:
        if payment.settlement_status in (
            Payment.SettlementStatus.ON_HOLD,
            Payment.SettlementStatus.SETTLED,
        ):
            raise ProfessionalBookingPaymentError(
                'El pago ya fue liquidado o está en revisión. '
                'La cancelación requiere intervención administrativa.'
            )

        if payment.refunds.filter(status__in=[
            Refund.Status.REQUESTED,
            Refund.Status.APPROVED,
            Refund.Status.PROCESSED,
            Refund.Status.FAILED,
        ]).exists():
            raise ProfessionalBookingPaymentError(
                'Este pago ya registra un reembolso o una revisión pendiente.'
            )

        if by_professional:
            decision = calculate_forced_full_refund(payment.amount_clp)
            refund_reason = Refund.Reason.PROFESSIONAL_CANCELLATION
        else:
            if (
                payment.policy_version != PAYMENTS_POLICY_VERSION
                or payment.policy_accepted_at is None
            ):
                raise ProfessionalBookingPaymentError(
                    'Este pago requiere revisión de la política aceptada.'
                )
            decision = calculate_member_cancellation(
                amount_clp=payment.amount_clp,
                service_start=_session_datetime(booking),
                cancelled_at=cancelled_at,
            )
            refund_reason = Refund.Reason.MEMBER_CANCELLATION

        if decision.refund_amount_clp <= 0:
            raise ProfessionalBookingPaymentError(
                'La cancelación no genera un reembolso automático.'
            )

        refund = Refund(
            payment=payment,
            requested_by=actor,
            refund_type=(
                Refund.RefundType.FULL
                if decision.refund_amount_clp == payment.amount_clp
                else Refund.RefundType.PARTIAL
            ),
            reason=refund_reason,
            amount_clp=decision.refund_amount_clp,
            policy_percentage_snapshot=decision.refund_percent,
            hours_before_service_snapshot=decision.hours_before_service,
            policy_version_snapshot=decision.policy_version,
            status=Refund.Status.PROCESSED,
            notes=(
                'Devolución contable sandbox por cancelación de sesión individual.'
            ),
            provider_reference=(
                f'RFD-PRF-{str(payment.public_id).split("-")[0].upper()}'
            ),
            resolved_at=cancelled_at,
            processed_at=cancelled_at,
        )
        refund.full_clean()
        refund.save()

        payment.refunded_amount_clp += decision.refund_amount_clp
        payment.status = (
            Payment.Status.REFUNDED
            if payment.refunded_amount_clp == payment.amount_clp
            else Payment.Status.PARTIALLY_REFUNDED
        )
        recalculate_payment_after_refund(payment, save=False)
        payment.full_clean()
        payment.save(update_fields=[
            'refunded_amount_clp', 'status', 'commission_base_clp',
            'commission_amount_clp', 'net_amount_clp', 'updated_at',
        ])

    # Los intentos no aprobados no representan dinero cobrado.
    Payment.objects.filter(
        professional_booking=booking,
        status=Payment.Status.PENDING,
    ).update(
        status=Payment.Status.CANCELLED,
        failure_reason='La reserva vinculada fue cancelada.',
        updated_at=cancelled_at,
    )

    previous_data = booking.audit_snapshot()
    booking.status = Booking.Status.CANCELLED
    booking.cancellation_reason = reason
    booking.cancelled_at = cancelled_at
    booking.save(update_fields=[
        'status', 'cancellation_reason', 'cancelled_at', 'updated_at',
    ])
    BookingHistory.objects.create(
        booking=booking,
        action=BookingHistory.Action.CANCELLED,
        previous_data=previous_data,
        new_data=booking.audit_snapshot(),
        changed_by=actor,
        reason=reason,
    )

    return BookingCancellationOutcome(
        booking=booking,
        payment=payment,
        refund=refund,
    )
