"""V131.81: resumen económico de jornadas de espacios (solo lectura).

Copiar como: apps/payments/space_day_admin_v13181.py

Los POST de preparación y cierre continúan en views.py, con sus mismas
validaciones y permisos. Este módulo NO modifica pagos ni liquidaciones.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from . import views
from .models import Payment, Settlement


_ECONOMIC_STATUSES = (
    Payment.Status.APPROVED,
    Payment.Status.PARTIALLY_REFUNDED,
    Payment.Status.REFUNDED,
)


def build_space_day_rows(payments, settlements):
    """Agrupa snapshots por recinto y fecha, sin consultar ni escribir BD."""
    grouped = {}
    booking_ids_by_key = {}

    def ensure_group(space, reference_date):
        key = (space.pk, reference_date)
        if key not in grouped:
            grouped[key] = {
                'space': space,
                'date': reference_date,
                'payment_count': 0,
                'booking_count': 0,
                'gross_total': 0,
                'refunded_total': 0,
                'commission_total': 0,
                'net_total': 0,
                'settlement': None,
                'incomplete': False,
                'cancelled_with_balance': False,
                'other_unfinished': False,
            }
        return key, grouped[key]

    for payment in payments:
        if payment.status not in _ECONOMIC_STATUSES:
            continue
        booking = payment.space_booking
        key, group = ensure_group(booking.space, booking.session_date)
        group['payment_count'] += 1
        group['gross_total'] += payment.amount_clp
        group['refunded_total'] += payment.refunded_amount_clp
        group['commission_total'] += payment.commission_amount_clp
        group['net_total'] += payment.net_amount_clp
        booking_ids_by_key.setdefault(key, set()).add(booking.pk)

        if payment.net_amount_clp > 0:
            if booking.status == 'confirmed':
                group['incomplete'] = True
            elif booking.status == 'cancelled':
                group['cancelled_with_balance'] = True
            elif booking.status != 'completed':
                group['other_unfinished'] = True

    for settlement in settlements:
        _, group = ensure_group(settlement.space, settlement.reference_date)
        group['settlement'] = settlement

    for key, group in grouped.items():
        group['booking_count'] = len(booking_ids_by_key.get(key, set()))
        settlement = group['settlement']
        group['no_balance'] = group['net_total'] == 0

        if group['no_balance']:
            group['operational_label'] = 'Sin saldo por liquidar'
        elif group['incomplete']:
            group['operational_label'] = 'Arriendo por completar'
        elif group['cancelled_with_balance']:
            group['operational_label'] = 'Cancelación con saldo retenido'
        elif group['other_unfinished']:
            group['operational_label'] = 'Estado por verificar'
        else:
            group['operational_label'] = 'Sin arriendos por completar'

        group['outdated_snapshot'] = bool(
            settlement
            and (
                settlement.gross_amount_clp != group['gross_total']
                or settlement.refunded_amount_clp != group['refunded_total']
                or settlement.commission_amount_clp != group['commission_total']
                or settlement.net_amount_clp != group['net_total']
            )
        )
        group['can_prepare'] = bool(group['payment_count']) and (
            settlement is None or settlement.status != Settlement.Status.SETTLED
        )
        group['can_settle'] = bool(
            settlement
            and settlement.status == Settlement.Status.ELIGIBLE
            and group['net_total'] > 0
            and not group['outdated_snapshot']
            and not group['incomplete']
            and not group['other_unfinished']
        )

    return sorted(
        grouped.values(),
        key=lambda group: (group['date'], group['space'].pk),
        reverse=True,
    )


@login_required(login_url='accounts:login')
@require_GET
def space_settlement_admin(request):
    """La protección original se reutiliza antes de consultar cualquier dato."""
    views._require_space_settlement_operator(request)

    payments = (
        Payment.objects.filter(
            economic_scope=Payment.EconomicScope.SPACE_BOOKING,
            activity__isnull=True,
            professional_booking__isnull=True,
            space_booking__isnull=False,
            status__in=_ECONOMIC_STATUSES,
        )
        .select_related('space_booking', 'space_booking__space')
        .order_by('space_booking__session_date', 'pk')
    )
    settlements = (
        Settlement.objects.filter(scope_type=Settlement.ScopeType.SPACE_DAY)
        .select_related('space', 'beneficiary')
        .order_by('-reference_date', '-pk')
    )

    return render(request, 'payments/space_settlement_admin.html', {
        'rows': build_space_day_rows(payments, settlements),
        'now': timezone.localtime(),
        'sandbox_enabled': True,
    })
