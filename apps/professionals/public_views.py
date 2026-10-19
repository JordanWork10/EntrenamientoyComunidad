from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render

from apps.locations.models import Commune, Region
from apps.subscriptions.services import has_professional_priority

from .models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalSpecialty,
)


def _published_services_queryset():
    """
    Base segura del catálogo público.

    Solo expone servicios que cumplen simultáneamente:
    - servicio Publicado;
    - Profesional Verificado;
    - Perfil Profesional público.
    """

    return (
        ProfessionalService.objects
        .filter(
            publication_status=(
                ProfessionalService
                .PublicationStatus
                .PUBLISHED
            ),
            professional_profile__verification_status=(
                ProfessionalProfile
                .VerificationStatus
                .VERIFIED
            ),
            professional_profile__is_public=True,
        )
        .select_related(
            'professional_profile',
            'professional_profile__user',
            'professional_profile__category',
            'professional_profile__specialty',
            'location_commune',
            'location_commune__region',
        )
    )


def public_service_catalog(request):
    """
    Catálogo público de servicios profesionales.

    Permite buscar y filtrar sin exponer borradores,
    servicios pausados o perfiles no habilitados.
    """

    services = _published_services_queryset()

    query = request.GET.get('q', '').strip()
    mode = request.GET.get('mode', '').strip()
    category_id = request.GET.get('category', '').strip()
    specialty_id = request.GET.get('specialty', '').strip()
    region_id = request.GET.get('region', '').strip()
    commune_id = request.GET.get('commune', '').strip()
    professional_id = request.GET.get('professional', '').strip()

    if query:
        services = services.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(
                professional_profile__professional_title__icontains=query
            )
            | Q(
                professional_profile__user__first_name__icontains=query
            )
            | Q(
                professional_profile__user__last_name__icontains=query
            )
            | Q(
                professional_profile__category__name__icontains=query
            )
            | Q(
                professional_profile__specialty__name__icontains=query
            )
        )

    valid_modes = {
        choice[0]
        for choice in ProfessionalService.ServiceMode.choices
    }

    if mode in valid_modes:
        services = services.filter(
            mode=mode
        )

    if category_id.isdigit():
        services = services.filter(
            professional_profile__category_id=category_id
        )

    if specialty_id.isdigit():
        services = services.filter(
            professional_profile__specialty_id=specialty_id
        )

    if region_id.isdigit():
        services = services.filter(
            location_commune__region_id=region_id
        )

    if commune_id.isdigit():
        services = services.filter(
            location_commune_id=commune_id
        )

    if professional_id.isdigit():
        services = services.filter(
            professional_profile_id=professional_id
        )

    services = list(
        services.order_by(
            '-published_at',
            '-created_at',
        )
    )

    priority_search_active = bool(
        query
        or category_id.isdigit()
        or specialty_id.isdigit()
        or region_id.isdigit()
        or commune_id.isdigit()
    )

    priority_by_user = {}

    for service in services:
        user = service.professional_profile.user

        if user.id not in priority_by_user:
            priority_by_user[user.id] = has_professional_priority(
                user
            )

        service.has_professional_priority = priority_by_user[user.id]

        service.price_display = (
            f'${service.price:,}'
            .replace(',', '.')
            + ' CLP'
        )

    if priority_search_active:
        services.sort(
            key=lambda service: (
                0
                if service.has_professional_priority
                else 1
            )
        )

    priority_result_count = sum(
        1
        for service in services
        if service.has_professional_priority
    )

    categories = (
        ProfessionalCategory.objects
        .filter(
            is_active=True
        )
        .order_by(
            'display_order',
            'name',
        )
    )

    specialties = (
        ProfessionalSpecialty.objects
        .filter(
            is_active=True
        )
        .select_related(
            'category'
        )
        .order_by(
            'category__display_order',
            'display_order',
            'name',
        )
    )

    if category_id.isdigit():
        specialties = specialties.filter(
            category_id=category_id
        )

    published_region_ids = (
        _published_services_queryset()
        .exclude(
            location_commune__isnull=True
        )
        .values_list(
            'location_commune__region_id',
            flat=True,
        )
        .distinct()
    )

    regions = (
        Region.objects
        .filter(
            pk__in=published_region_ids,
            is_active=True,
        )
        .order_by(
            'name',
        )
    )

    published_commune_ids = (
        _published_services_queryset()
        .exclude(
            location_commune__isnull=True
        )
        .values_list(
            'location_commune_id',
            flat=True,
        )
        .distinct()
    )

    communes = (
        Commune.objects
        .filter(
            pk__in=published_commune_ids,
            is_active=True,
        )
        .select_related(
            'region'
        )
        .order_by(
            'region__name',
            'name',
        )
    )

    if region_id.isdigit():
        communes = communes.filter(
            region_id=region_id
        )

    return render(
        request,
        'professionals/public_service_catalog.html',
        {
            'services': services,
            'result_count': len(services),
            'priority_search_active': priority_search_active,
            'priority_result_count': priority_result_count,
            'categories': categories,
            'specialties': specialties,
            'regions': regions,
            'communes': communes,
            'mode_choices': (
                ProfessionalService
                .ServiceMode
                .choices
            ),
            'filters': {
                'q': query,
                'mode': mode,
                'category': category_id,
                'specialty': specialty_id,
                'region': region_id,
                'commune': commune_id,
                'professional': professional_id,
            },
        }
    )


