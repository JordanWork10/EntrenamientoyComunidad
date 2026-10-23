from django.db.models import Count, Prefetch, Q
from django.shortcuts import render
from django.utils import timezone

from apps.activities.models import Activity, ActivityRegistration
from apps.locations.models import Commune
from apps.professionals.models import ProfessionalProfile, ProfessionalService
from apps.spaces.models import Space, SpaceProviderProfile


def _published_services():
    """Servicios públicos pertenecientes a profesionales verificados."""
    return (
        ProfessionalService.objects
        .filter(
            publication_status=ProfessionalService.PublicationStatus.PUBLISHED,
            professional_profile__verification_status=(
                ProfessionalProfile.VerificationStatus.VERIFIED
            ),
            professional_profile__is_public=True,
        )
        .select_related(
            'professional_profile',
            'professional_profile__user',
            'professional_profile__specialty',
            'location_commune',
            'location_commune__region',
        )
    )


def _published_spaces():
    """Espacios públicos pertenecientes a proveedores verificados."""
    return (
        Space.objects
        .filter(
            publication_status=Space.PublicationStatus.PUBLISHED,
            provider_profile__verification_status=(
                SpaceProviderProfile.VerificationStatus.VERIFIED
            ),
            provider_profile__is_public=True,
        )
        .select_related(
            'space_type', 'commune', 'commune__region',
            'provider_profile', 'provider_profile__user',
        )
        .prefetch_related('images', 'equipments', 'amenities')
    )


def _upcoming_activities():
    """Solo actividades futuras, publicadas y aptas para mostrarse."""
    local_now = timezone.localtime()
    return (
        Activity.objects
        .filter(status=Activity.Status.PUBLISHED)
        .filter(
            Q(date__gt=local_now.date())
            | Q(date=local_now.date(), start_time__gt=local_now.time())
        )
        .filter(
            Q(activity_type=Activity.ActivityType.COMMUNITY)
            | Q(
                activity_type=Activity.ActivityType.PROFESSIONAL,
                professional_profile__verification_status=(
                    ProfessionalProfile.VerificationStatus.VERIFIED
                ),
                professional_profile__is_public=True,
            )
        )
        .select_related('organizer', 'category', 'commune', 'commune__region')
        .annotate(
            home_registered_count=Count(
                'registrations',
                filter=Q(
                    registrations__status=ActivityRegistration.Status.REGISTERED
                ),
                distinct=True,
            )
        )
    )


def _set_space_cover(spaces):
    """Selecciona portada sin consultas extras por cada espacio."""
    for space in spaces:
        pictures = list(space.images.all())
        space.home_cover_image = next(
            (picture for picture in pictures if picture.is_cover),
            pictures[0] if pictures else None,
        )


def _set_activity_spots(activities):
    for activity in activities:
        activity.home_available_spots = max(
            activity.capacity - activity.home_registered_count, 0
        )


def home(request):
    """Inicio V125, conservado en V126."""
    published_services = _published_services()
    verified_professional_count = (
        published_services.values('professional_profile_id').distinct().count()
    )
    published_service_count = published_services.count()
    featured_services = list(
        published_services.order_by('-published_at', '-created_at')[:3]
    )

    featured_professionals = list(
        ProfessionalProfile.objects
        .filter(
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
            services__publication_status=(
                ProfessionalService.PublicationStatus.PUBLISHED
            ),
        )
        .select_related('user', 'category', 'specialty')
        .prefetch_related(
            Prefetch(
                'coverage_communes',
                queryset=(
                    Commune.objects.filter(is_active=True)
                    .select_related('region').order_by('region__name', 'name')
                ),
                to_attr='home_coverage_communes',
            ),
            Prefetch(
                'services',
                queryset=published_services.order_by('-published_at', '-created_at'),
                to_attr='home_published_services',
            ),
        )
        .annotate(
            published_service_count=Count(
                'services',
                filter=Q(
                    services__publication_status=(
                        ProfessionalService.PublicationStatus.PUBLISHED
                    )
                ),
                distinct=True,
            )
        )
        .distinct().order_by('-updated_at', '-requested_at')[:3]
    )

    for professional in featured_professionals:
        services = professional.home_published_services
        has_in_person = any(
            service.mode in (
                ProfessionalService.ServiceMode.IN_PERSON,
                ProfessionalService.ServiceMode.HYBRID,
            )
            for service in services
        )
        has_online = any(
            service.mode in (
                ProfessionalService.ServiceMode.ONLINE,
                ProfessionalService.ServiceMode.HYBRID,
            )
            for service in services
        )
        modes = []
        if has_in_person:
            modes.append('Presencial')
        if has_online:
            modes.append('Online')
        professional.home_modes = (
            ' · '.join(modes) if modes else 'Modalidad por consultar'
        )
        coverage = professional.home_coverage_communes
        if coverage:
            professional.home_location = coverage[0].name
        else:
            service_with_location = next(
                (service for service in services if service.location_commune), None
            )
            if service_with_location:
                professional.home_location = service_with_location.location_commune.name
            elif has_online:
                professional.home_location = 'Atención online'
            else:
                professional.home_location = 'Cobertura por consultar'

    published_spaces = _published_spaces().order_by('-published_at', '-created_at')
    published_space_count = published_spaces.count()
    featured_spaces = list(published_spaces[:3])
    _set_space_cover(featured_spaces)

    upcoming_activities = _upcoming_activities().order_by('date', 'start_time', 'id')
    published_activity_count = upcoming_activities.count()
    featured_activities = list(upcoming_activities[:3])
    _set_activity_spots(featured_activities)

    return render(request, 'core/home.html', {
        'featured_professionals': featured_professionals,
        'verified_professional_count': verified_professional_count,
        'featured_services': featured_services,
        'published_service_count': published_service_count,
        'featured_spaces': featured_spaces,
        'published_space_count': published_space_count,
        'featured_activities': featured_activities,
        'published_activity_count': published_activity_count,
    })


