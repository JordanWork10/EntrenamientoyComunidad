import calendar
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    PROFESSIONAL_BASE_COMMISSION,
    SPACE_BASE_COMMISSION,
    SubscriptionAccount,
    SubscriptionEvent,
    SubscriptionPlan,
    UserSubscription,
)


PROFESSIONAL_BASE_PLAN_CODE = 'professional_base'
SPACE_BASE_PLAN_CODE = 'space_provider_base'

MEMBER_BASE_COMMUNITY_PUBLICATIONS_PER_WEEK = 1
MEMBER_PLUS_COMMUNITY_PUBLICATIONS_PER_WEEK = 3
MEMBER_BASE_PENDING_SPACE_REQUESTS = 2
MEMBER_PLUS_PENDING_SPACE_REQUESTS = 5


@dataclass(frozen=True)
class PlanCommissionSnapshot:
    plan_code: str
    plan_name: str
    commission_rate_percent: Decimal
    is_premium: bool


class SubscriptionProcessingError(Exception):
    pass


def _add_one_calendar_month(value):
    year = value.year
    month = value.month + 1

    if month == 13:
        month = 1
        year += 1

    day = min(
        value.day,
        calendar.monthrange(year, month)[1],
    )

    return value.replace(
        year=year,
        month=month,
        day=day,
    )


def get_effective_subscription(user, at=None):
    if not user or not getattr(user, 'is_authenticated', False):
        return None

    at = at or timezone.now()

    subscriptions = (
        UserSubscription.objects
        .filter(
            user=user,
            status__in={
                UserSubscription.Status.TRIAL,
                UserSubscription.Status.ACTIVE,
                UserSubscription.Status.PAST_DUE,
                UserSubscription.Status.CANCEL_AT_PERIOD_END,
            },
        )
        .select_related('plan')
        .order_by('-created_at')
    )

    for subscription in subscriptions:
        if subscription.ended_at and subscription.ended_at <= at:
            continue

        if subscription.status == UserSubscription.Status.TRIAL:
            if (
                not subscription.trial_ends_at
                or subscription.trial_ends_at <= at
            ):
                continue

        if (
            subscription.status
            == UserSubscription.Status.CANCEL_AT_PERIOD_END
            and subscription.current_period_end
            and subscription.current_period_end <= at
        ):
            continue

        return subscription

    return None


def has_member_plus_benefits(user, at=None):
    subscription = get_effective_subscription(user, at=at)
    return bool(subscription and subscription.plan.includes_member_plus)


def has_professional_priority(user, at=None):
    """
    Indica si la Cuenta Única tiene prioridad profesional vigente.

    La prioridad se concede únicamente a planes que incluyen
    beneficios profesionales reales, como Profesional Pro o Pro Integral.
    """
    subscription = get_effective_subscription(user, at=at)

    return bool(
        subscription
        and subscription.plan.professional_commission_rate is not None
    )


def get_member_community_publication_limit(user, at=None):
    if has_member_plus_benefits(user, at=at):
        return MEMBER_PLUS_COMMUNITY_PUBLICATIONS_PER_WEEK
    return MEMBER_BASE_COMMUNITY_PUBLICATIONS_PER_WEEK


def get_member_pending_space_request_limit(user, at=None):
    if has_member_plus_benefits(user, at=at):
        return MEMBER_PLUS_PENDING_SPACE_REQUESTS
    return MEMBER_BASE_PENDING_SPACE_REQUESTS


