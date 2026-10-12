from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    MemberProfile,
    PlatformInterest,
    User,
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):

    fieldsets = UserAdmin.fieldsets + (
        (
            'Información personal adicional',
            {
                'fields': (
                    'rut',
                    'phone',
                    'birth_date',
                    'commune',
                    'profile_image',
                )
            },
        ),
        (
            'Consentimientos',
            {
                'fields': (
                    'terms_accepted',
                    'terms_accepted_at',
                    'privacy_accepted',
                    'privacy_accepted_at',
                )
            },
        ),
        (
            'Sistema',
            {
                'fields': (
                    'updated_at',
                )
            },
        ),
    )

    readonly_fields = (
        'terms_accepted_at',
        'privacy_accepted_at',
        'updated_at',
    )

    list_display = (
        'username',
        'email',
        'first_name',
        'last_name',
        'rut',
        'commune',
        'is_active',
        'is_staff',
    )

    search_fields = (
        'username',
        'email',
        'first_name',
        'last_name',
        'rut',
        'phone',
    )

    list_filter = (
        'is_active',
        'is_staff',
        'is_superuser',
        'commune__region',
    )

    autocomplete_fields = (
        'commune',
    )


@admin.register(PlatformInterest)
class PlatformInterestAdmin(admin.ModelAdmin):

    list_display = (
        'name',
        'slug',
        'display_order',
        'is_active',
    )

    search_fields = (
        'name',
        'slug',
    )

    list_filter = (
        'is_active',
    )

    ordering = (
        'display_order',
        'name',
    )


@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):

    list_display = (
        'user',
        'activity_level',
        'emergency_contact_name',
        'fitness_declaration_accepted',
        'protected_payment_accepted',
        'created_at',
    )

    search_fields = (
        'user__username',
        'user__email',
        'user__first_name',
        'user__last_name',
        'emergency_contact_name',
    )

    list_filter = (
        'activity_level',
        'fitness_declaration_accepted',
        'protected_payment_accepted',
        'created_at',
    )

    filter_horizontal = (
        'interests',
    )

    readonly_fields = (
        'fitness_declaration_accepted_at',
        'protected_payment_accepted_at',
        'created_at',
        'updated_at',
    )