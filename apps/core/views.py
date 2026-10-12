from django.db.models import Count, Prefetch, Q
from django.shortcuts import render

from apps.locations.models import Commune
from apps.professionals.models import (
    ProfessionalProfile,
    ProfessionalService,
)
from apps.spaces.models import (
    Space,
    SpaceProviderProfile,
)


def home(request):
    """
    Portada pública de EntrenamientoyComunidad.

    Muestra únicamente información real:
    - profesionales verificados y públicos;
    - que tengan al menos un servicio publicado;
    - métricas calculadas desde PostgreSQL.
    """

    published_services = (
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
            'location_commune',
            'location_commune__region',
        )
    )

    verified_professional_count = (
        published_services
        .values(
            'professional_profile_id'
        )
        .distinct()
        .count()
    )

    published_service_count = (
        published_services.count()
    )

    # Los servicios destacados se construirán desde los
    # mismos perfiles profesionales que sí aparecen en Inicio.
    # Así evitamos inconsistencias entre el contador, el perfil
    # y la sección pública de servicios.
    featured_services = []

    featured_professionals = list(
        ProfessionalProfile.objects
        .filter(
            verification_status=(
                ProfessionalProfile
                .VerificationStatus
                .VERIFIED
            ),
            is_public=True,
            services__publication_status=(
                ProfessionalService
                .PublicationStatus
                .PUBLISHED
            ),
        )
        .select_related(
            'user',
            'category',
            'specialty',
        )
        .prefetch_related(
            Prefetch(
                'coverage_communes',
                queryset=(
                    Commune.objects
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
                ),
                to_attr='home_coverage_communes',
            ),
            Prefetch(
                'services',
                queryset=(
                    published_services
                    .order_by(
                        '-published_at',
                        '-created_at',
                    )
                ),
                to_attr='home_published_services',
            ),
        )
        .annotate(
            published_service_count=Count(
                'services',
                filter=Q(
                    services__publication_status=(
                        ProfessionalService
                        .PublicationStatus
                        .PUBLISHED
                    )
                ),
                distinct=True,
            )
        )
        .distinct()
        .order_by(
            '-updated_at',
            '-requested_at',
        )[:3]
    )

    for professional in featured_professionals:

        services = (
            professional
            .home_published_services
        )

        has_in_person = any(
            service.mode
            in (
                ProfessionalService
                .ServiceMode
                .IN_PERSON,
                ProfessionalService
                .ServiceMode
                .HYBRID,
            )
            for service in services
        )

        has_online = any(
            service.mode
            in (
                ProfessionalService
                .ServiceMode
                .ONLINE,
                ProfessionalService
                .ServiceMode
                .HYBRID,
            )
            for service in services
        )

        mode_labels = []

        if has_in_person:
            mode_labels.append(
                'Presencial'
            )

        if has_online:
            mode_labels.append(
                'Online'
            )

        professional.home_modes = (
            ' · '.join(mode_labels)
            if mode_labels
            else 'Modalidad por consultar'
        )

        professional.home_primary_service = (
            services[0]
            if services
            else None
        )

        coverage = (
            professional
            .home_coverage_communes
        )

        if coverage:
            professional.home_location = (
                coverage[0].name
            )

        else:
            service_with_location = next(
                (
                    service
                    for service in services
                    if service.location_commune
                ),
                None,
            )

            if service_with_location:
                professional.home_location = (
                    service_with_location
                    .location_commune
                    .name
                )
            elif has_online:
                professional.home_location = (
                    'Atención online'
                )
            else:
                professional.home_location = (
                    'Cobertura por consultar'
                )

    # =====================================================
    # SERVICIOS DESTACADOS
    # =====================================================
    # Se obtienen desde exactamente los mismos servicios
    # publicados que alimentan las tarjetas de profesionales.
    # Esto garantiza que, si Juan aparece con 1 servicio
    # publicado, ese servicio también aparezca en Inicio.

    seen_service_ids = set()

    for professional in featured_professionals:

        for service in professional.home_published_services:

            if service.id in seen_service_ids:
                continue

            featured_services.append(service)
            seen_service_ids.add(service.id)

            if len(featured_services) >= 3:
                break

        if len(featured_services) >= 3:
            break

    # =====================================================
    # ESPACIOS PUBLICADOS
    # =====================================================

    published_spaces = (
        Space.objects
        .filter(
            publication_status=(
                Space
                .PublicationStatus
                .PUBLISHED
            ),
            provider_profile__verification_status=(
                SpaceProviderProfile
                .VerificationStatus
                .VERIFIED
            ),
            provider_profile__is_public=True,
        )
        .select_related(
            'space_type',
            'commune',
            'commune__region',
            'provider_profile',
            'provider_profile__user',
        )
        .prefetch_related(
            'images',
            'equipments',
            'amenities',
        )
        .order_by(
            '-published_at',
            '-created_at',
        )
    )

    published_space_count = (
        published_spaces.count()
    )

    featured_spaces = list(
        published_spaces[:3]
    )

    for space in featured_spaces:

        images = list(
            space.images.all()
        )

        space.home_cover_image = next(
            (
                image
                for image in images
                if image.is_cover
            ),
            images[0] if images else None,
        )

    return render(
        request,
        'core/home.html',
        {
            'featured_professionals': (
                featured_professionals
            ),
            'verified_professional_count': (
                verified_professional_count
            ),
            'published_service_count': (
                published_service_count
            ),
            'featured_services': (
                featured_services
            ),
            'featured_spaces': (
                featured_spaces
            ),
            'published_space_count': (
                published_space_count
            ),
        }
    )


def explore(request):
    """
    Punto de entrada público para descubrir
    los módulos disponibles de la plataforma.
    """

    return render(
        request,
        'core/explore.html'
    )
