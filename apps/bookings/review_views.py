"""Confirmación por el miembro, reporte de incidencias y estrellas."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Booking, BookingSessionReview


def _owned_review(request, booking_id, lock=False):
    qs = BookingSessionReview.objects.select_related(
        'booking',
        'booking__professional_profile__user',
        'booking__booked_by'
    )

    if lock:
        qs = qs.select_for_update()

    return get_object_or_404(
        qs,
        booking_id=booking_id,
        booking__booked_by=request.user,
        booking__status=Booking.Status.COMPLETED,
    )


@login_required(login_url='accounts:login')
def review_session(request, booking_id):
    review = _owned_review(request, booking_id)

    return render(
        request,
        'bookings/session_review.html',
        {
            'review': review,
            'booking': review.booking,
            'window_open': (
                review.status == BookingSessionReview.Status.PENDING
                and review.expires_at > timezone.now()
            ),
            'stars': range(1, 6),
        }
    )


@login_required(login_url='accounts:login')
@require_POST
def confirm_session(request, booking_id):

    with transaction.atomic():

        review = _owned_review(
            request,
            booking_id,
            lock=True
        )

        if (
            review.status != BookingSessionReview.Status.PENDING
            or review.expires_at <= timezone.now()
        ):
            messages.warning(
                request,
                'Esta confirmación ya fue resuelta o venció.'
            )

        else:
            review.status = BookingSessionReview.Status.CONFIRMED
            review.responded_at = timezone.now()

            review.save(
                update_fields=[
                    'status',
                    'responded_at',
                    'updated_at'
                ]
            )

            messages.success(
                request,
                'Gracias por confirmar que recibiste la sesión. '
                'Puedes evaluarla si quieres.'
            )

    return redirect(
        'bookings:session_review',
        booking_id=booking_id
    )


@login_required(login_url='accounts:login')
@require_POST
def report_session(request, booking_id):

    reason = (
        request.POST.get('issue_reason') or ''
    ).strip()

    if len(reason) < 10 or len(reason) > 1000:

        messages.error(
            request,
            'Explica qué ocurrió usando entre 10 y 1000 caracteres.'
        )

        return redirect(
            'bookings:session_review',
            booking_id=booking_id
        )

    with transaction.atomic():

        review = _owned_review(
            request,
            booking_id,
            lock=True
        )

        if (
            review.status != BookingSessionReview.Status.PENDING
            or review.expires_at <= timezone.now()
        ):
            messages.warning(
                request,
                'El plazo para responder ya venció o ya respondiste.'
            )

        else:
            review.status = BookingSessionReview.Status.REPORTED
            review.issue_reason = reason
            review.responded_at = timezone.now()

            review.save(
                update_fields=[
                    'status',
                    'issue_reason',
                    'responded_at',
                    'updated_at'
                ]
            )

            messages.success(
                request,
                'Registramos el problema. '
                'Quedó pendiente de revisión por la plataforma.'
            )

    return redirect(
        'bookings:session_review',
        booking_id=booking_id
    )


@login_required(login_url='accounts:login')
@require_POST
def rate_session(request, booking_id):

    rating_raw = (
        request.POST.get('rating') or ''
    ).strip()

    comment = (
        request.POST.get('rating_comment') or ''
    ).strip()

    try:
        rating = int(rating_raw)

    except (TypeError, ValueError):
        rating = 0

    if rating not in (1, 2, 3, 4, 5) or len(comment) > 500:

        messages.error(
            request,
            'Elige entre 1 y 5 estrellas '
            'y usa un comentario de hasta 500 caracteres.'
        )

        return redirect(
            'bookings:session_review',
            booking_id=booking_id
        )

    with transaction.atomic():

        review = _owned_review(
            request,
            booking_id,
            lock=True
        )

        if review.status != BookingSessionReview.Status.CONFIRMED:

            messages.error(
                request,
                'Solo puedes evaluar una sesión que confirmaste.'
            )

        elif review.rated_at is not None:

            messages.warning(
                request,
                'Esta sesión ya tiene una evaluación registrada.'
            )

        else:
            review.rating = rating
            review.rating_comment = comment
            review.rated_at = timezone.now()

            review.save(
                update_fields=[
                    'rating',
                    'rating_comment',
                    'rated_at',
                    'updated_at'
                ]
            )

            messages.success(
                request,
                '¡Gracias! Tu evaluación quedó registrada.'
            )

    return redirect(
        'bookings:session_review',
        booking_id=booking_id
    )