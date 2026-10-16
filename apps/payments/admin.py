from django.contrib import admin

from .models import Payment, Refund, Settlement


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'public_id',
        'payer',
        'activity',
        'amount_clp',
        'status',
        'plan_code_snapshot',
        'commission_rate_percent',
        'net_amount_clp',
        'settlement_status',
        'provider',
        'created_at',
    )

    list_filter = (
        'status',
        'settlement_status',
        'economic_scope',
        'provider',
        'currency',
        'plan_code_snapshot',
        'created_at',
    )

    search_fields = (
        'public_id',
        'payer__email',
        'payer__first_name',
        'payer__last_name',
        'activity__title',
        'provider_reference',
        'policy_version',
    )

    readonly_fields = (
        'public_id',
        'created_at',
        'updated_at',
        'approved_at',
        'settled_at',
    )


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = (
        'public_id',
        'payment',
        'refund_type',
        'reason',
        'amount_clp',
        'status',
        'requested_at',
        'processed_at',
    )

    list_filter = (
        'refund_type',
        'reason',
        'status',
        'requested_at',
    )

    search_fields = (
        'public_id',
        'payment__public_id',
        'payment__payer__email',
        'provider_reference',
    )

    readonly_fields = (
        'public_id',
        'requested_at',
        'updated_at',
    )


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = (
        'public_id',
        'beneficiary',
        'scope_type',
        'activity',
        'reference_date',
        'gross_amount_clp',
        'commission_amount_clp',
        'net_amount_clp',
        'status',
        'eligible_at',
        'settled_at',
    )

    list_filter = (
        'scope_type',
        'status',
        'reference_date',
        'created_at',
    )

    search_fields = (
        'public_id',
        'beneficiary__email',
        'beneficiary__first_name',
        'beneficiary__last_name',
        'activity__title',
        'provider_reference',
    )

    readonly_fields = (
        'public_id',
        'created_at',
        'updated_at',
    )
