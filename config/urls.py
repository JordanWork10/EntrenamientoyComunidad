"""URL configuration for EntrenamientoyComunidad."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path(
        'admin/',
        admin.site.urls,
    ),

    path(
        'cuenta/',
        include('apps.accounts.urls'),
    ),

    path(
        'profesionales/',
        include('apps.professionals.urls'),
    ),

    path(
        'reservas/',
        include('apps.bookings.urls'),
    ),

    path(
        'espacios/',
        include('apps.spaces.urls'),
    ),

    path(
        'actividades/',
        include('apps.activities.urls'),
    ),

    path(
        'pagos/',
        include('apps.payments.urls'),
    ),

    path(
        'suscripciones/',
        include('apps.subscriptions.urls'),
    ),

    path(
        '',
        include('apps.core.urls'),
    ),
]


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
