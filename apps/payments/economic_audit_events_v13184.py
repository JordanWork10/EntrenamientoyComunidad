"""V131.84 — línea de tiempo económica para el administrador (solo GET).

Copiar como: apps/payments/economic_audit_events_v13184.py
"""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .admin_economic_audit_v13183 import _require_economic_audit_permission
from .economic_audit_models_v13184 import EconomicAuditEvent


@login_required(login_url='accounts:login')
@require_GET
def economic_audit_events(request):
    """Registro histórico, paginado, sin mutaciones ni reconstrucciones."""
    _require_economic_audit_permission(request.user)

    source = request.GET.get('origen', 'todos')
    allowed_sources = ('todos', *EconomicAuditEvent.Source.values)
    if source not in allowed_sources:
        source = 'todos'

    action = request.GET.get('accion', 'todas')
    allowed_actions = ('todas', *EconomicAuditEvent.Action.values)
    if action not in allowed_actions:
        action = 'todas'

    term = request.GET.get('id', '').strip()[:50]
    invalid_id = False
    source_id = None
    if term:
        try:
            source_id = UUID(term)
        except (ValueError, AttributeError):
            invalid_id = True

    queryset = EconomicAuditEvent.objects.all()
    if source != 'todos':
        queryset = queryset.filter(source_type=source)
    if action != 'todas':
        queryset = queryset.filter(action=action)
    if source_id:
        queryset = queryset.filter(source_public_id=source_id)
    elif invalid_id:
        queryset = queryset.none()

    page_obj = Paginator(queryset.order_by('-occurred_at', '-pk'), 25).get_page(
        request.GET.get('pagina')
    )

    params = request.GET.copy()
    params.pop('pagina', None)

    return render(request, 'payments/economic_audit_events_v13184.html', {
        'page_obj': page_obj,
        'selected_source': source,
        'selected_action': action,
        'term': term,
        'invalid_id': invalid_id,
        'page_query': params.urlencode(),
    })
