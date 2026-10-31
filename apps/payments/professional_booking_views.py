"""V131.75: checkout y comprobante sandbox de sesiones individuales."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.bookings.models import Booking

from .models import Payment
from .services.professional_booking_payments import (
    ProfessionalBookingPaymentError,
    approve_professional_booking_payment,
    close_pending_professional_payment,
    open_professional_booking_payment,
)


def _payment_for_member(request, payment_id):
    return get_object_or_404(
        Payment.objects.select_related(
            'professional_booking',
            'professional_booking__professional_profile__user',
        ),
        public_id=payment_id,
        payer=request.user,
        professional_booking__isnull=False,
        economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
    )


@login_required(login_url='accounts:login')
@require_GET
def professional_booking_checkout(request, booking_id):
    """Crea/reutiliza un intento solo del Miembro y su reserva aceptada."""
    booking = get_object_or_404(
        Booking.objects.select_related('professional_profile__user'),
        pk=booking_id,
        booked_by=request.user,
    )

    try:
        payment = open_professional_booking_payment(booking.pk, request.user)
    except (ProfessionalBookingPaymentError, ValidationError) as exc:
        messages.error(request, str(exc))
        return redirect('bookings:detail', booking_id=booking.pk)

    if payment.status != Payment.Status.PENDING:
        return redirect('payments:professional_booking_receipt', payment_id=payment.public_id)

    return render(request, 'payments/professional_booking_checkout.html', {
        'booking': booking,
        'payment': payment,
        'sandbox_enabled': bool(getattr(settings, 'PAYMENTS_SANDBOX', False)),
    })


@login_required(login_url='accounts:login')
@require_GET
def professional_booking_receipt(request, payment_id):
    """Comprobante visible exclusivamente para el Miembro pagador."""
    payment = _payment_for_member(request, payment_id)
    return render(request, 'payments/professional_booking_receipt.html', {
        'payment': payment,
        'booking': payment.professional_booking,
        'refunds': payment.refunds.order_by('-requested_at'),
        'retained_amount_clp': max(
            payment.amount_clp - payment.refunded_amount_clp, 0,
        ),
    })


@login_required(login_url='accounts:login')
@require_POST
def professional_booking_sandbox_approve(request, payment_id):
    payment = _payment_for_member(request, payment_id)
    try:
        approve_professional_booking_payment(
            payment.public_id,
            request.user,
            accepts_policy=request.POST.get('accept_policy') == '1',
            accepts_sandbox=request.POST.get('accept_sandbox') == '1',
        )
    except (ProfessionalBookingPaymentError, ValidationError, IntegrityError) as exc:
        messages.error(request, str(exc))
        return redirect(
            'payments:professional_booking_checkout',
            booking_id=payment.professional_booking_id,
        )

    messages.success(request, 'Pago aprobado en sandbox. No hubo ningún cobro real.')
    return redirect('payments:professional_booking_receipt', payment_id=payment.public_id)


@login_required(login_url='accounts:login')
@require_POST
def professional_booking_sandbox_reject(request, payment_id):
    payment = _payment_for_member(request, payment_id)
    try:
        close_pending_professional_payment(
            payment.public_id, request.user, rejected=True,
        )
    except (ProfessionalBookingPaymentError, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.warning(request, 'El intento fue rechazado en sandbox; tu reserva sigue aceptada.')

    return redirect('payments:professional_booking_receipt', payment_id=payment.public_id)


@login_required(login_url='accounts:login')
@require_POST
def professional_booking_cancel_attempt(request, payment_id):
    payment = _payment_for_member(request, payment_id)
    try:
        close_pending_professional_payment(payment.public_id, request.user)
    except (ProfessionalBookingPaymentError, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.info(request, 'Intento cancelado. La sesión permanece aceptada.')

    return redirect('payments:professional_booking_receipt', payment_id=payment.public_id)
