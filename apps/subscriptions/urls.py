from django.urls import path

from . import views


app_name = 'subscriptions'


urlpatterns = [
    path(
        '',
        views.plans,
        name='plans',
    ),

    path(
        'activar/<str:plan_code>/',
        views.start_plan,
        name='start_plan',
    ),

    path(
        'cancelar/',
        views.cancel_plan,
        name='cancel_plan',
    ),

    path(
        'reactivar/',
        views.reactivate_plan,
        name='reactivate_plan',
    ),
]
