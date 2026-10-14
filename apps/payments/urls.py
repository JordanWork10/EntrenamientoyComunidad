from django.urls import path

from . import views


app_name = 'payments'


urlpatterns = [
    path(
        'mis-pagos/',
        views.my_payments,
        name='my_payments',
    ),

    path(
        'ingresos/',
        views.professional_income,
        name='professional_income',
    ),

    path(
        'actividad/<int:activity_id>/checkout/',
        views.checkout,
        name='checkout',
    ),

    path(
        'actividad/<int:activity_id>/movimientos/',
        views.activity_payments,
        name='activity_payments',
    ),

    path(
        '<uuid:payment_id>/',
        views.receipt,
        name='receipt',
    ),

    path(
        '<uuid:payment_id>/sandbox/aprobar/',
        views.sandbox_approve,
        name='sandbox_approve',
    ),

    path(
        '<uuid:payment_id>/sandbox/rechazar/',
        views.sandbox_reject,
        name='sandbox_reject',
    ),

    path(
        '<uuid:payment_id>/cancelar/',
        views.cancel_payment,
        name='cancel',
    ),
]
