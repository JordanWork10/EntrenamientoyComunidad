"""V132.09C1: archiva cambios de reservas profesionales tras el commit.

No modifica Booking, BookingHistory, pagos ni el sistema de novedades V128.
BookingHistory sigue siendo la fuente durable para futuros reintentos.
"""

import logging

from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from apps.accounts.notification_event_service_v13209 import (
    record_notification_event,
)

from .models import Booking, BookingHistory


logger = logging.getLogger(__name__)

TRACKED_ACTIONS = frozenset({
    BookingHistory.Action.CREATED,
    BookingHistory.Action.CONFIRMED,
    BookingHistory.Action.CANCELLED,
})


def _name(user):
    """Nombre acotado para no superar la longitud del titulo."""

    return (
        user.get_full_name()
        or user.email
        or "Usuario"
    ).strip()[:90]


def build_booking_notification_payload(history):
    """Traduce un evento auditado a una notificacion privada o None.

    La clave coincide con las novedades V128:
    la lectura previa se conserva.

    No guarda motivos libres de cancelacion ni datos clinicos.
    """

    booking = history.booking

    member = booking.booked_by

    professional = booking.professional_profile.user

    actor_id = history.changed_by_id

    if member.pk == professional.pk or actor_id is None:
        return None

    service_name = booking.service_name_snapshot

    previous_status = (
        history.previous_data or {}
    ).get("status")

    action = history.action

    # =====================================================
    # NUEVA SOLICITUD DEL MIEMBRO
    # =====================================================

    if (
        action == BookingHistory.Action.CREATED
        and actor_id == member.pk
    ):

        recipient = professional

        scope = "professional"

        key = f"booking-history-{history.pk}"

        title = (
            f"{_name(member)} envio una solicitud"
        )

        summary = (
            f"Se registro una solicitud para {service_name}."
        )

        detail_url = reverse(
            "bookings:professional_detail",
            kwargs={
                "booking_id": booking.pk,
            },
        )

    # =====================================================
    # CONFIRMACION DEL PROFESIONAL
    # =====================================================

    elif (
        action == BookingHistory.Action.CONFIRMED
        and actor_id == professional.pk
    ):

        recipient = member

        scope = "member"

        key = f"professional-{history.pk}"

        title = (
            f"{_name(professional)} confirmo tu sesion"
        )

        summary = (
            f"La reserva para {service_name} fue confirmada."
        )

        detail_url = reverse(
            "bookings:detail",
            kwargs={
                "booking_id": booking.pk,
            },
        )

    # =====================================================
    # CANCELACION REALIZADA POR EL MIEMBRO
    # =====================================================

    elif (
        action == BookingHistory.Action.CANCELLED
        and actor_id == member.pk
    ):

        recipient = professional

        scope = "professional"

        key = f"booking-history-{history.pk}"

        if previous_status == Booking.Status.PENDING:

            title = (
                f"{_name(member)} cancelo su solicitud"
            )

            summary = (
                f"La solicitud para {service_name} fue cancelada."
            )

        else:

            title = (
                f"{_name(member)} cancelo su reserva"
            )

            summary = (
                f"La reserva para {service_name} fue cancelada."
            )

        detail_url = reverse(
            "bookings:professional_detail",
            kwargs={
                "booking_id": booking.pk,
            },
        )

    # =====================================================
    # CANCELACION O RECHAZO DEL PROFESIONAL
    # =====================================================

    elif (
        action == BookingHistory.Action.CANCELLED
        and actor_id == professional.pk
    ):

        recipient = member

        scope = "member"

        key = f"professional-{history.pk}"

        if previous_status == Booking.Status.PENDING:

            title = (
                f"{_name(professional)} no pudo aceptar tu solicitud"
            )

            summary = (
                f"La solicitud para {service_name} fue rechazada."
            )

        else:

            title = (
                f"{_name(professional)} cancelo tu sesion"
            )

            summary = (
                f"La reserva para {service_name} fue cancelada."
            )

        detail_url = reverse(
            "bookings:detail",
            kwargs={
                "booking_id": booking.pk,
            },
        )

    else:
        return None

    return {
        "recipient": recipient,
        "scope": scope,
        "notification_key": key,
        "category": "booking",
        "title": title,
        "summary": summary,
        "detail_url": detail_url,
        "occurred_at": history.created_at,
    }


def _load_history(history_id):
    """Carga el acontecimiento original desde PostgreSQL."""

    return (
        BookingHistory.objects.select_related(
            "booking__booked_by",
            "booking__professional_profile__user",
        ).get(
            pk=history_id,
        )
    )


def _persist_history_notification(history_id):
    """Registra la notificacion despues del commit.

    Los fallos se registran para permitir un futuro reproceso
    desde BookingHistory.

    No deben alterar el resultado de una reserva confirmada.
    """

    try:

        history = _load_history(history_id)

        payload = build_booking_notification_payload(
            history
        )

        if payload is not None:

            record_notification_event(
                **payload
            )

    except Exception:

        logger.exception(
            "No se pudo archivar la notificacion "
            "de BookingHistory ID=%s",
            history_id,
        )


@receiver(
    post_save,
    sender=BookingHistory,
    dispatch_uid="v13209c1_booking_history_notification",
)
def on_booking_history_created(
    sender,
    instance,
    created,
    raw=False,
    using=None,
    **kwargs,
):
    """Programa el registro al crear un historial."""

    if (
        not created
        or raw
        or instance.action not in TRACKED_ACTIONS
    ):
        return

    # El servicio utiliza la base de datos principal.
    if using not in (
        None,
        DEFAULT_DB_ALIAS,
    ):
        return

    history_id = instance.pk

    transaction.on_commit(
        lambda history_id=history_id: (
            _persist_history_notification(history_id)
        ),
        using=using or DEFAULT_DB_ALIAS,
    )
    