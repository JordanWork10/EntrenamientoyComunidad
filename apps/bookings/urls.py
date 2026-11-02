"""Rutas de reservas V131.75, con pagos de sesiones individuales seguros."""
from django.urls import path

from apps.payments import professional_booking_bridge_views

from . import views, review_views, incident_response_views

app_name = 'bookings'

urlpatterns = [
    # V121 - Confirmaciones, conformidades y evaluaciones.
    path('<int:booking_id>/conformidad/', review_views.review_session, name='session_review'),
    path('<int:booking_id>/conformidad/confirmar/', review_views.confirm_session, name='session_review_confirm'),
    path('<int:booking_id>/conformidad/reportar/', review_views.report_session, name='session_review_report'),
    path('<int:booking_id>/conformidad/evaluar/', review_views.rate_session, name='session_review_rate'),

    # V123 - Incidencias.
    path('profesional/<int:booking_id>/incidencia/', review_views.professional_incident_status, name='professional_incident_status'),
    path('profesional/<int:booking_id>/incidencia/responder/', incident_response_views.submit_professional_incident_response, name='professional_incident_respond'),

    # Reservas del Miembro.
    path('mis-reservas/', views.my_bookings, name='my_bookings'),

    # Reservas recibidas por el Profesional.
    path('profesional/recibidas/', views.professional_received_bookings, name='professional_received'),
    path('profesional/<int:booking_id>/', professional_booking_bridge_views.professional_booking_detail, name='professional_detail'),
    path('profesional/<int:booking_id>/confirmar/', views.professional_confirm_booking, name='professional_confirm'),
    path('profesional/<int:booking_id>/cancelar/', professional_booking_bridge_views.professional_cancel_booking, name='professional_cancel'),
    path('profesional/<int:booking_id>/completar/', views.professional_complete_booking, name='professional_complete'),

    # Disponibilidad y solicitudes.
    path('servicios/<int:service_id>/horarios/', views.service_booking_slots, name='service_slots'),
    path('servicios/<int:service_id>/confirmar/', views.confirm_booking, name='confirm'),

    # Detalle y cancelación del Miembro.
    path('<int:booking_id>/cancelar/', professional_booking_bridge_views.cancel_my_booking, name='cancel_my_booking'),
    path('<int:booking_id>/', professional_booking_bridge_views.booking_detail, name='detail'),
]

from apps.payments.economic_actor_routes_v13186 import enable_external_economic_audit

urlpatterns = enable_external_economic_audit(urlpatterns, app_name='bookings')