"""
V132.09D1 - Integración de novedades V128 y V132.09.

Combina las novedades actuales del Miembro con las reservas
profesionales conservadas en NotificationEvent.

No modifica reservas, pagos, espacios, actividades ni incidencias.

Mantiene las claves utilizadas por NotificationReadState.
"""

import re

from apps.bookings.models import Booking, BookingHistory

from .notification_event_service_v13209 import (
    list_notification_events,
)


MEMBER_SCOPE = "member"
BOOKING_CATEGORY = "booking"

MAX_MEMBER_UPDATES = 30
ARCHIVE_QUERY_LIMIT = 100

BOOKING_KEY_PATTERN = re.compile(
    r"professional-([1-9][0-9]*)\Z"
)


def _history_id_from_key(key):
    """
    Extrae el identificador del historial desde una clave
    utilizada por las novedades profesionales del Miembro.
    """

    if not isinstance(key, str):
        return None

    match = BOOKING_KEY_PATTERN.fullmatch(key)

    if not match:
        return None

    return int(match.group(1))


def _load_member_booking_histories(user, events):
    """
    Recupera en una consulta los historiales que todavía
    pertenecen al Miembro autenticado.

    No permite consultar reservas de otros usuarios.
    """

    history_ids = {
        history_id
        for event in events
        if (
            history_id := _history_id_from_key(
                event.notification_key
            )
        ) is not None
    }

    if not history_ids:
        return {}

    return (
        BookingHistory.objects
        .filter(
            pk__in=history_ids,
            booking__booked_by_id=user.pk,
        )
        .select_related(
            "booking__professional_profile__user"
        )
        .in_bulk()
    )


def _booking_kind(event, history):
    """
    Recupera el tipo de novedad desde BookingHistory.

    Si el historial original ya no existe, utiliza
    una clasificación básica del título archivado.
    """

    if history is not None:

        if history.action == BookingHistory.Action.CONFIRMED:
            return "confirmed"

        if history.action == BookingHistory.Action.CANCELLED:

            previous_status = (
                history.previous_data or {}
            ).get("status")

            if previous_status == Booking.Status.PENDING:
                return "rejected"

            return "cancelled"

    # Respaldo para eventos históricos sin BookingHistory.
    # Estos títulos son generados por el servidor.
    title = event.title.casefold()

    if (
        "no pudo aceptar" in title
        or "rechaz" in title
    ):
        return "rejected"

    if "confirm" in title:
        return "confirmed"

    if "cancel" in title:
        return "cancelled"

    return "updated"


def _archived_member_booking_card(event, history):
    """
    Convierte un NotificationEvent en una tarjeta compatible
    con el dashboard del Miembro.

    Conserva el contrato de datos utilizado por V128.
    """

    booking = (
        history.booking
        if history is not None
        else None
    )

    professional = (
        booking.professional_profile.user
        if booking is not None
        else None
    )

    professional_name = (
        (
            professional.get_full_name()
            or professional.email
            or "Profesional"
        )
        if professional is not None
        else ""
    )

    return {
        "key": event.notification_key,

        "module": "professional",

        "module_label": "SERVICIO PROFESIONAL",

        "kind": _booking_kind(
            event,
            history,
        ),

        "title": event.title,

        "summary": event.summary,

        # No recuperamos motivos libres desde el archivo.
        "reason": "",

        "subject": (
            booking.service_name_snapshot
            if booking is not None
            else ""
        ),

        "person": professional_name,

        "session_date": (
            booking.session_date
            if booking is not None
            else None
        ),

        "start_time": (
            booking.start_time
            if booking is not None
            else None
        ),

        "end_time": (
            booking.end_time
            if booking is not None
            else None
        ),

        "created_at": event.occurred_at,

        "detail_url": event.detail_url,
    }


def merge_member_notification_updates(
    user,
    current_updates,
    *,
    limit=30,
):
    """
    Combina las novedades existentes con eventos archivados.

    Reglas:

    1. Mantener las novedades actuales de V128.
    2. Incorporar reservas profesionales persistentes.
    3. Evitar duplicados por notification_key.
    4. Preferir la tarjeta actual cuando exista.
    5. Ordenar por fecha.
    6. Conservar el límite del dashboard.

    current_updates debe provenir exclusivamente del servidor,
    utilizando las fuentes autorizadas del usuario.
    """

    if (
        type(limit) is not int
        or not (1 <= limit <= MAX_MEMBER_UPDATES)
    ):
        raise ValueError(
            "El limite de novedades debe estar entre 1 y 30."
        )

    updates = list(current_updates)

    known_keys = {
        item["key"]
        for item in updates
    }

    archived = [
        event

        for event in list_notification_events(
            recipient=user,
            scope=MEMBER_SCOPE,
            limit=ARCHIVE_QUERY_LIMIT,
        )

        if (
            event.category == BOOKING_CATEGORY
            and event.notification_key not in known_keys
        )
    ]

    histories = (
        _load_member_booking_histories(
            user,
            archived,
        )
        if archived
        else {}
    )

    for event in archived:

        if event.notification_key in known_keys:
            continue

        history_id = _history_id_from_key(
            event.notification_key
        )

        history = histories.get(
            history_id
        )

        updates.append(
            _archived_member_booking_card(
                event,
                history,
            )
        )

        known_keys.add(
            event.notification_key
        )

    updates.sort(
        key=lambda item: item["created_at"],
        reverse=True,
    )

    return updates[:limit]