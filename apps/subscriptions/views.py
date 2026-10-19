from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import SubscriptionPlan
from .services import (
    SubscriptionProcessingError,
    cancel_subscription_at_period_end,
    get_effective_subscription,
    get_member_community_publication_limit,
    get_member_pending_space_request_limit,
    reactivate_subscription,
    start_subscription,
    user_can_use_plan,
)


PLAN_BENEFITS = {
    SubscriptionPlan.Code.MEMBER_PLUS: [
        '3 publicaciones comunitarias por semana.',
        'Hasta 5 solicitudes de espacios pendientes simultáneamente.',
        'Las reservas confirmadas pagadas no consumen este límite.',
    ],
    SubscriptionPlan.Code.PROFESSIONAL_PRO: [
        'Incluye todos los beneficios de Miembro Plus.',
        'Comisión profesional reducida de 12% a 7%.',
        'Prioridad en resultados por zona y especialidad.',
    ],
    SubscriptionPlan.Code.SPACES_PRO: [
        'Incluye todos los beneficios de Miembro Plus.',
        'Comisión de espacios reducida de 10% a 5%.',
        'Prioridad para espacios en resultados de búsqueda.',
    ],
    SubscriptionPlan.Code.PRO_INTEGRAL: [
        'Incluye todos los beneficios de Miembro Plus.',
        'Comisión profesional de 7%.',
        'Comisión de espacios de 5%.',
        'Prioridad profesional y de espacios.',
    ],
}


def _sandbox_enabled():
    return bool(
        getattr(
            settings,
            'SUBSCRIPTIONS_SANDBOX',
            settings.DEBUG,
        )
    )


@login_required(login_url='accounts:login')
def plans(request):
    current_subscription = get_effective_subscription(
        request.user,
    )

    plan_cards = []

    for plan in (
        SubscriptionPlan.objects
        .filter(is_active=True)
        .order_by(
            'display_order',
            'monthly_price_clp',
        )
    ):
        can_use, reason = user_can_use_plan(
            request.user,
            plan,
        )

        plan_cards.append(
            {
                'plan': plan,
                'benefits': PLAN_BENEFITS.get(
                    plan.code,
                    [],
                ),
                'can_use': can_use,
                'reason': reason,
                'is_current': bool(
                    current_subscription
                    and current_subscription.plan_id == plan.id
                ),
            }
        )

    return render(
        request,
        'subscriptions/plans.html',
        {
            'plan_cards': plan_cards,
            'current_subscription': current_subscription,
            'member_publication_limit': (
                get_member_community_publication_limit(
                    request.user,
                )
            ),
            'member_space_request_limit': (
                get_member_pending_space_request_limit(
                    request.user,
                )
            ),
            'sandbox_enabled': _sandbox_enabled(),
        },
    )


@login_required(login_url='accounts:login')
def start_plan(request, plan_code):
    if request.method != 'POST':
        return redirect(
            'subscriptions:plans',
        )

    if not _sandbox_enabled():
        messages.error(
            request,
            'La activación sandbox no está disponible.',
        )
        return redirect(
            'subscriptions:plans',
        )

    plan = get_object_or_404(
        SubscriptionPlan,
        code=plan_code,
        is_active=True,
    )

    try:
        subscription = start_subscription(
            request.user,
            plan,
        )
    except SubscriptionProcessingError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            'subscriptions:plans',
        )

    if subscription.status == subscription.Status.TRIAL:
        messages.success(
            request,
            (
                f'{plan.name} activado. '
                f'Comenzaste tu prueba gratuita de {plan.trial_days} días.'
            ),
        )
    else:
        messages.success(
            request,
            f'{plan.name} activado correctamente en sandbox.',
        )

    return redirect(
        'subscriptions:plans',
    )


@login_required(login_url='accounts:login')
def cancel_plan(request):
    if request.method != 'POST':
        return redirect(
            'subscriptions:plans',
        )

    subscription = get_effective_subscription(
        request.user,
    )

    if not subscription:
        messages.info(
            request,
            'No tienes una suscripción vigente.',
        )
        return redirect(
            'subscriptions:plans',
        )

    try:
        cancel_subscription_at_period_end(
            subscription,
            request.user,
        )
    except SubscriptionProcessingError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            'subscriptions:plans',
        )

    messages.success(
        request,
        (
            'La cancelación quedó programada. '
            'Mantendrás los beneficios hasta el final del periodo vigente.'
        ),
    )

    return redirect(
        'subscriptions:plans',
    )


@login_required(login_url='accounts:login')
def reactivate_plan(request):
    if request.method != 'POST':
        return redirect(
            'subscriptions:plans',
        )

    subscription = (
        request.user.subscriptions
        .filter(
            status='cancel_at_period_end',
        )
        .select_related('plan')
        .order_by('-created_at')
        .first()
    )

    if not subscription:
        messages.info(
            request,
            'No tienes una cancelación programada para revertir.',
        )
        return redirect(
            'subscriptions:plans',
        )

    try:
        reactivate_subscription(
            subscription,
            request.user,
        )
    except SubscriptionProcessingError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            'subscriptions:plans',
        )

    messages.success(
        request,
        'Tu suscripción volvió a quedar activa.',
    )

    return redirect(
        'subscriptions:plans',
    )
