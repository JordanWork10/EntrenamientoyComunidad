"""V131.80 - Historial unificado, privado y de solo lectura de pagos del Miembro.

Copiar como: apps/payments/member_payments_v13180.py
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Payment


PAYMENT_TYPES = {
    'actividades': 'activity__isnull',
    'sesiones': 'professional_booking__isnull',
    'espacios': 'space_booking__isnull',
}


@login_required(login_url='accounts:login')
@require_GET
def my_payments(request):
    """Solo muestra pagos de quien inició sesión; nunca realiza operaciones."""
    all_payments = (
        Payment.objects
        .filter(payer=request.user)
        # Defensa adicional ante una relación histórica inconsistente:
        # una sesión ajena no debe figurar siquiera en el listado.
        .filter(
            Q(professional_booking__isnull=True)
            | Q(professional_booking__booked_by=request.user)
        )
    )

    economic_payments = all_payments.filter(
        status__in=(
            Payment.Status.APPROVED,
            Payment.Status.PARTIALLY_REFUNDED,
            Payment.Status.REFUNDED,
        )
    )
    amounts = economic_payments.aggregate(
        approved_total=Sum('amount_clp'),
        refunded_total=Sum('refunded_amount_clp'),
    )
    approved_total = amounts['approved_total'] or 0
    refunded_total = amounts['refunded_total'] or 0

    selected_type = request.GET.get('tipo', 'todos')
    if selected_type not in ('todos', *PAYMENT_TYPES.keys()):
        selected_type = 'todos'

    filtered_payments = all_payments
    if selected_type != 'todos':
        # Solo identificadores permitidos, nunca campos enviados por el usuario.
        filtered_payments = filtered_payments.filter(
            **{PAYMENT_TYPES[selected_type]: False}
        )

    payments = (
        filtered_payments
        .select_related(
            'activity',
            'space_booking',
            'professional_booking',
            'professional_booking__professional_profile__user',
        )
        .order_by('-created_at', '-pk')
    )

    return render(request, 'payments/my_payments.html', {
        'payments': payments,
        'selected_type': selected_type,
        'movements_total': all_payments.count(),
        'activities_count': all_payments.filter(activity__isnull=False).count(),
        'sessions_count': all_payments.filter(professional_booking__isnull=False).count(),
        'spaces_count': all_payments.filter(space_booking__isnull=False).count(),
        'approved_total': approved_total,
        'refunded_total': refunded_total,
        'retained_total': max(approved_total - refunded_total, 0),
    })
