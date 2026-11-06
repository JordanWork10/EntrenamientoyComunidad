"""
V132.09E1 - Historial persistente del Centro Profesional.

Combina las novedades actuales de V128 con los eventos
de reservas profesionales almacenados en NotificationEvent.

No crea notificaciones ni modifica reservas, incidencias,
pagos o historiales de reservas.

Conserva las claves utilizadas por NotificationReadState.
"""

import re

from apps.accounts.notification_event_service_v13209 import (
    list_notification_events,
)

from apps.bookings.models import Booking, BookingHistory


PROFESSIONAL_SCOPE = "professional"
BOOKING_CATEGORY = "booking"

MAX_PROFESSIONAL_UPDATES = 30
ARCHIVE_QUERY_LIMIT = 100

BOOKING_HISTORY_KEY = re.compile(
    r"booking-history-([1-9][0-9]*)\Z"
)


def _history_id_from_key(key):
    """
    Extrae el identificador de BookingHistory
    desde una clave válida.
    """

    if not isinstance(key, str):
        return None

    match = BOOKING_HISTORY_KEY.fullmatch(key)

    if not match:
        return None

    return int(match.group(1))


def _load_professional_booking_histories(user, events):
    """
    Recupera los historiales que pertenecen al Profesional.

    Filtra por el usuario propietario del Perfil Profesional,
    evitando consultar reservas de otros profesionales.
    """

    ids = {
        history_id

        for event in events

        if (
            history_id := _history_id_from_key(
                event.notification_key
            )
        ) is not None
    }

    if not ids:
        return {}

    return (
        BookingHistory.objects
        .filter(
            pk__in=ids,
            booking__professional_profile__user_id=user.pk,
        )
        .select_related(
            "booking__booked_by"
        )
        .in_bulk()
    )


def _archived_kind(event, history):
    """
    Clasifica una notificación histórica.

    Una solicitud que ya fue confirmada o cancelada
    no debe presentarse como una nueva solicitud pendiente.
    """

    if history is not None:

        if history.action == BookingHistory.Action.CANCELLED:
            return "cancelled"

        if history.action == BookingHistory.Action.CREATED:

            if history.booking.status == Booking.Status.PENDING:
                return "request"

            return "request_archived"

    # Respaldo para eventos cuyo historial original
    # ya no se encuentra disponible.
    #
    # El título fue generado por el servidor en V132.09C.

    title = event.title.casefold()

    if "cancel" in title:
        return "cancelled"

    return "request_archived"


def _archived_professional_booking_card(event, history):
    """
    Convierte NotificationEvent en una tarjeta compatible
    con el Centro Profesional.

    Mantiene el formato de datos utilizado por V128.
    """

    booking = (
        history.booking
        if history is not None
        else None
    )

    member = (
        booking.booked_by
        if booking is not None
        else None
    )

    return {
        "key": event.notification_key,

        "kind": _archived_kind(
            event,
            history,
        ),

        "title": event.title,

        "summary": event.summary,

        # No se incorporan motivos libres al archivo.
        "reason": "",

        "booking": booking,

        "member": member,

        "created_at": event.occurred_at,

        "link_url": event.detail_url,

        "link_label": (
            "Ver reserva"
            if booking is not None
            else "Ver aviso"
        ),

        # Permite distinguir los avisos recuperados
        # desde el historial persistente.
        "archived": True,
    }


def merge_professional_notification_updates(
    user,
    current_updates,
    *,
    limit=30,
):
    """
    Combina novedades actuales con eventos persistentes.

    Reglas:

    1. Conserva las novedades existentes de V128.
    2. Incorpora reservas profesionales archivadas.
    3. Evita duplicados mediante notification_key.
    4. Prefiere las tarjetas actuales cuando existen.
    5. Ordena por fecha de creación.
    6. Mantiene un límite de 30 novedades.

    current_updates debe provenir de las fuentes
    autorizadas del servidor.

    La comprobación del Perfil Profesional verificado
    corresponde a get_professional_updates_for().
    """

    if (
        type(limit) is not int
        or not (1 <= limit <= MAX_PROFESSIONAL_UPDATES)
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
            scope=PROFESSIONAL_SCOPE,
            limit=ARCHIVE_QUERY_LIMIT,
        )

        if (
            event.category == BOOKING_CATEGORY
            and event.notification_key not in known_keys
        )
    ]

    histories = (
        _load_professional_booking_histories(
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
            _archived_professional_booking_card(
                event,
                history,
            )
        )

        known_keys.add(
            event.notification_key
        )

    updates.sort(
        key=lambda item: (
            item["created_at"],
            item["key"],
        ),
        reverse=True,
    )

    return updates[:limit]