def public_service_detail(
    request,
    service_id
):
    """
    Ficha pública de un servicio profesional habilitado.
    """

    service = get_object_or_404(
        _published_services_queryset(),
        pk=service_id,
    )

    active_availabilities = (
        service.availabilities
        .filter(
            is_active=True
        )
        .order_by(
            'weekday',
            'start_time',
        )
    )

    coverage_communes = (
        service.professional_profile
        .coverage_communes
        .select_related(
            'region'
        )
        .order_by(
            'region__name',
            'name',
        )
    )

    price_display = (
        f'${service.price:,}'
        .replace(',', '.')
        + ' CLP'
    )

    return render(
        request,
        'professionals/public_service_detail.html',
        {
            'service': service,
            'price_display': price_display,
            'active_availabilities': (
                active_availabilities
            ),
            'coverage_communes': (
                coverage_communes
            ),
        }
    )


def public_professional_detail(
    request,
    professional_id
):
    """
    Perfil público de un Profesional verificado.

    Solo expone información profesional pública.
    Nunca muestra RUT, correo, teléfono ni otros
    datos privados de la Cuenta Única.
    """

    professional = get_object_or_404(
        ProfessionalProfile.objects
        .select_related(
            'user',
            'category',
            'specialty',
        ),
        pk=professional_id,
        verification_status=(
            ProfessionalProfile
            .VerificationStatus
            .VERIFIED
        ),
        is_public=True,
    )

    coverage_communes = (
        professional
        .coverage_communes
        .filter(
            is_active=True
        )
        .select_related(
            'region'
        )
        .order_by(
            'region__name',
            'name',
        )
    )

    services = list(
        _published_services_queryset()
        .filter(
            professional_profile=professional
        )
        .annotate(
            active_availability_count=Count(
                'availabilities',
                filter=Q(
                    availabilities__is_active=True
                ),
                distinct=True,
            )
        )
        .order_by(
            '-published_at',
            '-created_at',
        )
    )

    mode_labels = []

    if professional.offers_in_person:
        mode_labels.append(
            'Presencial'
        )

    if professional.offers_online:
        mode_labels.append(
            'Online'
        )

    return render(
        request,
        'professionals/public_professional_detail.html',
        {
            'professional': professional,
            'services': services,
            'service_count': len(services),
            'coverage_communes': coverage_communes,
            'mode_labels': mode_labels,
        }
    )

