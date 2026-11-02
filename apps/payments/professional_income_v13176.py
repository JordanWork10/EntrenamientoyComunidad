"""V131.76: ingresos de actividades y sesiones individuales del Profesional.

Instalar en: apps/payments/professional_income_v13176.py

Solo lectura. Reutiliza los snapshots de montos/comisiones y NO ejecuta
liquidaciones, aprobaciones, reembolsos ni cambios de estado.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.activities.models import Activity
from apps.professionals.models import ProfessionalProfile

from .models import Payment
from .views import (
    _build_professional_activity_groups,
    _economic_payment_statuses,
)


def _settlement_label(payment):
    """Estado económico del pago, separado del estado de la reserva."""
    if payment.status == Payment.Status.REFUNDED:
        return {'code': 'refunded', 'label': 'Reembolsado'}
    if payment.status == Payment.Status.PARTIALLY_REFUNDED:
        return {'code': 'partially_refunded', 'label': 'Reembolso parcial'}

    labels = {
        Payment.SettlementStatus.PENDING: ('pending', 'Pendiente de liquidación'),
        Payment.SettlementStatus.ELIGIBLE: ('eligible', 'Elegible para liquidación'),
        Payment.SettlementStatus.ON_HOLD: ('on_hold', 'En revisión'),
        Payment.SettlementStatus.SETTLED: ('settled', 'Liquidado'),
    }
    code, label = labels.get(
        payment.settlement_status,
        ('pending', 'Pendiente de liquidación'),
    )
    return {'code': code, 'label': label}


def _professional_session_groups(payments):
    """Una tarjeta por pago histórico aprobado de sesión individual."""
    groups = []

    for payment in payments:
        booking = payment.professional_booking
        settlement = _settlement_label(payment)

        groups.append({
            'payment': payment,
            'booking': booking,
            'member': payment.payer,
            'gross_total': payment.amount_clp,
            'refunded_total': payment.refunded_amount_clp,
            'commission_total': payment.commission_amount_clp,
            'net_total': payment.net_amount_clp,
            'settlement_code': settlement['code'],
            'settlement_label': settlement['label'],
        })

    return groups


@login_required(login_url='accounts:login')
def professional_income(request):
    """Muestra actividades y sesiones sin mezclar sus claves de negocio."""
    professional_profile = getattr(request.user, 'professional_profile', None)

    if (
        professional_profile is None
        or professional_profile.verification_status
        != ProfessionalProfile.VerificationStatus.VERIFIED
    ):
        messages.error(
            request,
            'Necesitas un Perfil Profesional verificado para revisar tus pagos.',
        )
        return redirect('accounts:dashboard')

    # Se conserva la consulta original de actividades, incluida su agrupación
    # por cupos pagados, estados de liquidación y reembolsos históricos.
    activity_payments = list(
        Payment.objects.filter(
            activity__organizer=request.user,
            activity__activity_type=Activity.ActivityType.PROFESSIONAL,
            status__in=_economic_payment_statuses(),
        )
        .select_related(
            'payer',
            'activity',
            'activity__category',
            'registration',
        )
        .order_by(
            '-activity__date',
            '-activity__start_time',
            '-approved_at',
            '-created_at',
        )
    )

    activity_groups = _build_professional_activity_groups(activity_payments)

    # FK profesional_booking identifica a una sesión individual. No usamos
    # activity ni space_booking aquí para impedir cifras cruzadas.
    session_payments = list(
        Payment.objects.filter(
            professional_booking__professional_profile=professional_profile,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
            status__in=_economic_payment_statuses(),
        )
        .select_related(
            'payer',
            'professional_booking',
            'professional_booking__professional_profile',
            'professional_booking__service',
        )
        .order_by(
            '-professional_booking__session_date',
            '-professional_booking__start_time',
            '-approved_at',
            '-created_at',
        )
    )

    session_groups = _professional_session_groups(session_payments)
    all_paid_payments = activity_payments + session_payments

    # Los reembolsados al 100 % conservan el bruto histórico, pero aportan
    # 0 al neto. No se suman intentos pending/failed/cancelled.
    to_settle_total = sum(
        payment.net_amount_clp
        for payment in all_paid_payments
        if payment.settlement_status in (
            Payment.SettlementStatus.PENDING,
            Payment.SettlementStatus.ELIGIBLE,
            Payment.SettlementStatus.ON_HOLD,
        )
    )
    settled_total = sum(
        payment.net_amount_clp
        for payment in all_paid_payments
        if payment.settlement_status == Payment.SettlementStatus.SETTLED
    )
    refunded_total = sum(
        payment.refunded_amount_clp
        for payment in all_paid_payments
    )
    gross_total = sum(payment.amount_clp for payment in all_paid_payments)
    commission_total = sum(
        payment.commission_amount_clp for payment in all_paid_payments
    )

    return render(request, 'payments/professional_income.html', {
        'professional_profile': professional_profile,
        'activity_groups': activity_groups,
        'session_groups': session_groups,
        'to_settle_total': to_settle_total,
        'settled_total': settled_total,
        'refunded_total': refunded_total,
        'gross_total': gross_total,
        'commission_total': commission_total,
        'paid_activity_count': len(activity_groups),
        'paid_session_count': len(session_groups),
    })
