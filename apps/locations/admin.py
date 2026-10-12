from django.contrib import admin

from .models import Commune, Region


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):

    list_display = (
        'name',
        'code',
        'is_active',
    )

    search_fields = (
        'name',
        'code',
    )

    list_filter = (
        'is_active',
    )


@admin.register(Commune)
class CommuneAdmin(admin.ModelAdmin):

    list_display = (
        'name',
        'region',
        'code',
        'is_active',
    )

    search_fields = (
        'name',
        'code',
        'region__name',
    )

    list_filter = (
        'region',
        'is_active',
    )