from django.urls import path

from . import views


app_name = 'bookings'


urlpatterns = [
    path(
        'mis-reservas/',
        views.my_bookings,
        name='my_bookings',
    ),

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