def explore(request):
    """V126: búsqueda transversal real y contenido de los tres módulos."""
    query = request.GET.get('q', '').strip()[:80]
    module = request.GET.get('module', 'all')
    if module not in ('all', 'professional', 'space', 'activity'):
        module = 'all'

    services = _published_services()
    spaces = _published_spaces()
    activities = _upcoming_activities()

    if query:
        services = services.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(professional_profile__user__first_name__icontains=query)
            | Q(professional_profile__user__last_name__icontains=query)
            | Q(professional_profile__specialty__name__icontains=query)
            | Q(location_commune__name__icontains=query)
        ).distinct()
        spaces = spaces.filter(
            Q(name__icontains=query)
            | Q(space_type__name__icontains=query)
            | Q(commune__name__icontains=query)
        ).distinct()
        activities = activities.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(category__name__icontains=query)
            | Q(commune__name__icontains=query)
            | Q(organizer__first_name__icontains=query)
            | Q(organizer__last_name__icontains=query)
        ).distinct()

    service_count = services.count() if module in ('all', 'professional') else 0
    space_count = spaces.count() if module in ('all', 'space') else 0
    activity_count = activities.count() if module in ('all', 'activity') else 0
    limit = 6 if query else 3

    featured_services = (
        list(services.order_by('-published_at', '-created_at')[:limit])
        if module in ('all', 'professional') else []
    )
    featured_spaces = (
        list(spaces.order_by('-published_at', '-created_at')[:limit])
        if module in ('all', 'space') else []
    )
    _set_space_cover(featured_spaces)
    featured_activities = (
        list(activities.order_by('date', 'start_time', 'id')[:limit])
        if module in ('all', 'activity') else []
    )
    _set_activity_spots(featured_activities)

    # Las imágenes del carrusel son de publicaciones reales, independientes
    # de los filtros de búsqueda. Si faltan, la plantilla muestra gradientes.
    banner_activity = (
        _upcoming_activities().filter(image__isnull=False)
        .exclude(image='').order_by('date', 'start_time').first()
    )
    banner_spaces = list(
        _published_spaces().order_by('-published_at', '-created_at')[:4]
    )
    _set_space_cover(banner_spaces)
    banner_space = next((s for s in banner_spaces if s.home_cover_image), None)
    # V127: la diapositiva Profesional usa la foto real de su perfil,
    # no fotografías de recintos deportivos ni datos del filtro activo.
    banner_professional = (
        _published_services()
        .order_by('-published_at', '-created_at')
        .first()
    )

    return render(request, 'core/explore.html', {
        'query': query,
        'selected_module': module,
        'has_search': bool(query or module != 'all'),
        'service_count': service_count,
        'space_count': space_count,
        'activity_count': activity_count,
        'result_count': service_count + space_count + activity_count,
        'featured_services': featured_services,
        'featured_spaces': featured_spaces,
        'featured_activities': featured_activities,
        'banner_activity': banner_activity,
        'banner_space': banner_space,
        'banner_professional': banner_professional,
    })
