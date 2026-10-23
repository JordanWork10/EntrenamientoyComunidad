"""
V128 - Endpoints seguros para el estado de lectura
de novedades del Miembro.

Las novedades se obtienen desde los registros reales
del usuario autenticado.

Este módulo NO modifica reservas, pagos ni incidencias.
"""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import (
    csrf_protect,
    ensure_csrf_cookie,
)
from django.views.decorators.http import require_GET, require_POST

from .models import NotificationReadState
from .notification_read_service import (
    get_read_keys,
    mark_all_as_read,
    mark_as_read,
)
from .views import _account_updates_for


MEMBER_SCOPE = NotificationReadState.Scope.MEMBER


def _available_member_keys(user):
    """
    Obtiene las claves de las novedades que realmente
    pertenecen al Miembro autenticado.

    No acepta identificadores de usuario provenientes
    del navegador.
    """

    updates = _account_updates_for(user)

    return [
        update['key']
        for update in updates
    ]


def _member_read_payload(user, available_keys):
    """
    Construye la respuesta con el estado actual
    de las novedades del usuario en PostgreSQL.
    """

    read_keys = get_read_keys(
        user,
        MEMBER_SCOPE,
        available_keys,
    )

    all_keys = set(available_keys)

    return {
        'success': True,
        'scope': MEMBER_SCOPE,
        'total': len(all_keys),
        'read_count': len(read_keys),
        'unread_count': len(all_keys - read_keys),
        'read_keys': sorted(read_keys),
    }


def _error_response(message, status=400):
    """
    Respuesta JSON uniforme para errores.
    """

    return JsonResponse(
        {
            'success': False,
            'error': str(message),
        },
        status=status,
    )


@login_required(login_url='accounts:login')
@require_GET
@ensure_csrf_cookie
def member_notification_state(request):
    """
    GET /cuenta/novedades/estado/

    Consulta las novedades revisadas del usuario
    que tiene la sesión iniciada.

    Garantiza que el navegador reciba una cookie CSRF
    para las posteriores operaciones de escritura.

    No modifica el estado de las novedades.
    """

    available_keys = _available_member_keys(
        request.user
    )

    try:
        payload = _member_read_payload(
            request.user,
            available_keys,
        )

    except ValidationError as exc:
        return _error_response(
            exc,
            status=400,
        )

    return JsonResponse(payload)


@login_required(login_url='accounts:login')
@require_POST
@csrf_protect
def member_notification_mark_read(request):
    """
    POST /cuenta/novedades/revisar/

    Permite dos operaciones:

    1. Marcar una o varias novedades:
       {"keys": ["professional-3"]}

    2. Marcar todas las novedades autorizadas:
       {"all": true}

    Las claves autorizadas se calculan nuevamente
    en el servidor usando el usuario autenticado.

    Exige sesión autenticada y protección CSRF.
    """

    if request.content_type != 'application/json':
        return _error_response(
            'La solicitud debe utilizar JSON.',
            status=415,
        )

    try:
        raw_data = request.body.decode('utf-8')
        data = json.loads(raw_data)

    except (UnicodeDecodeError, ValueError):
        return _error_response(
            'El contenido JSON no es válido.',
            status=400,
        )

    if not isinstance(data, dict):
        return _error_response(
            'El contenido debe ser un objeto JSON.',
            status=400,
        )

    available_keys = _available_member_keys(
        request.user
    )

    try:

        if data.get('all') is True:

            if 'keys' in data:
                return _error_response(
                    'No puedes combinar all y keys.',
                    status=400,
                )

            mark_all_as_read(
                request.user,
                MEMBER_SCOPE,
                available_keys,
            )

        elif 'keys' in data:

            requested_keys = data['keys']

            if not isinstance(requested_keys, list):
                return _error_response(
                    'Las claves deben enviarse como una lista.',
                    status=400,
                )

            mark_as_read(
                request.user,
                MEMBER_SCOPE,
                requested_keys,
                available_keys,
            )

        else:

            return _error_response(
                'Debes indicar keys o all.',
                status=400,
            )

        payload = _member_read_payload(
            request.user,
            available_keys,
        )

        return JsonResponse(payload)

    except PermissionDenied:
        return _error_response(
            'No puedes revisar novedades de otro usuario.',
            status=403,
        )

    except ValidationError as exc:
        return _error_response(
            exc,
            status=400,
        )