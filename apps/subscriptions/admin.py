from django.contrib import admin

from .models import (
    SubscriptionAccount,
    SubscriptionEvent,
    SubscriptionPlan,
    UserSubscription,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'code',
        'monthly_price_clp',
        'intro_price_clp',
        'trial_days',
        'professional_commission_rate',
        'space_commission_rate',
        'is_active',
    )

    list_filter = (
        'is_active',
        'includes_member_plus',
    )

    search_fields = (
        'name',
        'code',
    )


@admin.register(SubscriptionAccount)
class SubscriptionAccountAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'trial_used',
        'intro_months_used',
        'updated_at',
    )

    list_filter = (
        'trial_used',
    )

    search_fields = (
        'user__email',
        'user__first_name',
        'user__last_name',
    )


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'plan',
        'status',
        'started_at',
        'trial_ends_at',
        'current_period_end',
        'next_billing_at',
    )

    list_filter = (
        'status',
        'plan',
        'provider',
    )

    search_fields = (
        'user__email',
        'user__first_name',
        'user__last_name',
        'provider_subscription_reference',
    )


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = (
        'subscription',
        'event_type',
        'amount_clp',
        'occurred_at',
    )

    list_filter = (
        'event_type',
        'occurred_at',
    )

    search_fields = (
        'subscription__user__email',
        'subscription__plan__name',
    )

    readonly_fields = (
        'occurred_at',
    )
