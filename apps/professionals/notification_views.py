"""
V128 - Endpoints seguros para las novedades del Centro Profesional.

Mantiene la lista de claves permitidas en el servidor, según el usuario
con sesión iniciada y su Perfil Profesional verificado.
No modifica reservas, actividades, pagos ni incidencias.
"""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import NotificationReadState
from apps.accounts.notification_read_service import (
    get_read_keys,
    mark_all_as_read,
    mark_as_read,
)

from .notification_feed import get_professional_updates_for


PROFESSIONAL_SCOPE = NotificationReadState.Scope.PROFESSIONAL
MAX_JSON_BYTES = 32768


def _available_keys(user):
    # La lista proviene del mismo servicio que utiliza el dashboard.
    return [update['key'] for update in get_professional_updates_for(user)]


def _read_payload(user, available_keys):
    read_keys = get_read_keys(user, PROFESSIONAL_SCOPE, available_keys)
    available = set(available_keys)
    return {
        'success': True,
        'scope': PROFESSIONAL_SCOPE,
        'total': len(available),
        'read_count': len(read_keys),
        'unread_count': len(available - read_keys),
        'read_keys': sorted(read_keys),
    }


def _error(message, status=400):
    return JsonResponse({'success': False, 'error': str(message)}, status=status)


@login_required(login_url='accounts:login')
@require_GET
@ensure_csrf_cookie
def professional_notification_state(request):
    """Devuelve el estado leído del Profesional con sesión iniciada."""
    try:
        available_keys = _available_keys(request.user)
        return JsonResponse(_read_payload(request.user, available_keys))
    except PermissionDenied:
        return _error('No tienes un Perfil Profesional verificado.', status=403)
    except ValidationError as exc:
        return _error(exc.messages, status=400)


@login_required(login_url='accounts:login')
@require_POST
@csrf_protect
def professional_notification_mark_read(request):
    """Marca una o todas las novedades autorizadas del Profesional."""
    if request.content_type != 'application/json':
        return _error('Se requiere application/json.', status=415)

    if len(request.body) > MAX_JSON_BYTES:
        return _error('La solicitud es demasiado grande.', status=413)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return _error('El contenido JSON no es válido.')

    if not isinstance(data, dict):
        return _error('Se requiere un objeto JSON.')

    try:
        available_keys = _available_keys(request.user)

        if data.get('all') is True and 'keys' not in data:
            mark_all_as_read(request.user, PROFESSIONAL_SCOPE, available_keys)
        elif 'keys' in data and 'all' not in data:
            keys = data['keys']
            if not isinstance(keys, list):
                return _error('Las claves deben enviarse como una lista.')
            mark_as_read(request.user, PROFESSIONAL_SCOPE, keys, available_keys)
        else:
            return _error('Indica keys o all, sin combinarlos.')

        return JsonResponse(_read_payload(request.user, available_keys))

    except PermissionDenied:
        return _error('No puedes revisar estas novedades.', status=403)
    except ValidationError as exc:
        return _error(exc.messages, status=400)
