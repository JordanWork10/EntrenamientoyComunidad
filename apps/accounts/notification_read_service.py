"""
V128 - Servicio para conservar novedades revisadas en PostgreSQL.

No genera notificaciones nuevas ni modifica reservas, espacios o incidencias.
La vista que lo utilice debe obtener las novedades autorizadas desde
las fuentes reales antes de permitir marcarlas como revisadas.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import NotificationReadState


MAX_KEYS_PER_OPERATION = 250

VALID_SCOPES = frozenset(
    (
        NotificationReadState.Scope.MEMBER,
        NotificationReadState.Scope.PROFESSIONAL,
    )
)


def _validate_user_and_scope(user, scope):
    """
    Requiere una cuenta autenticada y un panel reconocido.
    """

    if user is None or not getattr(user, 'is_authenticated', False):
        raise PermissionDenied(
            'Debes iniciar sesión para consultar novedades.'
        )

    if not isinstance(scope, str) or scope not in VALID_SCOPES:
        raise ValidationError(
            'El panel de novedades no es válido.'
        )


def _normalize_keys(keys):
    """
    Normaliza y valida una colección de claves sin modificarlas.
    """

    if keys is None:
        return set()

    if isinstance(keys, (str, bytes, dict)):
        raise ValidationError(
            'Las claves deben enviarse como una lista.'
        )

    try:
        items = list(keys)
    except TypeError as exc:
        raise ValidationError(
            'Las claves deben enviarse como una lista.'
        ) from exc

    if len(items) > MAX_KEYS_PER_OPERATION:
        raise ValidationError(
            'Se enviaron demasiadas novedades juntas.'
        )

    normalized = set()

    for key in items:
        if (
            not isinstance(key, str)
            or not key
            or len(key) > 255
            or key != key.strip()
        ):
            raise ValidationError(
                'Se recibió una clave de novedad no válida.'
            )

        normalized.add(key)

    return normalized


def get_read_keys(user, scope, available_keys=None):
    """
    Devuelve las claves revisadas del usuario en el panel solicitado.

    Si available_keys se proporciona, solo devuelve aquellas que
    forman parte de las novedades actualmente visibles/autorizadas.
    """

    _validate_user_and_scope(user, scope)

    queryset = NotificationReadState.objects.filter(
        user=user,
        scope=scope,
    )

    if available_keys is not None:
        authorized = _normalize_keys(available_keys)

        if not authorized:
            return set()

        queryset = queryset.filter(
            notification_key__in=authorized
        )

    return set(
        queryset.values_list(
            'notification_key',
            flat=True,
        )
    )


def mark_as_read(user, scope, requested_keys, available_keys):
    """
    Registra como revisadas solo novedades que pertenecen al usuario.

    IMPORTANTE:
    available_keys debe provenir de las novedades reales construidas
    en el servidor para el usuario y el panel correspondientes.

    Nunca debe aceptarse available_keys directamente del navegador.

    La operación es idempotente: repetirla no crea duplicados,
    gracias a la restricción única definida en PostgreSQL.
    """

    _validate_user_and_scope(user, scope)

    requested = _normalize_keys(requested_keys)
    authorized = _normalize_keys(available_keys)

    if not requested.issubset(authorized):
        raise PermissionDenied(
            'No puedes marcar novedades que no te pertenecen.'
        )

    if not requested:
        return set()

    with transaction.atomic():
        NotificationReadState.objects.bulk_create(
            [
                NotificationReadState(
                    user=user,
                    scope=scope,
                    notification_key=key,
                )
                for key in sorted(requested)
            ],
            ignore_conflicts=True,
        )

    return get_read_keys(
        user,
        scope,
        requested,
    )


def mark_all_as_read(user, scope, available_keys):
    """
    Marca todas las novedades autorizadas del panel indicado.
    """

    authorized = _normalize_keys(available_keys)

    return mark_as_read(
        user,
        scope,
        authorized,
        authorized,
    )