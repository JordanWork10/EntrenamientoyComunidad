"""Copiar como apps/payments/urls.py (V131.85). Mantiene rutas anteriores."""

# La V131.85 envuelve únicamente las rutas económicas de escritura.
from .economic_actor_v13185 import payment_audit_path as path

from . import (
    views,
    professional_booking_views,
    professional_income_v13176,
    professional_day_settlement_views,
    member_payments_v13180,
    space_day_admin_v13181,
    admin_economic_audit_v13183,
    economic_audit_events_v13184,
)

app_name = 'payments'

urlpatterns = [
    # V131.84 - Eventos históricos creados automáticamente en PostgreSQL.
    path('administracion/economia/eventos/', economic_audit_events_v13184.economic_audit_events, name='economic_audit_events'),
    # V131.83 - Auditoría económica transversal. Solo GET y permisos de lectura.
    path('administracion/economia/auditoria/', admin_economic_audit_v13183.admin_economic_audit, name='admin_economic_audit'),
    # V131.67 - Cancelaciones de espacios.
    path('administracion/espacios/cancelaciones/', views.space_cancellation_admin, name='space_cancellation_admin'),
    path('administracion/espacios/cancelaciones/<int:cancellation_id>/resolver/', views.space_cancellation_resolve, name='space_cancellation_resolve'),
    # V131.58 - Liquidaciones de espacios.
    path('administracion/espacios/liquidaciones/', space_day_admin_v13181.space_settlement_admin, name='space_settlement_admin'),
    path('administracion/espacios/liquidaciones/<int:space_id>/<int:year>/<int:month>/<int:day>/preparar/', views.space_settlement_prepare, name='space_settlement_prepare'),
    path('administracion/espacios/liquidaciones/<int:settlement_id>/sandbox/liquidar/', views.space_settlement_close, name='space_settlement_close'),

    # V131.78 - Liquidaciones de sesiones profesionales (solo administrador).
    path('administracion/profesionales/liquidaciones/', professional_day_settlement_views.professional_day_settlement_admin, name='professional_day_settlement_admin'),
    path('administracion/profesionales/liquidaciones/<int:professional_id>/<int:year>/<int:month>/<int:day>/preparar/', professional_day_settlement_views.professional_day_settlement_prepare, name='professional_day_settlement_prepare'),
    path('administracion/profesionales/liquidaciones/<int:settlement_id>/sandbox/liquidar/', professional_day_settlement_views.professional_day_settlement_close, name='professional_day_settlement_close'),
    path('administracion/profesionales/liquidaciones/<int:settlement_id>/liberar/', professional_day_settlement_views.professional_day_settlement_release, name='professional_day_settlement_release'),

    path('mis-pagos/', member_payments_v13180.my_payments, name='my_payments'),

    # V131.76: misma URL y mismo nombre, nueva vista de solo lectura.
    path('ingresos/', professional_income_v13176.professional_income, name='professional_income'),

    # Actividades profesionales.
    path('actividad/<int:activity_id>/checkout/', views.checkout, name='checkout'),
    path('actividad/<int:activity_id>/cancelar-participacion/', views.cancel_paid_activity, name='cancel_paid_activity'),
    path('actividad/<int:activity_id>/movimientos/', views.activity_payments, name='activity_payments'),
    path('actividad/<int:activity_id>/sandbox/elegible/', views.sandbox_make_activity_settlement_eligible, name='sandbox_make_activity_settlement_eligible'),
    path('actividad/<int:activity_id>/sandbox/liquidar/', views.sandbox_settle_activity, name='sandbox_settle_activity'),

    # V131.75 - Checkout de servicios individuales.
    path('servicio/reserva/<int:booking_id>/checkout/', professional_booking_views.professional_booking_checkout, name='professional_booking_checkout'),
    path('servicio/pago/<uuid:payment_id>/', professional_booking_views.professional_booking_receipt, name='professional_booking_receipt'),
    path('servicio/pago/<uuid:payment_id>/sandbox/aprobar/', professional_booking_views.professional_booking_sandbox_approve, name='professional_booking_sandbox_approve'),
    path('servicio/pago/<uuid:payment_id>/sandbox/rechazar/', professional_booking_views.professional_booking_sandbox_reject, name='professional_booking_sandbox_reject'),
    path('servicio/pago/<uuid:payment_id>/cancelar-intento/', professional_booking_views.professional_booking_cancel_attempt, name='professional_booking_cancel_attempt'),

    # Espacios.
    path('espacios/ingresos/', views.space_income, name='space_income'),
    path('espacio/reserva/<int:booking_id>/checkout/', views.space_checkout, name='space_checkout'),
    path('espacio/pago/<uuid:payment_id>/', views.space_receipt, name='space_receipt'),
    path('espacio/pago/<uuid:payment_id>/sandbox/aprobar/', views.space_sandbox_approve, name='space_sandbox_approve'),
    path('espacio/pago/<uuid:payment_id>/sandbox/rechazar/', views.space_sandbox_reject, name='space_sandbox_reject'),
    path('espacio/pago/<uuid:payment_id>/cancelar/', views.space_cancel, name='space_cancel'),

    # Comprobantes de actividades por UUID.
    path('<uuid:payment_id>/', views.receipt, name='receipt'),
    path('<uuid:payment_id>/sandbox/aprobar/', views.sandbox_approve, name='sandbox_approve'),
    path('<uuid:payment_id>/sandbox/rechazar/', views.sandbox_reject, name='sandbox_reject'),
    path('<uuid:payment_id>/cancelar/', views.cancel_payment, name='cancel'),
]