def get_professional_commission_snapshot(user, at=None):
    subscription = get_effective_subscription(user, at=at)

    if (
        subscription
        and subscription.plan.professional_commission_rate is not None
    ):
        return PlanCommissionSnapshot(
            plan_code=subscription.plan.code,
            plan_name=subscription.plan.name,
            commission_rate_percent=(
                subscription.plan.professional_commission_rate
            ),
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

    if (
        subscription
        and subscription.plan.space_commission_rate is not None
    ):
        return PlanCommissionSnapshot(
            plan_code=subscription.plan.code,
            plan_name=subscription.plan.name,
            commission_rate_percent=(
                subscription.plan.space_commission_rate
            ),
            is_premium=True,
        )

    return PlanCommissionSnapshot(
        plan_code=SPACE_BASE_PLAN_CODE,
        plan_name='Proveedor Base',
        commission_rate_percent=SPACE_BASE_COMMISSION,
        is_premium=False,
    )


def get_plan_by_code(code):
    return (
        SubscriptionPlan.objects
        .filter(code=code, is_active=True)
        .first()
    )


def user_can_use_plan(user, plan):
    professional_profile = getattr(user, 'professional_profile', None)
    space_profile = getattr(user, 'space_provider_profile', None)

    professional_verified = bool(
        professional_profile
        and professional_profile.verification_status == 'verified'
    )

    space_verified = bool(
        space_profile
        and space_profile.verification_status == 'verified'
    )

    if plan.code == SubscriptionPlan.Code.MEMBER_PLUS:
        return True, ''

    if plan.code == SubscriptionPlan.Code.PROFESSIONAL_PRO:
        if professional_verified:
            return True, ''
        return (
            False,
            'Necesitas un Perfil Profesional verificado para contratar este plan.',
        )

    if plan.code == SubscriptionPlan.Code.SPACES_PRO:
        if space_verified:
            return True, ''
        return (
            False,
            'Necesitas un Perfil de Proveedor de Espacios verificado para contratar este plan.',
        )

    if plan.code == SubscriptionPlan.Code.PRO_INTEGRAL:
        if professional_verified and space_verified:
            return True, ''
        return (
            False,
            'Pro Integral requiere Perfil Profesional y Proveedor de Espacios verificados.',
        )

    return False, 'Este plan no está disponible.'


@transaction.atomic
def start_subscription(user, plan, now=None):
    now = now or timezone.now()

    can_use, reason = user_can_use_plan(user, plan)
    if not can_use:
        raise SubscriptionProcessingError(reason)

    existing = (
        UserSubscription.objects
        .select_for_update()
        .filter(
            user=user,
            status__in=[
                UserSubscription.Status.TRIAL,
                UserSubscription.Status.ACTIVE,
                UserSubscription.Status.PAST_DUE,
                UserSubscription.Status.CANCEL_AT_PERIOD_END,
            ],
        )
        .select_related('plan')
        .first()
    )

    if existing:
        raise SubscriptionProcessingError(
            f'Ya tienes {existing.plan.name} como suscripción vigente.'
        )

    account, _ = (
        SubscriptionAccount.objects
        .select_for_update()
        .get_or_create(user=user)
    )

    if not account.trial_used:
        trial_ends_at = now + timedelta(days=plan.trial_days)

        subscription = UserSubscription(
            user=user,
            plan=plan,
            status=UserSubscription.Status.TRIAL,
            provider=UserSubscription.Provider.SANDBOX,
            provider_subscription_reference='SUB-SBX-TRIAL',
            started_at=now,
            trial_started_at=now,
            trial_ends_at=trial_ends_at,
            current_period_start=now,
            current_period_end=trial_ends_at,
            next_billing_at=trial_ends_at,
        )
        subscription.full_clean()
        subscription.save()

        account.trial_used = True
        account.save(
            update_fields=[
                'trial_used',
                'updated_at',
            ]
        )

        SubscriptionEvent.objects.create(
            subscription=subscription,
            event_type=SubscriptionEvent.EventType.TRIAL_STARTED,
            amount_clp=0,
            metadata={
                'trial_days': plan.trial_days,
                'next_intro_price_clp': plan.intro_price_clp,
            },
        )

        return subscription

    current_period_end = _add_one_calendar_month(now)

    subscription = UserSubscription(
        user=user,
        plan=plan,
        status=UserSubscription.Status.ACTIVE,
        provider=UserSubscription.Provider.SANDBOX,
        provider_subscription_reference='SUB-SBX-ACTIVE',
        started_at=now,
        current_period_start=now,
        current_period_end=current_period_end,
        next_billing_at=current_period_end,
    )
    subscription.full_clean()
    subscription.save()

    charge_amount = (
        plan.intro_price_clp
        if account.intro_months_used < plan.intro_months
        else plan.monthly_price_clp
    )

    if account.intro_months_used < plan.intro_months:
        account.intro_months_used += 1
        account.save(
            update_fields=[
                'intro_months_used',
                'updated_at',
            ]
        )

    SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=SubscriptionEvent.EventType.ACTIVATED,
        amount_clp=charge_amount,
        metadata={
            'sandbox': True,
            'intro_month_number': account.intro_months_used,
        },
    )

    return subscription


@transaction.atomic
def cancel_subscription_at_period_end(subscription, user, now=None):
    now = now or timezone.now()

    locked = (
        UserSubscription.objects
        .select_for_update()
        .select_related('plan')
        .get(pk=subscription.pk, user=user)
    )

    if locked.status == UserSubscription.Status.CANCEL_AT_PERIOD_END:
        return locked

    if locked.status not in {
        UserSubscription.Status.TRIAL,
        UserSubscription.Status.ACTIVE,
        UserSubscription.Status.PAST_DUE,
    }:
        raise SubscriptionProcessingError(
            'Esta suscripción ya no admite una solicitud de cancelación.'
        )

    period_end = (
        locked.trial_ends_at
        if locked.status == UserSubscription.Status.TRIAL
        else locked.current_period_end
    )

    if not period_end:
        raise SubscriptionProcessingError(
            'No se pudo determinar el término del periodo actual.'
        )

    locked.status = UserSubscription.Status.CANCEL_AT_PERIOD_END
    locked.current_period_end = period_end
    locked.cancelled_at = now
    locked.save(
        update_fields=[
            'status',
            'current_period_end',
            'cancelled_at',
            'updated_at',
        ]
    )

    SubscriptionEvent.objects.create(
        subscription=locked,
        event_type=SubscriptionEvent.EventType.CANCELLATION_REQUESTED,
        metadata={
            'effective_at': period_end.isoformat(),
        },
    )

    return locked


@transaction.atomic
def reactivate_subscription(subscription, user, now=None):
    now = now or timezone.now()

    locked = (
        UserSubscription.objects
        .select_for_update()
        .select_related('plan')
        .get(pk=subscription.pk, user=user)
    )

    if locked.status != UserSubscription.Status.CANCEL_AT_PERIOD_END:
        raise SubscriptionProcessingError(
            'Esta suscripción no tiene una cancelación programada.'
        )

    if locked.trial_ends_at and now < locked.trial_ends_at:
        locked.status = UserSubscription.Status.TRIAL
    else:
        locked.status = UserSubscription.Status.ACTIVE

    locked.cancelled_at = None
    locked.save(
        update_fields=[
            'status',
            'cancelled_at',
            'updated_at',
        ]
    )

    SubscriptionEvent.objects.create(
        subscription=locked,
        event_type=SubscriptionEvent.EventType.REACTIVATED,
    )

    return locked
