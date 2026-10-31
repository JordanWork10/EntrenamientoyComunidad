"""Rutas de pagos con servicios profesionales individuales V131.75."""
from django.urls import path

from . import views, professional_booking_views

app_name = 'payments'

urlpatterns = [
    # V131.67: revisión de cancelaciones pagadas de espacios (sandbox).
    path('administracion/espacios/cancelaciones/', views.space_cancellation_admin, name='space_cancellation_admin'),
    path('administracion/espacios/cancelaciones/<int:cancellation_id>/resolver/', views.space_cancellation_resolve, name='space_cancellation_resolve'),
    # V131.58: panel administrativo de liquidaciones de recintos.
    path('administracion/espacios/liquidaciones/', views.space_settlement_admin, name='space_settlement_admin'),
    path('administracion/espacios/liquidaciones/<int:space_id>/<int:year>/<int:month>/<int:day>/preparar/', views.space_settlement_prepare, name='space_settlement_prepare'),
    path('administracion/espacios/liquidaciones/<int:settlement_id>/sandbox/liquidar/', views.space_settlement_close, name='space_settlement_close'),

    path('mis-pagos/', views.my_payments, name='my_payments'),
    path('ingresos/', views.professional_income, name='professional_income'),

    # Actividades profesionales (clases grupales).
    path('actividad/<int:activity_id>/checkout/', views.checkout, name='checkout'),
    path('actividad/<int:activity_id>/cancelar-participacion/', views.cancel_paid_activity, name='cancel_paid_activity'),
    path('actividad/<int:activity_id>/movimientos/', views.activity_payments, name='activity_payments'),
    path('actividad/<int:activity_id>/sandbox/elegible/', views.sandbox_make_activity_settlement_eligible, name='sandbox_make_activity_settlement_eligible'),
    path('actividad/<int:activity_id>/sandbox/liquidar/', views.sandbox_settle_activity, name='sandbox_settle_activity'),

    # V131.75: servicio individual, separado de actividad y espacio.
    path('servicio/reserva/<int:booking_id>/checkout/', professional_booking_views.professional_booking_checkout, name='professional_booking_checkout'),
    path('servicio/pago/<uuid:payment_id>/', professional_booking_views.professional_booking_receipt, name='professional_booking_receipt'),
    path('servicio/pago/<uuid:payment_id>/sandbox/aprobar/', professional_booking_views.professional_booking_sandbox_approve, name='professional_booking_sandbox_approve'),
    path('servicio/pago/<uuid:payment_id>/sandbox/rechazar/', professional_booking_views.professional_booking_sandbox_reject, name='professional_booking_sandbox_reject'),
    path('servicio/pago/<uuid:payment_id>/cancelar-intento/', professional_booking_views.professional_booking_cancel_attempt, name='professional_booking_cancel_attempt'),

    # V131.24: ingresos de proveedores por recinto, solo lectura.
    path('espacios/ingresos/', views.space_income, name='space_income'),

    # Arriendos de espacios.
    path('espacio/reserva/<int:booking_id>/checkout/', views.space_checkout, name='space_checkout'),
    path('espacio/pago/<uuid:payment_id>/', views.space_receipt, name='space_receipt'),
    path('espacio/pago/<uuid:payment_id>/sandbox/aprobar/', views.space_sandbox_approve, name='space_sandbox_approve'),
    path('espacio/pago/<uuid:payment_id>/sandbox/rechazar/', views.space_sandbox_reject, name='space_sandbox_reject'),
    path('espacio/pago/<uuid:payment_id>/cancelar/', views.space_cancel, name='space_cancel'),

    # Actividades: pago por UUID.
    path('<uuid:payment_id>/', views.receipt, name='receipt'),
    path('<uuid:payment_id>/sandbox/aprobar/', views.sandbox_approve, name='sandbox_approve'),
    path('<uuid:payment_id>/sandbox/rechazar/', views.sandbox_reject, name='sandbox_reject'),
    path('<uuid:payment_id>/cancelar/', views.cancel_payment, name='cancel'),
]
