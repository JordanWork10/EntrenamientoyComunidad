from django import template
from django.utils import timezone

from apps.activities.models import Activity
from apps.subscriptions.services import (
    get_effective_subscription,
    get_member_community_publication_limit,
    get_professional_commission_snapshot,
    has_member_plus_benefits,
)


register = template.Library()


@register.simple_tag
def subscription_identity(user):
    """
    Resumen visual de la suscripción vigente de la Cuenta Única.

    No modifica datos ni recalcula pagos históricos. La comisión profesional
    devuelta aquí corresponde a operaciones NUEVAS realizadas mientras el plan
    esté vigente.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return {
            'subscription': None,
            'plan_name': '',
            'plan_code': '',
            'status': '',
            'status_label': '',
            'trial_ends_at': None,
            'current_period_end': None,
            'member_plus': False,
            'professional_plan_name': 'Profesional Base',
            'professional_commission_rate': None,
            'has_professional_discount': False,
        }

    subscription = get_effective_subscription(user)
    commission = get_professional_commission_snapshot(user)

    return {
        'subscription': subscription,
        'plan_name': subscription.plan.name if subscription else '',
        'plan_code': subscription.plan.code if subscription else '',
        'status': subscription.status if subscription else '',
        'status_label': (
            subscription.get_status_display()
            if subscription
            else ''
        ),
        'trial_ends_at': (
            subscription.trial_ends_at
            if subscription
            else None
        ),
        'current_period_end': (
            subscription.current_period_end
            if subscription
            else None
        ),
        'member_plus': has_member_plus_benefits(user),
        'professional_plan_name': commission.plan_name,
        'professional_commission_rate': commission.commission_rate_percent,
        'has_professional_discount': commission.is_premium,
    }


@register.simple_tag
def community_publication_summary(user):
    """
    Resume el uso semanal de publicaciones comunitarias del Miembro.

    Base: 1 publicación por semana.
    Miembro Plus y planes superiores: 3 publicaciones por semana.
    Los borradores no consumen el cupo semanal.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return {
            'limit': 0,
            'used': 0,
            'remaining': 0,
            'can_publish': False,
            'member_plus': False,
            'plan_name': '',
            'week_start': None,
            'week_end': None,
            'next_week_start': None,
        }

    now = timezone.localtime()
    week_start = now.date() - timezone.timedelta(days=now.weekday())
    week_end = week_start + timezone.timedelta(days=6)
    next_week_start = week_end + timezone.timedelta(days=1)

    limit = get_member_community_publication_limit(
        user,
        at=now,
    )

    used = (
        Activity.objects
        .filter(
            organizer=user,
            activity_type=Activity.ActivityType.COMMUNITY,
            published_at__date__range=(week_start, week_end),
        )
        .count()
    )

    subscription = get_effective_subscription(
        user,
        at=now,
    )

    member_plus = has_member_plus_benefits(
        user,
        at=now,
    )

    remaining = max(limit - used, 0)

    return {
        'limit': limit,
        'used': used,
        'remaining': remaining,
        'can_publish': remaining > 0,
        'member_plus': member_plus,
        'plan_name': (
            subscription.plan.name
            if subscription and member_plus
            else 'Miembro Base'
        ),
        'week_start': week_start,
        'week_end': week_end,
        'next_week_start': next_week_start,
    }
