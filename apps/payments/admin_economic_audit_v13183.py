"""V131.83 — Auditoría económica administrativa de solo lectura.

Copiar como: apps/payments/admin_economic_audit_v13183.py

Consulta registros persistidos de pagos, reembolsos y liquidaciones de los tres
orígenes. No recalcula snapshots, no crea movimientos y no ejecuta cierres.
"""

from datetime import date
from uuid import UUID

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Payment, Refund, Settlement


AUDIT_TYPES = ('pagos', 'reembolsos', 'liquidaciones')
AUDIT_ORIGINS = ('todos', 'actividades', 'sesiones', 'espacios')
ECONOMIC_PAYMENT_STATUSES = (
    Payment.Status.APPROVED,
    Payment.Status.PARTIALLY_REFUNDED,
    Payment.Status.REFUNDED,
)


def _require_economic_audit_permission(user):
    """Tres permisos de lectura, independientemente del acceso a cierres."""
    if not (
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and all(user.has_perm(permission) for permission in (
            'payments.view_payment',
            'payments.view_refund',
            'payments.view_settlement',
        ))
    ):
        raise PermissionDenied('No tienes permiso para consultar la auditoría económica.')


def _parse_date(value):
    """Fecha ISO explícita; una fecha inválida no amplía el intervalo."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _filter_origin(queryset, kind, origin):
    if origin == 'todos':
        return queryset

    if kind == 'liquidaciones':
        scope = {
            'actividades': Settlement.ScopeType.ACTIVITY,
            'sesiones': Settlement.ScopeType.PROFESSIONAL_DAY,
            'espacios': Settlement.ScopeType.SPACE_DAY,
        }[origin]
        return queryset.filter(scope_type=scope)

    prefix = 'payment__' if kind == 'reembolsos' else ''
    relation = {
        'actividades': 'activity',
        'sesiones': 'professional_booking',
        'espacios': 'space_booking',
    }[origin]
    return queryset.filter(**{f'{prefix}{relation}__isnull': False})


def _filter_identifier(queryset, kind, term):
    """UUID exacto, o coincidencia parcial de referencia de pasarela."""
    if not term:
        return queryset
    try:
        public_id = UUID(term)
    except (ValueError, AttributeError):
        if kind == 'reembolsos':
            return queryset.filter(
                Q(provider_reference__icontains=term)
                | Q(payment__provider_reference__icontains=term)
            )
        return queryset.filter(provider_reference__icontains=term)

    if kind == 'reembolsos':
        return queryset.filter(
            Q(public_id=public_id) | Q(payment__public_id=public_id)
        )
    if kind == 'liquidaciones':
        # Puede encontrarse la jornada desde el UUID de un pago vinculado.
        return queryset.filter(
            Q(public_id=public_id) | Q(payments__public_id=public_id)
        ).distinct()
    return queryset.filter(public_id=public_id)


def build_audit_queryset(kind, origin='todos', status='', term='', start=None, end=None):
    """Conserva todos los estados, incluidos intentos fallidos y devoluciones."""
    if kind == 'reembolsos':
        queryset = Refund.objects.select_related(
            'payment', 'payment__payer', 'payment__activity',
            'payment__space_booking', 'payment__professional_booking',
            'requested_by',
        )
        choices = dict(Refund.Status.choices)
        date_field = 'requested_at'
    elif kind == 'liquidaciones':
        queryset = Settlement.objects.select_related(
            'beneficiary', 'settled_by', 'activity', 'space',
        )
        choices = dict(Settlement.Status.choices)
        date_field = 'created_at'
    else:
        queryset = Payment.objects.select_related(
            'payer', 'activity', 'space_booking', 'professional_booking',
        )
        choices = dict(Payment.Status.choices)
        date_field = 'created_at'

    queryset = _filter_origin(queryset, kind, origin)
    if status in choices:
        queryset = queryset.filter(status=status)
    queryset = _filter_identifier(queryset, kind, term)
    if start:
        queryset = queryset.filter(**{f'{date_field}__date__gte': start})
    if end:
        queryset = queryset.filter(**{f'{date_field}__date__lte': end})
    return queryset.order_by(f'-{date_field}', '-pk')


@login_required(login_url='accounts:login')
@require_GET
def admin_economic_audit(request):
    """Auditoría transversal: GET, autorizada, filtrada y paginada."""
    _require_economic_audit_permission(request.user)

    kind = request.GET.get('tipo', 'pagos')
    if kind not in AUDIT_TYPES:
        kind = 'pagos'
    origin = request.GET.get('origen', 'todos')
    if origin not in AUDIT_ORIGINS:
        origin = 'todos'

    choices = {
        'pagos': Payment.Status.choices,
        'reembolsos': Refund.Status.choices,
        'liquidaciones': Settlement.Status.choices,
    }[kind]
    status = request.GET.get('estado', '')
    if status not in dict(choices):
        status = ''

    term = request.GET.get('buscar', '').strip()[:120]
    raw_start = request.GET.get('desde', '').strip()
    raw_end = request.GET.get('hasta', '').strip()
    start = _parse_date(raw_start)
    end = _parse_date(raw_end)
    invalid_dates = bool((raw_start and not start) or (raw_end and not end))

    # Un intervalo inválido no puede convertirse en una búsqueda más amplia.
    if invalid_dates or (start and end and start > end):
        queryset = build_audit_queryset(kind).none()
        invalid_dates = True
    else:
        queryset = build_audit_queryset(kind, origin, status, term, start, end)

    page_obj = Paginator(queryset, 20).get_page(request.GET.get('pagina'))

    approved_amounts = Payment.objects.filter(
        status__in=ECONOMIC_PAYMENT_STATUSES,
    ).aggregate(
        gross=Sum('amount_clp'),
        refunded=Sum('refunded_amount_clp'),
        net=Sum('net_amount_clp'),
    )
    params = request.GET.copy()
    params.pop('pagina', None)

    return render(request, 'payments/admin_economic_audit.html', {
        'kind': kind,
        'origin': origin,
        'selected_status': status,
        'status_choices': choices,
        'term': term,
        'start_input': raw_start,
        'end_input': raw_end,
        'invalid_dates': invalid_dates,
        'page_obj': page_obj,
        'page_query': params.urlencode(),
        'payment_count': Payment.objects.count(),
        'refund_count': Refund.objects.count(),
        'settlement_count': Settlement.objects.count(),
        'gross_total': approved_amounts['gross'] or 0,
        'refunded_total': approved_amounts['refunded'] or 0,
        'net_total': approved_amounts['net'] or 0,
        'sandbox_enabled': bool(getattr(settings, 'PAYMENTS_SANDBOX', False)),
    })
