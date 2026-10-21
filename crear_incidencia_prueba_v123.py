"""
V123 - Crear incidencia ficticia para probar
la respuesta del Profesional.

SOLO PARA EL ENTORNO DE DESARROLLO.

Reserva #3:
Miembro: Roberto Tototo
Profesional: Juan Moraga
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.bookings.models import (
    Booking,
    BookingSessionReview,
    BookingSessionIncident,
)


def crear_incidencia_prueba():

    # -----------------------------------------
    # 1. IMPEDIR EJECUCIÓN EN PRODUCCIÓN
    # -----------------------------------------

    if not settings.DEBUG:
        print(
            "ERROR: Este script solo puede ejecutarse "
            "en el entorno de desarrollo."
        )
        return

    # -----------------------------------------
    # 2. CREAR LOS REGISTROS EN UNA TRANSACCIÓN
    # -----------------------------------------

    with transaction.atomic():

        booking = Booking.objects.get(
            pk=3,
            status=Booking.Status.COMPLETED,
        )

        # No alterar una conformidad existente.
        if BookingSessionReview.objects.filter(
            booking=booking
        ).exists():

            print(
                "La reserva #3 ya tiene una conformidad. "
                "No se modificó ningún registro."
            )
            return

        now = timezone.now()

        # -------------------------------------
        # 3. CREAR CONFORMIDAD FICTICIA
        # -------------------------------------

        review = BookingSessionReview(
            booking=booking,
            status=BookingSessionReview.Status.REPORTED,
            expires_at=now + timedelta(hours=48),
            responded_at=now,
            issue_reason=(
                "[PRUEBA V123] El miembro indica que "
                "la sesión presentó inconvenientes "
                "y solicita una revisión de la plataforma."
            ),
            rating_comment="",
        )

        review.full_clean()
        review.save()

        # -------------------------------------
        # 4. CREAR INCIDENCIA ADMINISTRATIVA
        # -------------------------------------

        incident = BookingSessionIncident(
            review=review,
            status=BookingSessionIncident.Status.OPEN,
        )

        incident.full_clean()
        incident.save()

    # -----------------------------------------
    # 5. MOSTRAR RESULTADOS
    # -----------------------------------------

    print("===================================")
    print("V123 - INCIDENCIA DE PRUEBA CREADA")
    print("===================================")

    print("Reserva:", booking.id)
    print("Miembro:", booking.booked_by)
    print("Profesional:", booking.professional_profile.user)
    print("Conformidad:", review.get_status_display())
    print("Incidencia:", incident.get_status_display())
    print("ID de incidencia:", incident.id)

    print("===================================")
    print("LISTO PARA PROBAR RESPUESTA PROFESIONAL")
    print("===================================")


crear_incidencia_prueba()