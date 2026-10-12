from django.urls import path

from . import views


app_name = 'spaces'


urlpatterns = [
    path(
        '',
        views.public_space_catalog,
        name='public_catalog',
    ),

    path(
        'publico/<int:space_id>/',
        views.public_space_detail,
        name='public_detail',
    ),

    path(
        'publico/<int:space_id>/horarios/',
        views.public_space_slots,
        name='public_slots',
    ),

    path(
        'publico/<int:space_id>/reservar/',
        views.confirm_space_booking,
        name='confirm_booking',
    ),

    path(
        'mis-reservas/',
        views.my_space_bookings,
        name='my_bookings',
    ),

    path(
        'reservas/<int:booking_id>/cancelar/',
        views.cancel_my_space_booking,
        name='cancel_my_booking',
    ),

    path(
        'reservas/<int:booking_id>/',
        views.space_booking_detail,
        name='booking_detail',
    ),

    path(
        'centro/',
        views.space_provider_dashboard,
        name='dashboard',
    ),

    path(
        'centro/calendario/',
        views.provider_rental_calendar,
        name='provider_calendar',
    ),

    path(
        'centro/reservas/',
        views.provider_received_space_bookings,
        name='provider_received_bookings',
    ),

    path(
        'centro/reservas/<int:booking_id>/',
        views.provider_space_booking_detail,
        name='provider_booking_detail',
    ),

    path(
        'centro/reservas/<int:booking_id>/confirmar/',
        views.provider_confirm_space_booking,
        name='provider_confirm_booking',
    ),

    path(
        'centro/reservas/<int:booking_id>/cancelar/',
        views.provider_cancel_space_booking,
        name='provider_cancel_booking',
    ),

    path(
        'centro/reservas/<int:booking_id>/completar/',
        views.provider_complete_space_booking,
        name='provider_complete_booking',
    ),

    path(
        'centro/espacios/crear/',
        views.create_space,
        name='create_space',
    ),

    path(
        'centro/espacios/<int:space_id>/',
        views.space_detail,
        name='space_detail',
    ),

    path(
        'centro/espacios/<int:space_id>/editar/',
        views.edit_space,
        name='edit_space',
    ),

    path(
        'centro/espacios/<int:space_id>/historial/',
        views.space_history,
        name='space_history',
    ),

    path(
        'centro/espacios/<int:space_id>/publicar/',
        views.publish_space,
        name='publish_space',
    ),

    path(
        (
            'centro/espacios/<int:space_id>/'
            'disponibilidad/publicar/'
        ),
        views.publish_space_exact_availability,
        name='publish_exact_availability',
    ),

    path(
        'centro/espacios/<int:space_id>/disponibilidad/',
        views.space_availability,
        name='availability',
    ),

    path(
        (
            'centro/espacios/<int:space_id>/'
            'disponibilidad/<int:availability_id>/estado/'
        ),
        views.set_space_availability_status,
        name='availability_status',
    ),

    path(
        (
            'centro/espacios/<int:space_id>/'
            'excepciones/<int:exception_id>/estado/'
        ),
        views.set_space_availability_exception_status,
        name='availability_exception_status',
    ),

    path(
        'solicitar-perfil/',
        views.request_space_provider_profile,
        name='request_profile',
    ),

    path(
        'comunas/',
        views.communes_by_region,
        name='communes_by_region',
    ),
]
