from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from .models import (
    PROFESSIONAL_BASE_COMMISSION,
    SPACE_BASE_COMMISSION,
    SubscriptionPlan,
    UserSubscription,
)


PROFESSIONAL_BASE_PLAN_CODE = 'professional_base'
SPACE_BASE_PLAN_CODE = 'space_provider_base'


@dataclass(frozen=True)
class PlanCommissionSnapshot:
    plan_code: str
    plan_name: str
    commission_rate_percent: Decimal
    is_premium: bool


EFFECTIVE_STATUSES = {
    UserSubscription.Status.TRIAL,
    UserSubscription.Status.ACTIVE,
    UserSubscription.Status.PAST_DUE,
    UserSubscription.Status.CANCEL_AT_PERIOD_END,
}


def get_effective_subscription(user, at=None):
    """
    Devuelve la suscripción efectiva de la Cuenta Única.

    No modifica estados ni realiza cobros. V102 solo resuelve qué plan debe
    considerarse al momento de generar una nueva operación económica.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None

    at = at or timezone.now()

    subscriptions = (
        UserSubscription.objects
        .filter(user=user, status__in=EFFECTIVE_STATUSES)
        .select_related('plan')
        .order_by('-created_at')
    )

    for subscription in subscriptions:
        if subscription.ended_at and subscription.ended_at <= at:
            continue

        if subscription.status == UserSubscription.Status.TRIAL:
            if not subscription.trial_ends_at or subscription.trial_ends_at <= at:
                continue

        if subscription.status == UserSubscription.Status.CANCEL_AT_PERIOD_END:
            if (
                subscription.current_period_end
                and subscription.current_period_end <= at
            ):
                continue

        return subscription

    return None


def has_member_plus_benefits(user, at=None):
    subscription = get_effective_subscription(user, at=at)
    if not subscription:
        return False
    return bool(subscription.plan.includes_member_plus)


def get_professional_commission_snapshot(user, at=None):
    subscription = get_effective_subscription(user, at=at)

    if (
        subscription
        and subscription.plan.professional_commission_rate is not None
    ):
        return PlanCommissionSnapshot(
            plan_code=subscription.plan.code,
            plan_name=subscription.plan.name,
            commission_rate_percent=subscription.plan.professional_commission_rate,
            is_premium=True,
        )

    return PlanCommissionSnapshot(
        plan_code=PROFESSIONAL_BASE_PLAN_CODE,
        plan_name='Profesional Base',
        commission_rate_percent=PROFESSIONAL_BASE_COMMISSION,
        is_premium=False,
    )


def get_space_commission_snapshot(user, at=None):
    subscription = get_effective_subscription(user, at=at)

    if subscription and subscription.plan.space_commission_rate is not None:
        return PlanCommissionSnapshot(
            plan_code=subscription.plan.code,
            plan_name=subscription.plan.name,
            commission_rate_percent=subscription.plan.space_commission_rate,
            is_premium=True,
        )

    return PlanCommissionSnapshot(
        plan_code=SPACE_BASE_PLAN_CODE,
        plan_name='Proveedor Base',
        commission_rate_percent=SPACE_BASE_COMMISSION,
        is_premium=False,
    )


def get_plan_by_code(code):
    return SubscriptionPlan.objects.filter(code=code, is_active=True).first()
