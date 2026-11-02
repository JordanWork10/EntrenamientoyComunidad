"""V131.78: panel administrativo de jornadas de sesiones (sandbox)."""

from datetime import date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from .models import Payment, Settlement
from .services.professional_day_settlements import (
    SettlementProcessingError,
    release_professional_day_hold,
    settle_professional_day_settlement,
    sync_professional_day_settlement,
)


def _require_operator(request):
    user = request.user
    if not (
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perm('payments.change_settlement')
    ):
        raise PermissionDenied('No tienes permiso para administrar liquidaciones.')
    if not getattr(settings, 'PAYMENTS_SANDBOX', False):
        raise Http404('Estas liquidaciones solo están disponibles en sandbox.')


@login_required(login_url='accounts:login')
@require_GET
def professional_day_settlement_admin(request):
    """Solo lectura: listar pagos y jornadas sin crear liquidaciones."""
    _require_operator(request)
    payments = (
        Payment.objects.filter(
            economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
            professional_booking__isnull=False,
            activity__isnull=True,
            space_booking__isnull=True,
            status__in=(
                Payment.Status.APPROVED,
                Payment.Status.PARTIALLY_REFUNDED,
                Payment.Status.REFUNDED,
            ),
        )
        .select_related(
            'professional_booking',
            'professional_booking__professional_profile__user',
        )
        .order_by('professional_booking__session_date', 'pk')
    )

    groups = {}

    def ensure_group(professional, reference_date):
        key = (professional.pk, reference_date)
        if key not in groups:
            groups[key] = {
                'professional': professional,
                'date': reference_date,
                'payment_count': 0,
                'gross_total': 0,
                'refunded_total': 0,
                'commission_total': 0,
                'net_total': 0,
                'awaiting_completion': False,
                'settlement': None,
            }
        return groups[key]

    for payment in payments:
        booking = payment.professional_booking
        professional = booking.professional_profile.user
        row = ensure_group(professional, booking.session_date)
        row['payment_count'] += 1
        row['gross_total'] += payment.amount_clp
        row['refunded_total'] += payment.refunded_amount_clp
        row['commission_total'] += payment.commission_amount_clp
        row['net_total'] += payment.net_amount_clp
        if payment.net_amount_clp > 0 and booking.status == 'confirmed':
            row['awaiting_completion'] = True

    settlements = Settlement.objects.filter(
        scope_type=Settlement.ScopeType.PROFESSIONAL_DAY,
        reference_date__isnull=False,
    ).select_related('beneficiary', 'settled_by')
    for settlement in settlements:
        row = ensure_group(settlement.beneficiary, settlement.reference_date)
        row['settlement'] = settlement

    for row in groups.values():
        settlement = row['settlement']
        row['can_prepare'] = bool(row['payment_count']) and (
            settlement is None or settlement.status != Settlement.Status.SETTLED
        )
        row['can_settle'] = bool(
            settlement and settlement.status == Settlement.Status.ELIGIBLE
        )
        row['can_release'] = bool(
            settlement and settlement.status == Settlement.Status.ON_HOLD
        )

    rows = sorted(
        groups.values(),
        key=lambda row: (row['date'], row['professional'].pk),
        reverse=True,
    )
    return render(request, 'payments/professional_day_settlement_admin.html', {
        'rows': rows,
        'now': timezone.localtime(),
    })


@login_required(login_url='accounts:login')
@require_POST
@csrf_protect
def professional_day_settlement_prepare(request, professional_id, year, month, day):
    """Revisa la jornada; no autoriza la liquidación."""
    _require_operator(request)
    try:
        reference_date = date(year, month, day)
    except ValueError as exc:
        raise Http404('Fecha inválida.') from exc
    professional = get_object_or_404(get_user_model(), pk=professional_id)
    try:
        settlement = sync_professional_day_settlement(
            professional, reference_date,
        )
    except (SettlementProcessingError, ValidationError) as exc:
        messages.error(request, f'No fue posible preparar la jornada: {exc}')
    else:
        messages.success(request, (
            f'Jornada #{settlement.pk} revisada: '
            f'{settlement.get_status_display()}. No se transfirió dinero.'
        ))
    return redirect('payments:professional_day_settlement_admin')


@login_required(login_url='accounts:login')
@require_POST
@csrf_protect
def professional_day_settlement_close(request, settlement_id):
    """Cierre expreso, solo después de la revalidación dentro del servicio."""
    _require_operator(request)
    if request.POST.get('confirm') != 'yes':
        messages.error(request, 'Debes confirmar expresamente el cierre sandbox.')
        return redirect('payments:professional_day_settlement_admin')
    settlement = get_object_or_404(
        Settlement, pk=settlement_id,
        scope_type=Settlement.ScopeType.PROFESSIONAL_DAY,
    )
    try:
        closed = settle_professional_day_settlement(
            settlement, reviewed_by=request.user,
        )
    except (SettlementProcessingError, ValidationError) as exc:
        messages.error(request, f'Liquidación rechazada: {exc}')
    else:
        messages.success(request, (
            f'Liquidación #{closed.pk} cerrada SOLO EN SANDBOX. '
            f'Neto: ${closed.net_amount_clp:,} CLP. Sin transferencia real.'
        ).replace(',', '.'))
    return redirect('payments:professional_day_settlement_admin')


@login_required(login_url='accounts:login')
@require_POST
@csrf_protect
def professional_day_settlement_release(request, settlement_id):
    """Liberar retención requiere confirmación y ausencia de bloqueos."""
    _require_operator(request)
    if request.POST.get('confirm') != 'yes':
        messages.error(request, 'Debes confirmar la revisión de la retención.')
        return redirect('payments:professional_day_settlement_admin')
    settlement = get_object_or_404(
        Settlement, pk=settlement_id,
        scope_type=Settlement.ScopeType.PROFESSIONAL_DAY,
    )
    try:
        current = release_professional_day_hold(
            settlement, reviewed_by=request.user,
        )
    except (SettlementProcessingError, ValidationError) as exc:
        messages.error(request, f'No se pudo liberar la jornada: {exc}')
    else:
        messages.success(request, (
            f'Jornada #{current.pk} revisada y liberada. '
            f'Estado: {current.get_status_display()}.'
        ))
    return redirect('payments:professional_day_settlement_admin')
