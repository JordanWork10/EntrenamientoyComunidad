from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'public_id',
        'payer',
        'activity',
        'amount_clp',
        'currency',
        'status',
        'provider',
        'created_at',
        'approved_at',
    )

    list_filter = (
        'status',
        'provider',
        'currency',
        'created_at',
    )

    search_fields = (
        'public_id',
        'payer__email',
        'payer__first_name',
        'payer__last_name',
        'activity__title',
        'provider_reference',
    )

    readonly_fields = (
        'public_id',
        'created_at',
        'updated_at',
        'approved_at',
    )
