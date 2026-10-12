from django.contrib import admin

from .models import Activity, ActivityCategory, ActivityRegistration


@admin.register(ActivityCategory)
class ActivityCategoryAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'slug',
        'is_active',
        'created_at',
    )
    list_filter = (
        'is_active',
    )
    search_fields = (
        'name',
        'slug',
    )
    ordering = (
        'name',
    )


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'activity_type',
        'organizer',
        'category',
        'date',
        'start_time',
        'capacity',
        'status',
    )

    list_filter = (
        'activity_type',
        'modality',
        'level',
        'status',
        'category',
        'date',
    )

    search_fields = (
        'title',
        'description',
        'organizer__username',
        'organizer__first_name',
        'organizer__last_name',
    )

    readonly_fields = (
        'published_at',
        'created_at',
        'updated_at',
    )

    ordering = (
        '-date',
        '-start_time',
    )


@admin.register(ActivityRegistration)
class ActivityRegistrationAdmin(admin.ModelAdmin):
    list_display = (
        'activity',
        'member',
        'status',
        'registered_at',
    )

    list_filter = (
        'status',
        'registered_at',
    )

    search_fields = (
        'activity__title',
        'member__username',
        'member__first_name',
        'member__last_name',
    )

    readonly_fields = (
        'registered_at',
        'updated_at',
    )

    ordering = (
        '-registered_at',
    )