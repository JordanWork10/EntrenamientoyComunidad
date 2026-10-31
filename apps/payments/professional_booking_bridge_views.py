"""V131.75: vistas de reservas individuales conectadas con pagos.

Se activan desde bookings/urls.py sin sustituir el resto de bookings/views.py.
"""

from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.bookings.models import Booking
from apps.bookings.services import expire_pending_bookings
from apps.professionals.models import ProfessionalProfile

from .models import Payment
from .services.professional_booking_payments import (
    PAID_HISTORY_STATUSES,
    ProfessionalBookingPaymentError,
    cancel_professional_booking_with_refund,
)


def _session_datetime(booking, *, end=False):
    value = datetime.combine(
        booking.session_date,
        booking.end_time if end else booking.start_time,
    )
    return timezone.make_aware(value, timezone.get_current_timezone())


def _associated_payment(booking):
    payments = Payment.objects.filter(
        professional_booking=booking,
        economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
    )
    historic = payments.filter(
        status__in=PAID_HISTORY_STATUSES,
    ).order_by('-approved_at').first()
    if historic is not None:
        return historic
    return payments.order_by('-created_at').first()


@login_required(login_url='accounts:login')
def booking_detail(request, booking_id):
    expire_pending_bookings(booked_by=request.user)
    booking = get_object_or_404(
        Booking.objects.select_related(
            'service', 'professional_profile', 'professional_profile__user',
        ),
        pk=booking_id,
        booked_by=request.user,
    )
    payment = _associated_payment(booking)
    session_start_datetime = _session_datetime(booking)
    can_cancel = (
        booking.status in (Booking.Status.PENDING, Booking.Status.CONFIRMED)
        and timezone.now() < session_start_datetime
        and not (
            payment is not None
            and payment.status in PAID_HISTORY_STATUSES
            and payment.settlement_status in (
                Payment.SettlementStatus.SETTLED,
                Payment.SettlementStatus.ON_HOLD,
            )
        )
    )
    can_pay = (
        booking.status == Booking.Status.CONFIRMED
        and booking.price_clp > 0
        and bool(getattr(settings, 'PAYMENTS_SANDBOX', False))
        and timezone.now() < session_start_datetime
        and not (payment is not None and payment.status in PAID_HISTORY_STATUSES)
    )
    return render(request, 'bookings/booking_detail.html', {
        'booking': booking,
        'history_entries': booking.history.select_related('changed_by').order_by('-created_at'),
        'session_start_datetime': session_start_datetime,
        'can_cancel': can_cancel,
        'can_pay': can_pay,
        'booking_payment': payment,
        'sandbox_enabled': bool(getattr(settings, 'PAYMENTS_SANDBOX', False)),
    })


def _verified_professional(request):
    profile = getattr(request.user, 'professional_profile', None)
    if profile is None or (
        profile.verification_status
        != ProfessionalProfile.VerificationStatus.VERIFIED
    ):
        return None
    return profile


@login_required(login_url='accounts:login')
def professional_booking_detail(request, booking_id):
    profile = _verified_professional(request)
    if profile is None:
        return redirect('accounts:dashboard')

    expire_pending_bookings(professional_profile=profile)
    booking = get_object_or_404(
        Booking.objects.select_related('booked_by', 'service', 'professional_profile'),
        pk=booking_id,
        professional_profile=profile,
    )
    session_end_datetime = _session_datetime(booking, end=True)
    return render(request, 'bookings/professional_booking_detail.html', {
        'booking': booking,
        'professional_profile': profile,
        'history_entries': booking.history.select_related('changed_by').order_by('-created_at'),
        'session_end_datetime': session_end_datetime,
        'can_complete': (
            booking.status == Booking.Status.CONFIRMED
            and timezone.now() >= session_end_datetime
        ),
        'booking_payment': _associated_payment(booking),
    })


@login_required(login_url='accounts:login')
@require_POST
def cancel_my_booking(request, booking_id):
    expire_pending_bookings(booked_by=request.user)
    get_object_or_404(Booking, pk=booking_id, booked_by=request.user)
    try:
        outcome = cancel_professional_booking_with_refund(
            booking_id, request.user,
            by_professional=False,
            reason=request.POST.get('cancellation_reason', ''),
        )
    except (ProfessionalBookingPaymentError, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        if outcome.refund is not None:
            amount = f'${outcome.refund.amount_clp:,}'.replace(',', '.')
            messages.success(
                request,
                f'Reserva cancelada. Reembolso sandbox registrado: {amount} CLP.',
            )
        else:
            messages.success(request, 'Tu reserva fue cancelada correctamente.')
    return redirect('bookings:detail', booking_id=booking_id)


@login_required(login_url='accounts:login')
@require_POST
def professional_cancel_booking(request, booking_id):
    profile = _verified_professional(request)
    if profile is None:
        return redirect('accounts:dashboard')
    expire_pending_bookings(professional_profile=profile)
    get_object_or_404(Booking, pk=booking_id, professional_profile=profile)

    try:
        outcome = cancel_professional_booking_with_refund(
            booking_id, request.user,
            by_professional=True,
            reason=request.POST.get('cancellation_reason', ''),
        )
    except (ProfessionalBookingPaymentError, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        if outcome.refund is not None:
            messages.success(
                request,
                'Reserva cancelada y reembolso completo registrado en sandbox. '
                'El horario permanecerá bloqueado para tus servicios.',
            )
        else:
            messages.success(
                request,
                'Reserva cancelada. El horario quedó bloqueado para tus servicios.',
            )
    return redirect('bookings:professional_detail', booking_id=booking_id)
