from django.urls import path

from . import public_views
from . import views


app_name = 'professionals'


urlpatterns = [
    # =====================================================
    # CATÁLOGO PÚBLICO
    # =====================================================

    path(
        'explorar/',
        public_views.public_service_catalog,
        name='public_service_catalog',
    ),

    path(
        'perfil/<int:professional_id>/',
        public_views.public_professional_detail,
        name='public_professional_detail',
    ),

    path(
        'servicios/<int:service_id>/',
        public_views.public_service_detail,
        name='public_service_detail',
    ),

    # =====================================================
    # PERFIL PROFESIONAL
    # =====================================================

    path(
        'solicitar-perfil/',
        views.request_professional_profile,
        name='request_profile'
    ),

    path(
        'especialidades/',
        views.specialties_by_category,
        name='specialties_by_category'
    ),

    path(
        'comunas-cobertura/',
        views.coverage_communes_by_region,
        name='coverage_communes_by_region'
    ),

    path(
        'panel/',
        views.professional_dashboard,
        name='dashboard',
    ),

    path(
        'agenda/',
        views.professional_calendar,
        name='calendar',
    ),

    # =====================================================
    # SERVICIOS
    # =====================================================

    path(
        'servicios/crear/',
        views.create_professional_service,
        name='create_service',
    ),

    path(
        'servicios/<int:service_id>/editar/',
        views.edit_professional_service,
        name='edit_service',
    ),

    path(
        'servicios/<int:service_id>/publicar/',
        views.publish_professional_service,
        name='publish_service',
    ),

    path(
        'servicios/<int:service_id>/pausar/',
        views.pause_professional_service,
        name='pause_service',
    ),

    # =====================================================
    # DISPONIBILIDAD
    # =====================================================

    path(
        'servicios/<int:service_id>/disponibilidad/agregar/',
        views.create_service_availability,
        name='create_service_availability',
    ),

    path(
        'disponibilidades/<int:availability_id>/editar/',
        views.edit_service_availability,
        name='edit_service_availability',
    ),

    path(
        'disponibilidades/<int:availability_id>/desactivar/',
        views.deactivate_service_availability,
        name='deactivate_service_availability',
    ),

    path(
        'disponibilidades/<int:availability_id>/activar/',
        views.activate_service_availability,
        name='activate_service_availability',
    ),

    path(
        'disponibilidades/<int:availability_id>/historial/',
        views.service_availability_history,
        name='service_availability_history',
    ),

    path(
        'servicios/<int:service_id>/sesiones/',
        views.service_reservable_slots_preview,
        name='service_slots_preview',
    ),
]
