from django.urls import path

from . import views, review_views


app_name = 'bookings'


urlpatterns = [

    # ==========================================
    # V121 - CONFIRMACIONES Y EVALUACIONES
    # ==========================================

    path(
        '<int:booking_id>/conformidad/',
        review_views.review_session,
        name='session_review',
    ),

    path(
        '<int:booking_id>/conformidad/confirmar/',
        review_views.confirm_session,
        name='session_review_confirm',
    ),

    path(
        '<int:booking_id>/conformidad/reportar/',
        review_views.report_session,
        name='session_review_report',
    ),

    path(
        '<int:booking_id>/conformidad/evaluar/',
        review_views.rate_session,
        name='session_review_rate',
    ),


    # ==========================================
    # RESERVAS DEL MIEMBRO
    # ==========================================

    path(
        'mis-reservas/',
        views.my_bookings,
        name='my_bookings',
    ),


    # ==========================================
    # RESERVAS DEL PROFESIONAL
    # ==========================================

    path(
        'profesional/recibidas/',
        views.professional_received_bookings,
        name='professional_received',
    ),

    path(
        'profesional/<int:booking_id>/',
        views.professional_booking_detail,
        name='professional_detail',
    ),

    path(
        'profesional/<int:booking_id>/confirmar/',
        views.professional_confirm_booking,
        name='professional_confirm',
    ),

    path(
        'profesional/<int:booking_id>/cancelar/',
        views.professional_cancel_booking,
        name='professional_cancel',
    ),

    path(
        'profesional/<int:booking_id>/completar/',
        views.professional_complete_booking,
        name='professional_complete',
    ),


    # ==========================================
    # DISPONIBILIDAD Y SOLICITUD DE RESERVAS
    # ==========================================

    path(
        'servicios/<int:service_id>/horarios/',
        views.service_booking_slots,
        name='service_slots',
    ),

    path(
        'servicios/<int:service_id>/confirmar/',
        views.confirm_booking,
        name='confirm',
    ),


    # ==========================================
    # CANCELACIÓN Y DETALLE DEL MIEMBRO
    # ==========================================

    path(
        '<int:booking_id>/cancelar/',
        views.cancel_my_booking,
        name='cancel_my_booking',
    ),

    path(
        '<int:booking_id>/',
        views.booking_detail,
        name='detail',
    ),

]