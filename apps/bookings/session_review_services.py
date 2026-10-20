"""Reglas transaccionales de conformidad de servicios profesionales."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Booking, BookingSessionReview


def review_hours():
    hours = int(
        getattr(
            settings,
            "BOOKING_REVIEW_WINDOW_HOURS",
            48
        )
    )

    return max(1, hours)


def start_review(booking):
    """
    Crear el registro de conformidad
    cuando una sesión se marca como completada.
    """

    if (
        booking.status != Booking.Status.COMPLETED
        or not booking.completed_at
    ):
        raise ValueError(
            "La reserva debe estar completada."
        )

    review, _ = BookingSessionReview.objects.get_or_create(
        booking=booking,
        defaults={
            "expires_at": (
                booking.completed_at
                + timedelta(hours=review_hours())
            )
        },
    )

    return review


def close_overdue_reviews():
    """
    Cerrar confirmaciones cuyo plazo terminó,
    sin atribuir conformidad al miembro.
    """

    return BookingSessionReview.objects.filter(
        status=BookingSessionReview.Status.PENDING,
        expires_at__lte=timezone.now(),
    ).update(
        status=BookingSessionReview.Status.NO_RESPONSE,
        updated_at=timezone.now(),
    )