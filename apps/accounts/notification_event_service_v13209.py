"""V132.09B: registro idempotente y consulta aislada de notificaciones.

No conecta eventos de negocio ni modifica reservas, pagos o incidencias.
Solo debe llamarse desde codigo de servidor con un destinatario autorizado.
"""

from datetime import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import NotificationEvent


MAX_EVENTS_PER_QUERY = 100


def _validate_recipient(recipient):
    if (
        recipient is None
        or not getattr(recipient, "is_authenticated", False)
        or getattr(recipient, "pk", None) is None
    ):
        raise PermissionDenied(
            "Se requiere un destinatario autenticado y guardado."
        )


def _validate_scope(scope):
    if (
        not isinstance(scope, str)
        or scope not in NotificationEvent.Scope.values
    ):
        raise ValidationError(
            "El panel de notificaciones no es valido."
        )


def record_notification_event(
    *,
    recipient,
    scope,
    notification_key,
    category,
    title,
    summary="",
    detail_url="",
    occurred_at=None,
):
    """Registra un evento una sola vez por usuario, panel y clave.

    Devuelve (evento, creado).

    Una llamada repetida conserva el primer contenido, incluso
    si se recibe otro titulo o resumen para la misma clave.

    No utilizar directamente con datos del navegador.
    """

    _validate_recipient(recipient)
    _validate_scope(scope)

    if (
        not isinstance(category, str)
        or category not in NotificationEvent.Category.values
    ):
        raise ValidationError(
            "Categoria de notificacion no valida."
        )

    if not isinstance(title, str) or not title.strip():
        raise ValidationError(
            "La notificacion requiere un titulo."
        )

    if (
        not isinstance(summary, str)
        or not isinstance(detail_url, str)
    ):
        raise ValidationError(
            "El resumen y el enlace deben ser texto."
        )

    if occurred_at is not None and (
        not isinstance(occurred_at, datetime)
        or timezone.is_naive(occurred_at)
    ):
        raise ValidationError(
            "La fecha del evento debe incluir zona horaria."
        )

    candidate = NotificationEvent(
        recipient=recipient,
        scope=scope,
        notification_key=notification_key,
        category=category,
        title=title,
        summary=summary,
        detail_url=detail_url,
    )

    if occurred_at is not None:
        candidate.occurred_at = occurred_at

    # Validar el formato sin rechazar claves ya existentes.
    # La deduplicacion se realiza en PostgreSQL.
    candidate.full_clean(
        validate_unique=False,
        validate_constraints=False,
    )

    with transaction.atomic():

        event, created = NotificationEvent.objects.get_or_create(
            recipient=recipient,
            scope=scope,
            notification_key=notification_key,
            defaults={
                "category": candidate.category,
                "title": candidate.title,
                "summary": candidate.summary,
                "detail_url": candidate.detail_url,
                "occurred_at": candidate.occurred_at,
            },
        )

    return event, created


def list_notification_events(
    *,
    recipient,
    scope,
    limit=30,
):
    """Devuelve hasta 100 eventos del destinatario y panel indicados."""

    _validate_recipient(recipient)
    _validate_scope(scope)

    if (
        type(limit) is not int
        or not (1 <= limit <= MAX_EVENTS_PER_QUERY)
    ):
        raise ValidationError(
            "El limite debe estar entre 1 y 100."
        )

    return list(
        NotificationEvent.objects.filter(
            recipient=recipient,
            scope=scope,
        ).order_by(
            "-occurred_at",
            "-pk",
        )[:limit]
    )