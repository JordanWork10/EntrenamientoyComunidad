"""
V132.09F2: notificaciones persistentes para arriendos de espacios.

Solo registra cambios reales de SpaceBookingHistory, después de confirmar
la transacción. No modifica reservas, pagos ni decisiones administrativas.
"""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from apps.accounts.models import NotificationEvent
from apps.accounts.notification_event_service_v13209 import record_notification_event

from .models import SpaceBooking, SpaceBookingHistory


SUPPORTED_ACTIONS = frozenset({
    SpaceBookingHistory.Action.CREATED,
    SpaceBookingHistory.Action.CONFIRMED,
    SpaceBookingHistory.Action.CANCELLED,
    SpaceBookingHistory.Action.COMPLETED,
})


def _display_member(member):
    return (
        member.get_full_name().strip()
        or "Un miembro"
    )


def _notification_specs(history):
    """
    Construye las novedades autorizadas para los dos participantes.

    No atribuye al proveedor cancelaciones aprobadas por administración.
    Excluye las acciones que realizó el propio destinatario.
    """

    booking = history.booking
    member = booking.booked_by
    provider = booking.provider_profile.user

    if member.pk == provider.pk:
        return []

    member_name = _display_member(member)

    provider_name = (
        (booking.provider_name_snapshot or "").strip()
        or "El proveedor"
    )

    space_name = (
        (booking.space_name_snapshot or "").strip()
        or "el espacio"
    )

    member_url = reverse(
        "spaces:booking_detail",
        kwargs={"booking_id": booking.pk},
    )

    provider_url = reverse(
        "spaces:provider_booking_detail",
        kwargs={"booking_id": booking.pk},
    )

    key = f"space-{history.pk}"
    specs = []

    def add(recipient, scope, title, summary, url):
        specs.append({
            "recipient": recipient,
            "scope": scope,
            "notification_key": key,
            "category": NotificationEvent.Category.SPACE,
            "title": title[:180],
            "summary": summary[:600],
            "detail_url": url,
            "occurred_at": history.created_at,
        })

    if history.action == SpaceBookingHistory.Action.CREATED:

        if history.changed_by_id != provider.pk:

            add(
                provider,
                NotificationEvent.Scope.SPACE,
                f"{member_name} solicitó un arriendo",
                f"Nueva solicitud para {space_name}.",
                provider_url,
            )

    elif history.action == SpaceBookingHistory.Action.CONFIRMED:

        if history.changed_by_id != member.pk:

            add(
                member,
                NotificationEvent.Scope.MEMBER,
                f"{provider_name} confirmó tu arriendo",
                f"Tu reserva de {space_name} quedó confirmada.",
                member_url,
            )

    elif history.action == SpaceBookingHistory.Action.CANCELLED:

        previous_status = (
            history.previous_data or {}
        ).get("status")

        if history.changed_by_id != member.pk:

            if history.changed_by_id == provider.pk:

                if previous_status == SpaceBooking.Status.PENDING:

                    member_title = (
                        f"{provider_name} no pudo aceptar tu solicitud"
                    )

                    member_summary = (
                        f"El arriendo de {space_name} no se realizará "
                        "en el horario solicitado."
                    )

                else:

                    member_title = (
                        f"{provider_name} canceló tu arriendo"
                    )

                    member_summary = (
                        f"Tu reserva de {space_name} fue cancelada."
                    )

            else:
                # Una decisión administrativa no se atribuye
                # equivocadamente al proveedor.

                member_title = "Se canceló tu arriendo"

                member_summary = (
                    f"Tu reserva de {space_name} fue cancelada."
                )

            add(
                member,
                NotificationEvent.Scope.MEMBER,
                member_title,
                member_summary,
                member_url,
            )

        if history.changed_by_id != provider.pk:

            provider_title = (
                f"{member_name} canceló su arriendo"
                if history.changed_by_id == member.pk
                else "Se canceló un arriendo de tu espacio"
            )

            add(
                provider,
                NotificationEvent.Scope.SPACE,
                provider_title,
                f"La reserva de {space_name} fue cancelada.",
                provider_url,
            )

    elif history.action == SpaceBookingHistory.Action.COMPLETED:

        if history.changed_by_id != member.pk:

            add(
                member,
                NotificationEvent.Scope.MEMBER,
                f"{provider_name} completó tu arriendo",
                f"La reserva de {space_name} quedó completada.",
                member_url,
            )

    return specs


def persist_space_booking_history_notifications(history_id):
    """
    Recupera el historial confirmado y registra
    sus eventos de forma idempotente.
    """

    history = (
        SpaceBookingHistory.objects
        .select_related(
            "booking__booked_by",
            "booking__provider_profile__user",
        )
        .get(pk=history_id)
    )

    for payload in _notification_specs(history):

        record_notification_event(**payload)


@receiver(
    post_save,
    sender=SpaceBookingHistory,
    dispatch_uid="v13209f2_space_booking_history_notification",
)
def space_booking_history_notification(
    sender,
    instance,
    created,
    raw=False,
    **kwargs,
):

    if (
        raw
        or not created
        or instance.action not in SUPPORTED_ACTIONS
    ):
        return

    history_id = instance.pk

    transaction.on_commit(
        lambda: persist_space_booking_history_notifications(
            history_id
        )
    )