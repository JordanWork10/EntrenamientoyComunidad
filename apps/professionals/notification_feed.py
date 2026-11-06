"""
V128/V132.09E3 - Novedades del Centro Profesional.

La misma función alimenta el dashboard y las rutas de lectura para
que la lista de claves autorizadas no pueda diferir de la mostrada.
No crea ni modifica reservas, historiales o incidencias.
"""

from django.core.exceptions import PermissionDenied

from apps.bookings.models import Booking, BookingHistory
from apps.bookings.incident_notifications import get_session_incident_updates

from .models import ProfessionalProfile
from .professional_notification_feed_merge_v13209 import (
    merge_professional_notification_updates,
)


def get_professional_updates_for(user):
    """Devuelve hasta 30 novedades autorizadas del Profesional autenticado.

    Incluye las novedades actuales de V128 y V123, más los avisos de
    reservas que permanecen guardados mediante NotificationEvent.
    El dashboard decidirá cuántas mostrar inicialmente.
    """

    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Debes iniciar sesión.")

    professional_profile = getattr(user, "professional_profile", None)
    if (
        professional_profile is None
        or professional_profile.verification_status
        != ProfessionalProfile.VerificationStatus.VERIFIED
    ):
        raise PermissionDenied("Necesitas un Perfil Profesional verificado.")

    # =====================================================
    # V128 - NOVEDADES ACTUALES DEL PROFESIONAL
    # =====================================================
    # Los cambios de reservas proceden de BookingHistory.
    # Solo se muestran eventos originados por miembros:
    # - solicitud que todavía está pendiente;
    # - cancelación realizada por el miembro.
    # Los cambios del propio profesional no generan tarjetas para él.

    professional_history_events = (
        BookingHistory.objects
        .filter(
            booking__professional_profile=professional_profile,
            action__in=[
                BookingHistory.Action.CREATED,
                BookingHistory.Action.CANCELLED,
            ],
            changed_by__isnull=False,
        )
        .exclude(changed_by=user)
        .select_related(
            "booking",
            "booking__booked_by",
            "booking__service",
            "changed_by",
        )
        .order_by("-created_at", "-id")[:40]
    )

    booking_updates = []
    seen_booking_ids = set()

    for event in professional_history_events:
        booking = event.booking

        # Una sola novedad vigente por reserva.
        if booking.id in seen_booking_ids:
            continue

        member = booking.booked_by
        member_name = member.get_full_name() or member.email

        if event.action == BookingHistory.Action.CREATED:
            if booking.status != Booking.Status.PENDING:
                continue

            kind = "request"
            title = f"{member_name} envió una nueva solicitud"
            summary = f"Quiere reservar {booking.service_name_snapshot}."
            reason = ""

        elif event.action == BookingHistory.Action.CANCELLED:
            if booking.status != Booking.Status.CANCELLED:
                continue

            previous_status = (event.previous_data or {}).get("status")
            kind = "cancelled"

            if previous_status == Booking.Status.PENDING:
                title = f"{member_name} canceló su solicitud"
                summary = (
                    f"La solicitud para {booking.service_name_snapshot} "
                    "ya no requiere respuesta."
                )
            else:
                title = f"{member_name} canceló su reserva"
                summary = (
                    f"La sesión de {booking.service_name_snapshot} "
                    "ya no se realizará."
                )

            reason = event.reason or booking.cancellation_reason or ""

        else:
            continue

        booking_updates.append(
            {
                "key": f"booking-history-{event.id}",
                "kind": kind,
                "title": title,
                "summary": summary,
                "reason": reason,
                "booking": booking,
                "member": member,
                "created_at": event.created_at,
            }
        )

        seen_booking_ids.add(booking.id)

    # =====================================================
    # V123 - INCIDENCIAS
    # =====================================================
    # Conservamos los avisos de incidencias, sus claves y sus enlaces.

    incident_updates = get_session_incident_updates(
        user,
        "professional",
        limit=30,
    )

    # =====================================================
    # V132.09E - HISTORIAL PERSISTENTE DE RESERVAS
    # =====================================================
    # El adaptador agrega los NotificationEvent propios, sin duplicar
    # los eventos vigentes ya obtenidos de BookingHistory y sin
    # modificar incidencias. El límite de 30 se aplica una sola vez,
    # después de mezclar y ordenar todas las fuentes autorizadas.

    current_updates = booking_updates + incident_updates

    return merge_professional_notification_updates(
        user,
        current_updates,
        limit=30,
    )