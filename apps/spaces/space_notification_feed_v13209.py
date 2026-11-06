"""V132.09F3: tarjetas autorizadas para el Centro de Espacios.

Solo lee notificaciones y su estado de lectura.
No altera reservas ni pagos.
"""

import re

from apps.accounts.models import NotificationEvent, NotificationReadState
from apps.accounts.notification_event_service_v13209 import (
    list_notification_events,
)
from apps.accounts.notification_read_service import get_read_keys

from .models import SpaceBookingHistory


SPACE_SCOPE = NotificationEvent.Scope.SPACE
SPACE_CATEGORY = NotificationEvent.Category.SPACE
MAX_EVENTS = 100

SPACE_KEY_RE = re.compile(
    r"space-([1-9][0-9]*)\Z"
)


def _history_id(key):

    if not isinstance(key, str):
        return None

    match = SPACE_KEY_RE.fullmatch(key)

    return int(match.group(1)) if match else None


def get_space_provider_notification_feed(user):
    """
    Devuelve exclusivamente eventos cuyo historial
    pertenece al proveedor autenticado.
    """

    events = [
        event
        for event in list_notification_events(
            recipient=user,
            scope=SPACE_SCOPE,
            limit=MAX_EVENTS,
        )
        if (
            event.category == SPACE_CATEGORY
            and _history_id(event.notification_key)
        )
    ]

    history_ids = {
        _history_id(event.notification_key)
        for event in events
    }

    histories = (
        SpaceBookingHistory.objects
        .filter(
            pk__in=history_ids,
            booking__provider_profile__user_id=user.pk,
        )
        .select_related("booking")
        .in_bulk()
        if history_ids
        else {}
    )

    authorized_events = [
        (
            event,
            histories[_history_id(event.notification_key)],
        )
        for event in events
        if _history_id(event.notification_key) in histories
    ]

    available_keys = {
        event.notification_key
        for event, _ in authorized_events
    }

    read_keys = get_read_keys(
        user,
        NotificationReadState.Scope.SPACE,
        available_keys,
    )

    unread = []
    reviewed = []

    labels = {
        SpaceBookingHistory.Action.CREATED: (
            "Nueva solicitud",
            "requested",
        ),
        SpaceBookingHistory.Action.CONFIRMED: (
            "Confirmada",
            "confirmed",
        ),
        SpaceBookingHistory.Action.CANCELLED: (
            "Cancelada",
            "cancelled",
        ),
        SpaceBookingHistory.Action.COMPLETED: (
            "Completada",
            "completed",
        ),
    }

    for event, history in authorized_events:

        booking = history.booking

        status_label, kind = labels.get(
            history.action,
            ("Actualizada", "updated"),
        )

        item = {
            "key": event.notification_key,
            "title": event.title,
            "summary": event.summary,
            "detail_url": event.detail_url,
            "occurred_at": event.occurred_at,
            "session_date": booking.session_date,
            "start_time": booking.start_time,
            "end_time": booking.end_time,
            "space_name": booking.space_name_snapshot,
            "kind": kind,
            "status_label": status_label,
        }

        if event.notification_key in read_keys:
            reviewed.append(item)
        else:
            unread.append(item)

    return {
        "space_notification_unread_preview": unread[:6],
        "space_notification_unread_extra": unread[6:],
        "space_notification_reviewed": reviewed,
        "space_notification_unread_count": len(unread),
        "space_notification_reviewed_count": len(reviewed),
        "space_notification_has_events": bool(
            unread or reviewed
        ),
        "space_notification_available_keys": available_keys,
    }