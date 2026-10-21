import calendar as calendar_module
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.locations.models import Commune
from apps.bookings.models import Booking, BookingHistory
from apps.bookings.services import expire_pending_bookings
from apps.bookings.incident_notifications import get_session_incident_updates

from .forms import (
    ProfessionalCredentialForm,
    ProfessionalProfileRequestForm,
    ProfessionalServiceAvailabilityForm,
    ProfessionalServiceForm,
)
from .models import (
    ProfessionalCredential,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalServiceAvailabilityHistory,
    ProfessionalSpecialty,
)


@login_required(login_url='accounts:login')
def request_professional_profile(request):
    """
    Permite que un miembro solicite habilitar
    su Perfil Profesional junto con una primera
    acreditación obligatoria.
    """

    # =====================================================
    # VALIDAR QUE LA CUENTA BASE ESTÉ COMPLETA
    # =====================================================

    member_profile = getattr(
        request.user,
        'member_profile',
        None
    )

    user_profile_complete = all([
        request.user.first_name,
        request.user.last_name,
        request.user.rut,
        request.user.phone,
        request.user.birth_date,
        request.user.commune,
    ])

    if (
        member_profile is None
        or not user_profile_complete
        or not request.user.terms_accepted
        or not request.user.privacy_accepted
    ):
        return redirect(
            'accounts:dashboard'
        )

    # =====================================================
    # EVITAR SOLICITUDES DUPLICADAS
    # =====================================================

    existing_profile = (
        ProfessionalProfile.objects
        .filter(
            user=request.user
        )
        .first()
    )

    if existing_profile:

        return redirect(
            'accounts:dashboard'
        )

    # =====================================================
    # PROCESAR SOLICITUD
    # =====================================================

    if request.method == 'POST':

        form = ProfessionalProfileRequestForm(
            request.POST
        )

        credential_form = ProfessionalCredentialForm(
            request.POST,
            request.FILES,
        )

        if (
            form.is_valid()
            and credential_form.is_valid()
        ):

            with transaction.atomic():

                # =========================================
                # CREAR PERFIL PROFESIONAL
                # =========================================

                professional_profile = (
                    form.save(
                        commit=False
                    )
                )

                professional_profile.user = (
                    request.user
                )

                professional_profile.verification_status = (
                    ProfessionalProfile
                    .VerificationStatus
                    .PENDING
                )

                professional_profile.is_public = False

                professional_profile.save()

                form.save_m2m()

                # =========================================
                # CREAR PRIMERA ACREDITACIÓN
                # =========================================

                credential = (
                    credential_form.save(
                        commit=False
                    )
                )

                credential.professional_profile = (
                    professional_profile
                )

                credential.review_status = (
                    ProfessionalCredential
                    .ReviewStatus
                    .PENDING
                )

                credential.save()

            return redirect(
                'accounts:dashboard'
            )

    else:

        form = ProfessionalProfileRequestForm()

        credential_form = (
            ProfessionalCredentialForm()
        )

    return render(
        request,
        'professionals/request_profile.html',
        {
            'form': form,
            'credential_form': credential_form,
        }
    )


@login_required(login_url='accounts:login')
def specialties_by_category(request):
    """
    Devuelve las especialidades activas
    pertenecientes a una categoría.
    """

    category_id = request.GET.get(
        'category'
    )

    if not category_id:

        return JsonResponse(
            {
                'specialties': [],
            }
        )

    specialties = (
        ProfessionalSpecialty.objects
        .filter(
            category_id=category_id,
            is_active=True,
        )
        .order_by(
            'display_order',
            'name',
        )
        .values(
            'id',
            'name',
        )
    )

    return JsonResponse(
        {
            'specialties': list(
                specialties
            ),
        }
    )


@login_required(login_url='accounts:login')
def coverage_communes_by_region(request):
    """
    Devuelve las comunas activas correspondientes
    a la región seleccionada para cobertura profesional.
    """

    region_id = request.GET.get(
        'region'
    )

    if not region_id:

        return JsonResponse(
            {
                'communes': [],
            }
        )

    communes = (
        Commune.objects
        .filter(
            region_id=region_id,
            is_active=True,
        )
        .order_by(
            'name'
        )
        .values(
            'id',
            'name',
        )
    )

    return JsonResponse(
        {
            'communes': list(
                communes
            ),
        }
    )


@login_required(login_url='accounts:login')
def professional_dashboard(request):
    """
    Centro de gestión exclusivo para usuarios
    con un Perfil Profesional verificado.
    """

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    # =====================================================
    # VALIDAR PERFIL PROFESIONAL
    # =====================================================

    if professional_profile is None:

        return redirect(
            'accounts:dashboard'
        )

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):

        return redirect(
            'accounts:dashboard'
        )

    # Las solicitudes cuyo horario ya comenzó dejan
    # automáticamente de estar Pendientes.
    expire_pending_bookings(
        professional_profile=professional_profile
    )

    # =====================================================
    # ACREDITACIONES
    # =====================================================

    credentials = (
        professional_profile
        .credentials
        .order_by(
            '-created_at'
        )
    )

    # =====================================================
    # COBERTURA
    # =====================================================

    coverage_communes = (
        professional_profile
        .coverage_communes
        .select_related(
            'region'
        )
        .order_by(
            'region__name',
            'name',
        )
    )

    # =====================================================
    # SERVICIOS PROFESIONALES
    # =====================================================

    services = (
        professional_profile
        .services
        .order_by(
            '-created_at'
        )
    )

    # =====================================================
    # AGENDA PROFESIONAL PRÓXIMA
    # =====================================================

    today = timezone.localdate()

    upcoming_professional_queryset = (
        Booking.objects
        .filter(
            professional_profile=professional_profile,
            session_date__gte=today,
            status__in=[
                Booking.Status.PENDING,
                Booking.Status.CONFIRMED,
            ],
        )
        .select_related(
            'booked_by',
            'service',
        )
        .order_by(
            'session_date',
            'start_time',
        )
    )

    upcoming_professional_total = (
        upcoming_professional_queryset.count()
    )

    pending_professional_count = (
        upcoming_professional_queryset
        .filter(
            status=Booking.Status.PENDING
        )
        .count()
    )

    confirmed_professional_count = (
        upcoming_professional_queryset
        .filter(
            status=Booking.Status.CONFIRMED
        )
        .count()
    )

    # En el panel mostramos solo las tres más próximas.
    # El listado completo sigue disponible en Reservas recibidas.
    upcoming_professional_bookings = list(
        upcoming_professional_queryset[:3]
    )

    # =====================================================
    # NOVEDADES PROFESIONALES
    # =====================================================
    #
    # Las novedades de reservas se construyen desde BookingHistory.
    # Las incidencias se consultan desde los modelos de V123,
    # sin crear otras fuentes de verdad ni nuevas migraciones.
    #
    # Solo mostramos cambios originados por el Miembro:
    # - solicitud nueva que todavía sigue Pendiente;
    # - cancelación realizada por el Miembro.
    #
    # Los cambios hechos por el propio Profesional no se muestran
    # como novedad para él mismo.

    professional_history_events = (
        BookingHistory.objects
        .filter(
            booking__professional_profile=professional_profile,
            action__in=[
                BookingHistory.Action.CREATED,
                BookingHistory.Action.CANCELLED,
            ],
            changed_by__isnull=False,
        )
        .exclude(
            changed_by=request.user
        )
        .select_related(
            'booking',
            'booking__booked_by',
            'booking__service',
            'changed_by',
        )
        .order_by(
            '-created_at',
            '-id',
        )[:40]
    )

    booking_updates = []
    seen_booking_ids = set()

    for event in professional_history_events:

        booking = event.booking

        # Una sola novedad vigente por reserva.
        if booking.id in seen_booking_ids:
            continue

        member = booking.booked_by
        member_name = (
            member.get_full_name()
            or member.email
        )

        if event.action == BookingHistory.Action.CREATED:

            # Si la solicitud ya fue confirmada/cancelada, no mostramos
            # una tarjeta antigua de "nueva solicitud".
            if booking.status != Booking.Status.PENDING:
                continue

            kind = 'request'
            title = f'{member_name} envió una nueva solicitud'
            summary = (
                f'Quiere reservar {booking.service_name_snapshot}.'
            )
            reason = ''

        elif event.action == BookingHistory.Action.CANCELLED:

            # Aquí solo llegan cancelaciones realizadas por el Miembro
            # porque los cambios del propio Profesional fueron excluidos.
            if booking.status != Booking.Status.CANCELLED:
                continue

            previous_status = (
                (event.previous_data or {})
                .get('status')
            )

            kind = 'cancelled'

            if previous_status == Booking.Status.PENDING:
                title = f'{member_name} canceló su solicitud'
                summary = (
                    f'La solicitud para {booking.service_name_snapshot} '
                    'ya no requiere respuesta.'
                )
            else:
                title = f'{member_name} canceló su reserva'
                summary = (
                    f'La sesión de {booking.service_name_snapshot} '
                    'ya no se realizará.'
                )

            reason = (
                event.reason
                or booking.cancellation_reason
                or ''
            )

        else:
            continue

        booking_updates.append(
            {
                'key': f'booking-history-{event.id}',
                'kind': kind,
                'title': title,
                'summary': summary,
                'reason': reason,
                'booking': booking,
                'member': member,
                'created_at': event.created_at,
            }
        )

        seen_booking_ids.add(booking.id)

    # =====================================================
    # V123 - INTEGRAR NOVEDADES DE INCIDENCIAS
    # =====================================================
    # No reemplaza las novedades antiguas. La función de bookings
    # filtra las incidencias del Profesional autenticado y devuelve
    # una novedad vigente por incidencia con clave propia y enlace.

    incident_updates = get_session_incident_updates(
        request.user,
        'professional',
        limit=30,
    )

    # Reservas e incidencias se ordenan juntas por fecha real.
    # Conservamos el límite original de seis tarjetas del panel.
    professional_updates = booking_updates + incident_updates
    professional_updates.sort(
        key=lambda update: (update['created_at'], update['key']),
        reverse=True,
    )
    professional_updates = professional_updates[:6]

    return render(
        request,
        'professionals/dashboard.html',
        {
            'professional_profile': (
                professional_profile
            ),

            'credentials': (
                credentials
            ),

            'coverage_communes': (
                coverage_communes
            ),

            'services': (
                services
            ),

            'upcoming_professional_bookings': (
                upcoming_professional_bookings
            ),

            'upcoming_professional_total': (
                upcoming_professional_total
            ),

            'pending_professional_count': (
                pending_professional_count
            ),

            'confirmed_professional_count': (
                confirmed_professional_count
            ),

            'professional_updates': (
                professional_updates
            ),
        }
    )


@login_required(login_url='accounts:login')
def create_professional_service(request):
    """
    Permite que un Profesional verificado y público
    cree un nuevo servicio.

    El Perfil Profesional propietario se determina
    automáticamente desde la cuenta autenticada.

    Todo servicio nuevo comienza como Borrador.
    """

    # =====================================================
    # OBTENER PERFIL PROFESIONAL
    # =====================================================

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    # =====================================================
    # VALIDAR EXISTENCIA
    # =====================================================

    if professional_profile is None:

        return redirect(
            'accounts:dashboard'
        )

    # =====================================================
    # VALIDAR VERIFICACIÓN
    # =====================================================

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):

        return redirect(
            'accounts:dashboard'
        )

    # =====================================================
    # VALIDAR PERFIL PÚBLICO
    # =====================================================

    if not professional_profile.is_public:

        return redirect(
            'professionals:dashboard'
        )

    # =====================================================
    # PROCESAR FORMULARIO
    # =====================================================

    if request.method == 'POST':

        form = ProfessionalServiceForm(
            request.POST,
            professional_profile=(
                professional_profile
            ),
        )

        if form.is_valid():

            with transaction.atomic():

                service = form.save(
                    commit=False
                )

                # -----------------------------------------
                # PROPIETARIO AUTOMÁTICO
                # -----------------------------------------

                service.professional_profile = (
                    professional_profile
                )

                # -----------------------------------------
                # ESTADO INICIAL SEGURO
                # -----------------------------------------

                service.publication_status = (
                    ProfessionalService
                    .PublicationStatus
                    .DRAFT
                )

                service.save()

            return redirect(
                'professionals:dashboard'
            )

    else:

        form = ProfessionalServiceForm(
            professional_profile=(
                professional_profile
            )
        )

    # =====================================================
    # MOSTRAR FORMULARIO
    # =====================================================

    return render(
        request,
        'professionals/create_service.html',
        {
            'form': form,

            'professional_profile': (
                professional_profile
            ),
        }
    )


@login_required(login_url='accounts:login')
def edit_professional_service(request, service_id):
    """
    Permite que un Profesional verificado edite
    únicamente uno de sus propios servicios.

    El propietario del servicio nunca se selecciona
    desde el formulario: se valida contra la cuenta
    autenticada.
    """

    # =====================================================
    # OBTENER PERFIL PROFESIONAL
    # =====================================================

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    # =====================================================
    # VALIDAR EXISTENCIA DEL PERFIL
    # =====================================================

    if professional_profile is None:

        return redirect(
            'accounts:dashboard'
        )

    # =====================================================
    # VALIDAR VERIFICACIÓN
    # =====================================================

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):

        return redirect(
            'accounts:dashboard'
        )

    # =====================================================
    # VALIDAR PERFIL PÚBLICO
    # =====================================================

    if not professional_profile.is_public:

        return redirect(
            'professionals:dashboard'
        )

    # =====================================================
    # OBTENER SOLO UN SERVICIO PROPIO
    # =====================================================

    service = get_object_or_404(
        ProfessionalService,
        pk=service_id,
        professional_profile=professional_profile,
    )

    # =====================================================
    # PROCESAR FORMULARIO
    # =====================================================

    if request.method == 'POST':

        form = ProfessionalServiceForm(
            request.POST,
            instance=service,
            professional_profile=(
                professional_profile
            ),
        )

        if form.is_valid():

            with transaction.atomic():

                updated_service = form.save(
                    commit=False
                )

                # El propietario se mantiene forzado
                # desde la sesión autenticada.
                updated_service.professional_profile = (
                    professional_profile
                )

                updated_service.save()

            messages.success(
                request,
                (
                    f'Los cambios de "{updated_service.name}" '
                    'fueron guardados correctamente.'
                ),
                extra_tags='service-updated',
            )

            return redirect(
                'professionals:dashboard'
            )

    else:

        form = ProfessionalServiceForm(
            instance=service,
            professional_profile=(
                professional_profile
            ),
        )

    # =====================================================
    # MOSTRAR FORMULARIO
    # =====================================================

    return render(
        request,
        'professionals/edit_service.html',
        {
            'form': form,
            'service': service,
            'professional_profile': (
                professional_profile
            ),
        }
    )


@login_required(login_url='accounts:login')
@require_POST
def publish_professional_service(request, service_id):
    """
    Publica o vuelve a publicar un servicio propio.

    Solo un Profesional verificado, con perfil público,
    puede publicar servicios. El cambio de estado se
    realiza únicamente mediante POST.
    """

    # =====================================================
    # OBTENER PERFIL PROFESIONAL
    # =====================================================

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    # =====================================================
    # VALIDAR PERFIL PROFESIONAL
    # =====================================================

    if professional_profile is None:

        return redirect(
            'accounts:dashboard'
        )

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):

        return redirect(
            'accounts:dashboard'
        )

    if not professional_profile.is_public:

        return redirect(
            'professionals:dashboard'
        )

    # =====================================================
    # OBTENER SOLO UN SERVICIO PROPIO
    # =====================================================

    service = get_object_or_404(
        ProfessionalService,
        pk=service_id,
        professional_profile=professional_profile,
    )

    # =====================================================
    # PUBLICAR / VOLVER A PUBLICAR
    # =====================================================

    if service.publication_status in (
        ProfessionalService
        .PublicationStatus
        .DRAFT,

        ProfessionalService
        .PublicationStatus
        .PAUSED,
    ):

        service.publication_status = (
            ProfessionalService
            .PublicationStatus
            .PUBLISHED
        )

        service.save(
            update_fields=[
                'publication_status',
                'updated_at',
            ]
        )

    return redirect(
        'professionals:dashboard'
    )


@login_required(login_url='accounts:login')
@require_POST
def pause_professional_service(request, service_id):
    """
    Pausa un servicio publicado perteneciente
    al Profesional autenticado.

    El cambio de estado se realiza únicamente
    mediante POST.
    """

    # =====================================================
    # OBTENER PERFIL PROFESIONAL
    # =====================================================

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    # =====================================================
    # VALIDAR PERFIL PROFESIONAL
    # =====================================================

    if professional_profile is None:

        return redirect(
            'accounts:dashboard'
        )

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):

        return redirect(
            'accounts:dashboard'
        )

    # =====================================================
    # OBTENER SOLO UN SERVICIO PROPIO
    # =====================================================

    service = get_object_or_404(
        ProfessionalService,
        pk=service_id,
        professional_profile=professional_profile,
    )

    # =====================================================
    # PAUSAR
    # =====================================================

    if (
        service.publication_status
        == ProfessionalService
        .PublicationStatus
        .PUBLISHED
    ):

        service.publication_status = (
            ProfessionalService
            .PublicationStatus
            .PAUSED
        )

        service.save(
            update_fields=[
                'publication_status',
                'updated_at',
            ]
        )

    return redirect(
        'professionals:dashboard'
    )


@login_required(login_url='accounts:login')
def create_service_availability(request, service_id):
    """
    Crea una disponibilidad para una fecha concreta.

    La interfaz solicita una fecha exacta y una hora de inicio.
    La hora de término se calcula según la duración del servicio.

    Para mantener compatibilidad con el modelo actual:
    - weekday se deriva de la fecha;
    - valid_from y valid_until guardan la misma fecha.

    Así el bloque aplica únicamente al día elegido.
    """

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    if professional_profile is None:
        return redirect(
            'accounts:dashboard'
        )

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):
        return redirect(
            'accounts:dashboard'
        )

    if not professional_profile.is_public:
        return redirect(
            'professionals:dashboard'
        )

    service = get_object_or_404(
        ProfessionalService,
        pk=service_id,
        professional_profile=professional_profile,
    )

    availability_date_value = ''
    automatic_end_time_value = ''
    availability_date_error = ''
    automatic_end_time_error = ''

    if request.method == 'POST':

        availability_date_value = (
            request.POST.get(
                'availability_date',
                ''
            )
            .strip()
        )

        start_time_value = (
            request.POST.get(
                'start_time',
                ''
            )
            .strip()
        )

        selected_date = parse_date(
            availability_date_value
        )

        if selected_date is None:

            availability_date_error = (
                'Selecciona una fecha válida.'
            )

        elif selected_date < timezone.localdate():

            availability_date_error = (
                'La disponibilidad no puede crearse '
                'en una fecha anterior a hoy.'
            )

        if start_time_value:

            try:

                start_hour, start_minute = [
                    int(part)
                    for part in start_time_value.split(':')
                ]

                start_total_minutes = (
                    start_hour * 60
                    + start_minute
                )

                end_total_minutes = (
                    start_total_minutes
                    + service.duration_minutes
                )

                if end_total_minutes >= (24 * 60):

                    automatic_end_time_error = (
                        'Esta hora de inicio no permite completar '
                        'la sesión antes de terminar el día.'
                    )

                else:

                    end_hour = (
                        end_total_minutes // 60
                    )

                    end_minute = (
                        end_total_minutes % 60
                    )

                    automatic_end_time_value = (
                        f'{end_hour:02d}:'
                        f'{end_minute:02d}'
                    )

            except (
                TypeError,
                ValueError,
            ):

                automatic_end_time_error = (
                    'Selecciona una hora de inicio válida.'
                )

        form_data = request.POST.copy()

        if selected_date is not None:

            form_data['weekday'] = str(
                selected_date.weekday()
            )

            form_data['valid_from'] = (
                selected_date.isoformat()
            )

            form_data['valid_until'] = (
                selected_date.isoformat()
            )

        if automatic_end_time_value:

            form_data['end_time'] = (
                automatic_end_time_value
            )

        form = ProfessionalServiceAvailabilityForm(
            form_data,
            service=service,
        )

        if automatic_end_time_value:

            current_end_choices = list(
                form.fields[
                    'end_time'
                ].choices
            )

            valid_end_values = {
                value
                for value, _label
                in current_end_choices
            }

            if (
                automatic_end_time_value
                not in valid_end_values
            ):

                current_end_choices.append(
                    (
                        automatic_end_time_value,
                        automatic_end_time_value,
                    )
                )

                form.fields[
                    'end_time'
                ].choices = (
                    current_end_choices
                )

        can_validate_form = (
            not availability_date_error
            and not automatic_end_time_error
        )

        if (
            can_validate_form
            and form.is_valid()
        ):

            with transaction.atomic():

                availability = form.save(
                    commit=False
                )

                availability.service = service
                availability.is_active = True
                availability.save()

                ProfessionalServiceAvailabilityHistory.objects.create(
                    availability=availability,
                    action=(
                        ProfessionalServiceAvailabilityHistory
                        .Action
                        .CREATED
                    ),
                    previous_data={},
                    new_data=(
                        availability.audit_snapshot()
                    ),
                    changed_by=request.user,
                    reason=(
                        'Disponibilidad para fecha concreta '
                        'creada desde el Centro Profesional.'
                    ),
                )

            messages.success(
                request,
                (
                    'Disponibilidad publicada para '
                    f'{selected_date.strftime("%d/%m/%Y")}, '
                    f'de {availability.start_time.strftime("%H:%M")} '
                    f'a {availability.end_time.strftime("%H:%M")}.'
                ),
                extra_tags='availability-created',
            )

            return redirect(
                'professionals:dashboard'
            )

    else:

        requested_date_value = (
            request.GET.get(
                'date',
                ''
            )
            .strip()
        )

        requested_date = parse_date(
            requested_date_value
        )

        today = timezone.localdate()

        if (
            requested_date is not None
            and requested_date >= today
        ):
            availability_date_value = (
                requested_date.isoformat()
            )
        else:
            availability_date_value = (
                today.isoformat()
            )

        form = ProfessionalServiceAvailabilityForm(
            service=service,
        )

    return render(
        request,
        'professionals/create_availability.html',
        {
            'form': form,
            'service': service,
            'professional_profile': (
                professional_profile
            ),
            'availability_date_value': (
                availability_date_value
            ),
            'availability_date_error': (
                availability_date_error
            ),
            'automatic_end_time_value': (
                automatic_end_time_value
            ),
            'automatic_end_time_error': (
                automatic_end_time_error
            ),
            'today_iso': (
                timezone.localdate().isoformat()
            ),
            'current_year': (
                timezone.localdate().year
            ),
        }
    )


@login_required(login_url='accounts:login')
def edit_service_availability(
    request,
    availability_id
):
    """
    Permite editar una disponibilidad perteneciente
    a un servicio propio del Profesional autenticado.

    Cada modificación se registra en el historial
    conservando estado anterior y estado nuevo.
    """

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    if professional_profile is None:
        return redirect(
            'accounts:dashboard'
        )

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):
        return redirect(
            'accounts:dashboard'
        )

    if not professional_profile.is_public:
        return redirect(
            'professionals:dashboard'
        )

    availability = get_object_or_404(
        ProfessionalServiceAvailability
        .objects
        .select_related(
            'service',
            'service__professional_profile',
        ),
        pk=availability_id,
        service__professional_profile=professional_profile,
    )

    service = availability.service

    if request.method == 'POST':

        previous_data = (
            availability.audit_snapshot()
        )

        form = ProfessionalServiceAvailabilityForm(
            request.POST,
            instance=availability,
            service=service,
        )

        if form.is_valid():

            with transaction.atomic():

                updated_availability = form.save(
                    commit=False
                )

                updated_availability.service = service

                # El estado activo/inactivo no se modifica
                # desde el formulario de edición.
                updated_availability.is_active = (
                    previous_data.get(
                        'is_active',
                        True
                    )
                )

                updated_availability.save()

                new_data = (
                    updated_availability
                    .audit_snapshot()
                )

                if previous_data != new_data:

                    ProfessionalServiceAvailabilityHistory.objects.create(
                        availability=updated_availability,
                        action=(
                            ProfessionalServiceAvailabilityHistory
                            .Action
                            .UPDATED
                        ),
                        previous_data=previous_data,
                        new_data=new_data,
                        changed_by=request.user,
                        reason=(
                            'Disponibilidad editada desde '
                            'el Centro Profesional.'
                        ),
                    )

            return redirect(
                'professionals:dashboard'
            )

    else:

        form = ProfessionalServiceAvailabilityForm(
            instance=availability,
            service=service,
        )

    return render(
        request,
        'professionals/edit_availability.html',
        {
            'form': form,
            'service': service,
            'availability': availability,
            'professional_profile': (
                professional_profile
            ),
        }
    )


@login_required(login_url='accounts:login')
@require_POST
def deactivate_service_availability(
    request,
    availability_id
):
    """
    Desactiva una disponibilidad sin eliminarla.
    El cambio queda registrado en el historial.
    """

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    if professional_profile is None:
        return redirect(
            'accounts:dashboard'
        )

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):
        return redirect(
            'accounts:dashboard'
        )

    availability = get_object_or_404(
        ProfessionalServiceAvailability,
        pk=availability_id,
        service__professional_profile=professional_profile,
    )

    if availability.is_active:

        previous_data = (
            availability.audit_snapshot()
        )

        with transaction.atomic():

            availability.is_active = False

            availability.save(
                update_fields=[
                    'is_active',
                    'updated_at',
                ]
            )

            ProfessionalServiceAvailabilityHistory.objects.create(
                availability=availability,
                action=(
                    ProfessionalServiceAvailabilityHistory
                    .Action
                    .DEACTIVATED
                ),
                previous_data=previous_data,
                new_data=(
                    availability.audit_snapshot()
                ),
                changed_by=request.user,
                reason=(
                    'Disponibilidad desactivada desde '
                    'el Centro Profesional.'
                ),
            )

    return redirect(
        'professionals:dashboard'
    )


@login_required(login_url='accounts:login')
@require_POST
def activate_service_availability(
    request,
    availability_id
):
    """
    Reactiva una disponibilidad previamente desactivada.

    Antes de guardar se vuelven a ejecutar las validaciones
    del modelo, incluyendo la detección de solapamientos.
    """

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    if professional_profile is None:
        return redirect(
            'accounts:dashboard'
        )

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):
        return redirect(
            'accounts:dashboard'
        )

    if not professional_profile.is_public:
        return redirect(
            'professionals:dashboard'
        )

    availability = get_object_or_404(
        ProfessionalServiceAvailability,
        pk=availability_id,
        service__professional_profile=professional_profile,
    )

    if not availability.is_active:

        previous_data = (
            availability.audit_snapshot()
        )

        availability.is_active = True

        try:

            with transaction.atomic():

                availability.save(
                    update_fields=[
                        'is_active',
                        'updated_at',
                    ]
                )

                ProfessionalServiceAvailabilityHistory.objects.create(
                    availability=availability,
                    action=(
                        ProfessionalServiceAvailabilityHistory
                        .Action
                        .ACTIVATED
                    ),
                    previous_data=previous_data,
                    new_data=(
                        availability.audit_snapshot()
                    ),
                    changed_by=request.user,
                    reason=(
                        'Disponibilidad reactivada desde '
                        'el Centro Profesional.'
                    ),
                )

        except ValidationError:

            # La base de datos permanece sin cambios porque
            # la validación ocurre antes de guardar.
            messages.error(
                request,
                (
                    'No fue posible activar la disponibilidad. '
                    'Revisa que no se superponga con otro '
                    'horario activo del mismo servicio.'
                )
            )

    return redirect(
        'professionals:dashboard'
    )


@login_required(login_url='accounts:login')
def service_availability_history(
    request,
    availability_id
):
    """
    Muestra el historial completo de una disponibilidad
    perteneciente a un servicio propio del Profesional
    autenticado.

    La vista es de solo lectura y permite filtrar por:
    - texto libre;
    - tipo de cambio;
    - períodos rápidos;
    - rango de fechas personalizado.
    """

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    if professional_profile is None:

        return redirect(
            'accounts:dashboard'
        )

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):

        return redirect(
            'accounts:dashboard'
        )

    availability = get_object_or_404(
        ProfessionalServiceAvailability
        .objects
        .select_related(
            'service',
            'service__professional_profile',
        ),
        pk=availability_id,
        service__professional_profile=professional_profile,
    )

    history_entries = (
        availability
        .history
        .select_related(
            'changed_by'
        )
        .order_by(
            '-created_at'
        )
    )

    # =====================================================
    # FILTROS DEL HISTORIAL
    # =====================================================

    search_value = (
        request.GET.get(
            'q',
            ''
        )
        .strip()
    )

    action_value = (
        request.GET.get(
            'action',
            ''
        )
        .strip()
    )

    period_value = (
        request.GET.get(
            'period',
            'all'
        )
        .strip()
    )

    allowed_periods = {
        'all',
        'today',
        '7d',
        'month',
        'custom',
    }

    if period_value not in allowed_periods:
        period_value = 'all'

    date_from_value = (
        request.GET.get(
            'date_from',
            ''
        )
        .strip()
    )

    date_to_value = (
        request.GET.get(
            'date_to',
            ''
        )
        .strip()
    )

    # -----------------------------------------------------
    # BÚSQUEDA LIBRE
    # -----------------------------------------------------

    if search_value:

        search_filter = (
            Q(reason__icontains=search_value)
            | Q(
                changed_by__first_name__icontains=search_value
            )
            | Q(
                changed_by__last_name__icontains=search_value
            )
            | Q(
                changed_by__email__icontains=search_value
            )
        )

        normalized_search = (
            search_value
            .lower()
            .strip()
        )

        action_matches = []

        for action_key, action_label in (
            ProfessionalServiceAvailabilityHistory
            .Action
            .choices
        ):

            if (
                normalized_search
                in action_label.lower()
                or action_label.lower()
                in normalized_search
            ):
                action_matches.append(
                    action_key
                )

        if action_matches:

            search_filter |= Q(
                action__in=action_matches
            )

        if (
            'registro histórico' in normalized_search
            or 'registro historico' in normalized_search
            or 'inicial' in normalized_search
        ):

            search_filter |= Q(
                changed_by__isnull=True
            )

        history_entries = (
            history_entries
            .filter(
                search_filter
            )
        )

    # -----------------------------------------------------
    # TIPO DE CAMBIO
    # -----------------------------------------------------

    valid_actions = {
        choice[0]
        for choice in (
            ProfessionalServiceAvailabilityHistory
            .Action
            .choices
        )
    }

    if action_value in valid_actions:

        history_entries = (
            history_entries
            .filter(
                action=action_value
            )
        )

    else:

        action_value = ''

    # -----------------------------------------------------
    # PERÍODO
    # -----------------------------------------------------

    today = timezone.localdate()

    filter_error = ''

    if period_value == 'today':

        history_entries = (
            history_entries
            .filter(
                created_at__date=today
            )
        )

    elif period_value == '7d':

        date_from = (
            today - timedelta(days=6)
        )

        history_entries = (
            history_entries
            .filter(
                created_at__date__gte=date_from,
                created_at__date__lte=today,
            )
        )

    elif period_value == 'month':

        first_day = today.replace(
            day=1
        )

        history_entries = (
            history_entries
            .filter(
                created_at__date__gte=first_day,
                created_at__date__lte=today,
            )
        )

    elif period_value == 'custom':

        date_from = (
            parse_date(date_from_value)
            if date_from_value
            else None
        )

        date_to = (
            parse_date(date_to_value)
            if date_to_value
            else None
        )

        if (
            date_from
            and date_to
            and date_from > date_to
        ):

            filter_error = (
                'La fecha inicial no puede ser posterior '
                'a la fecha final.'
            )

        else:

            if date_from:

                history_entries = (
                    history_entries
                    .filter(
                        created_at__date__gte=date_from
                    )
                )

            if date_to:

                history_entries = (
                    history_entries
                    .filter(
                        created_at__date__lte=date_to
                    )
                )

    # =====================================================
    # INFORMACIÓN PARA LA INTERFAZ
    # =====================================================

    period_labels = {
        'all': 'Todo el historial',
        'today': 'Hoy',
        '7d': 'Últimos 7 días',
        'month': 'Este mes',
        'custom': 'Rango personalizado',
    }

    action_labels = dict(
        ProfessionalServiceAvailabilityHistory
        .Action
        .choices
    )

    result_count = (
        history_entries.count()
        if not filter_error
        else 0
    )

    has_active_filters = any([
        search_value,
        action_value,
        period_value != 'all',
    ])

    return render(
        request,
        'professionals/availability_history.html',
        {
            'professional_profile': (
                professional_profile
            ),
            'service': (
                availability.service
            ),
            'availability': (
                availability
            ),
            'history_entries': (
                history_entries
                if not filter_error
                else history_entries.none()
            ),
            'search_value': (
                search_value
            ),
            'action_value': (
                action_value
            ),
            'action_choices': (
                ProfessionalServiceAvailabilityHistory
                .Action
                .choices
            ),
            'active_action_label': (
                action_labels.get(
                    action_value,
                    ''
                )
            ),
            'period_value': (
                period_value
            ),
            'active_period_label': (
                period_labels[
                    period_value
                ]
            ),
            'date_from_value': (
                date_from_value
            ),
            'date_to_value': (
                date_to_value
            ),
            'result_count': (
                result_count
            ),
            'has_active_filters': (
                has_active_filters
            ),
            'filter_error': (
                filter_error
            ),
        }
    )


@login_required(login_url='accounts:login')
def service_reservable_slots_preview(
    request,
    service_id
):
    """
    Permite al Profesional revisar las sesiones que el sistema
    genera dinámicamente para uno de sus propios servicios.

    Esta vista es únicamente de consulta:
    - no crea sesiones en PostgreSQL;
    - no crea reservas;
    - utiliza las disponibilidades recurrentes existentes;
    - respeta exactamente duration_minutes del servicio.
    """

    # =====================================================
    # PERFIL PROFESIONAL
    # =====================================================

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    if professional_profile is None:

        return redirect(
            'accounts:dashboard'
        )

    if (
        professional_profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
    ):

        return redirect(
            'accounts:dashboard'
        )

    # =====================================================
    # SERVICIO PROPIO
    # =====================================================

    service = get_object_or_404(
        ProfessionalService,
        pk=service_id,
        professional_profile=professional_profile,
    )

    # =====================================================
    # FECHA CONSULTADA
    # =====================================================

    selected_date_value = (
        request.GET.get(
            'date',
            ''
        )
        .strip()
    )

    selected_date = (
        parse_date(
            selected_date_value
        )
        if selected_date_value
        else None
    )

    slots = []

    date_error = ''

    if selected_date_value and selected_date is None:

        date_error = (
            'La fecha seleccionada no es válida.'
        )

    elif selected_date:

        if (
            selected_date
            < timezone.localdate()
        ):

            date_error = (
                'Selecciona una fecha de hoy en adelante.'
            )

        else:

            slots = (
                service
                .generate_reservable_slots_for_date(
                    selected_date
                )
            )

    # =====================================================
    # CONTEXTO DE LA FECHA
    # =====================================================

    weekday_labels = [
        'Lunes',
        'Martes',
        'Miércoles',
        'Jueves',
        'Viernes',
        'Sábado',
        'Domingo',
    ]

    weekday_label = ''

    if selected_date:

        weekday_label = (
            weekday_labels[
                selected_date.weekday()
            ]
        )

    # =====================================================
    # FECHAS RÁPIDAS
    # =====================================================

    today = timezone.localdate()

    quick_dates = []

    for day_offset in range(7):

        quick_date = (
            today
            + timedelta(
                days=day_offset
            )
        )

        if day_offset == 0:
            quick_label = 'Hoy'

        elif day_offset == 1:
            quick_label = 'Mañana'

        else:
            quick_label = (
                weekday_labels[
                    quick_date.weekday()
                ]
            )

        quick_dates.append(
            {
                'value': (
                    quick_date.isoformat()
                ),
                'label': (
                    quick_label
                ),
                'date_label': (
                    quick_date.strftime(
                        '%d/%m'
                    )
                ),
                'is_selected': (
                    selected_date
                    == quick_date
                ),
            }
        )

    return render(
        request,
        'professionals/service_slots_preview.html',
        {
            'professional_profile': (
                professional_profile
            ),
            'service': (
                service
            ),
            'selected_date': (
                selected_date
            ),
            'selected_date_value': (
                selected_date_value
            ),
            'weekday_label': (
                weekday_label
            ),
            'slots': (
                slots
            ),
            'slot_count': (
                len(slots)
            ),
            'date_error': (
                date_error
            ),
            'today_value': (
                today.isoformat()
            ),
            'quick_dates': (
                quick_dates
            ),
            'is_service_published': (
                service.publication_status
                == ProfessionalService
                .PublicationStatus
                .PUBLISHED
            ),
        }
    )

@login_required(login_url='accounts:login')
def professional_calendar(request):
    """
    Agenda mensual del Profesional autenticado.

    Reúne en un mismo calendario:
    - disponibilidades activas de sus servicios;
    - solicitudes pendientes;
    - sesiones confirmadas;
    - sesiones completadas y canceladas como referencia histórica.

    No crea nuevos registros: solamente organiza la información
    existente para facilitar la gestión diaria del Profesional.
    """

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None,
    )

    if professional_profile is None:
        return redirect('accounts:dashboard')

    if (
        professional_profile.verification_status
        != ProfessionalProfile.VerificationStatus.VERIFIED
    ):
        return redirect('accounts:dashboard')

    # Mantiene la agenda limpia antes de construir
    # contadores, calendario y detalle del día.
    expire_pending_bookings(
        professional_profile=professional_profile
    )

    today = timezone.localdate()

    # =====================================================
    # MES A MOSTRAR
    # =====================================================

    requested_month = request.GET.get('month', '').strip()
    display_month = None

    if requested_month:
        try:
            year_text, month_text = requested_month.split('-', 1)
            display_month = date(
                int(year_text),
                int(month_text),
                1,
            )
        except (TypeError, ValueError):
            display_month = None

    if display_month is None:
        display_month = today.replace(day=1)

    def shift_month(month_date, offset):
        month_index = (
            month_date.year * 12
            + month_date.month
            - 1
            + offset
        )
        return date(
            month_index // 12,
            month_index % 12 + 1,
            1,
        )

    previous_month = shift_month(display_month, -1)
    next_month = shift_month(display_month, 1)
    next_month_start = next_month
    month_end = next_month_start - timedelta(days=1)

    month_names = {
        1: 'Enero',
        2: 'Febrero',
        3: 'Marzo',
        4: 'Abril',
        5: 'Mayo',
        6: 'Junio',
        7: 'Julio',
        8: 'Agosto',
        9: 'Septiembre',
        10: 'Octubre',
        11: 'Noviembre',
        12: 'Diciembre',
    }

    display_month_label = (
        f'{month_names[display_month.month]} '
        f'{display_month.year}'
    )

    # Barra de meses del año seleccionado.
    month_navigation = [
        {
            'number': month_number,
            'short_name': month_names[month_number][:3].upper(),
            'full_name': month_names[month_number],
            'query_value': (
                f'{display_month.year}-{month_number:02d}'
            ),
            'is_active': month_number == display_month.month,
        }
        for month_number in range(1, 13)
    ]

    # =====================================================
    # FECHA SELECCIONADA
    # =====================================================

    selected_date = parse_date(
        request.GET.get('date', '')
    )

    if not (
        selected_date
        and selected_date.year == display_month.year
        and selected_date.month == display_month.month
    ):
        if (
            today.year == display_month.year
            and today.month == display_month.month
        ):
            selected_date = today
        else:
            selected_date = display_month

    # =====================================================
    # SERVICIOS / DISPONIBILIDADES
    # =====================================================

    services = (
        professional_profile.services
        .order_by('name')
    )

    primary_service = (
        services
        .filter(
            publication_status=(
                ProfessionalService.PublicationStatus.PUBLISHED
            )
        )
        .first()
        or services.first()
    )

    availabilities = list(
        ProfessionalServiceAvailability.objects
        .filter(
            service__professional_profile=professional_profile,
            is_active=True,
            valid_from__lte=month_end,
        )
        .filter(
            Q(valid_until__isnull=True)
            | Q(valid_until__gte=display_month)
        )
        .select_related('service')
        .order_by(
            'valid_from',
            'start_time',
        )
    )

    # =====================================================
    # RESERVAS DEL MES
    # =====================================================

    bookings = list(
        Booking.objects
        .filter(
            professional_profile=professional_profile,
            session_date__range=(
                display_month,
                month_end,
            ),
        )
        .select_related(
            'booked_by',
            'service',
        )
        .order_by(
            'session_date',
            'start_time',
        )
    )

    # =====================================================
    # MAPAS POR FECHA
    # =====================================================

    availability_by_date = {}
    booking_by_date = {}

    current_date = display_month
    while current_date <= month_end:
        availability_by_date[current_date] = []
        booking_by_date[current_date] = []
        current_date += timedelta(days=1)

    for availability in availabilities:
        current_date = max(
            display_month,
            availability.valid_from,
        )

        effective_end = min(
            month_end,
            availability.valid_until or month_end,
        )

        while current_date <= effective_end:
            if current_date.weekday() == availability.weekday:
                availability_by_date[current_date].append(
                    availability
                )
            current_date += timedelta(days=1)

    for booking in bookings:
        booking_by_date.setdefault(
            booking.session_date,
            [],
        ).append(booking)

    # =====================================================
    # CELDAS DEL CALENDARIO
    # =====================================================

    calendar_weeks = []
    month_calendar = calendar_module.Calendar(
        firstweekday=0,
    )

    for week in month_calendar.monthdatescalendar(
        display_month.year,
        display_month.month,
    ):
        week_cells = []

        for cell_date in week:
            in_month = (
                cell_date.month == display_month.month
                and cell_date.year == display_month.year
            )

            day_availabilities = (
                availability_by_date.get(cell_date, [])
                if in_month
                else []
            )

            day_bookings = (
                booking_by_date.get(cell_date, [])
                if in_month
                else []
            )

            pending_count = sum(
                1
                for booking in day_bookings
                if booking.status == Booking.Status.PENDING
            )

            confirmed_count = sum(
                1
                for booking in day_bookings
                if booking.status == Booking.Status.CONFIRMED
            )

            completed_count = sum(
                1
                for booking in day_bookings
                if booking.status == Booking.Status.COMPLETED
            )

            cancelled_count = sum(
                1
                for booking in day_bookings
                if booking.status == Booking.Status.CANCELLED
            )

            history_count = sum(
                1
                for booking in day_bookings
                if booking.status not in [
                    Booking.Status.PENDING,
                    Booking.Status.CONFIRMED,
                ]
            )

            week_cells.append(
                {
                    'date': cell_date,
                    'in_month': in_month,
                    'is_today': cell_date == today,
                    'is_selected': (
                        cell_date == selected_date
                    ),
                    'availability_count': len(
                        day_availabilities
                    ),
                    'pending_count': pending_count,
                    'confirmed_count': confirmed_count,
                    'completed_count': completed_count,
                    'cancelled_count': cancelled_count,
                    'history_count': history_count,
                    'has_activity': bool(
                        day_availabilities
                        or day_bookings
                    ),
                }
            )

        calendar_weeks.append(week_cells)

    # =====================================================
    # RESUMEN DEL MES
    # =====================================================

    monthly_availability_count = sum(
        len(items)
        for items in availability_by_date.values()
    )

    monthly_pending_count = sum(
        1
        for booking in bookings
        if booking.status == Booking.Status.PENDING
    )

    monthly_confirmed_count = sum(
        1
        for booking in bookings
        if booking.status == Booking.Status.CONFIRMED
    )

    monthly_history_count = sum(
        1
        for booking in bookings
        if booking.status not in [
            Booking.Status.PENDING,
            Booking.Status.CONFIRMED,
        ]
    )

    # =====================================================
    # DETALLE DEL DÍA SELECCIONADO
    # =====================================================

    selected_availabilities = list(
        availability_by_date.get(
            selected_date,
            [],
        )
    )

    for availability in selected_availabilities:
        availability.calendar_kind = (
            'Fecha exacta'
            if (
                availability.valid_until
                and availability.valid_from
                == availability.valid_until
            )
            else 'Recurrente'
        )

    selected_bookings = list(
        booking_by_date.get(
            selected_date,
            [],
        )
    )

    selected_active_bookings = [
        booking
        for booking in selected_bookings
        if booking.status in [
            Booking.Status.PENDING,
            Booking.Status.CONFIRMED,
        ]
    ]

    selected_history_bookings = [
        booking
        for booking in selected_bookings
        if booking.status not in [
            Booking.Status.PENDING,
            Booking.Status.CONFIRMED,
        ]
    ]

    # =====================================================
    # ESTADO VISUAL DE CADA BLOQUE DE DISPONIBILIDAD
    # =====================================================
    #
    # Un bloque publicado puede seguir existiendo como
    # disponibilidad base, pero en una fecha concreta puede:
    # - estar libre;
    # - tener una solicitud pendiente;
    # - estar reservado por una sesión confirmada.
    #
    # Esto evita que el Profesional interprete como "libre"
    # un horario que ya está comprometido.
    for availability in selected_availabilities:

        overlapping_active_bookings = [
            booking
            for booking in selected_active_bookings
            if (
                booking.service_id
                == availability.service_id
                and booking.start_time
                < availability.end_time
                and booking.end_time
                > availability.start_time
            )
        ]

        has_confirmed_booking = any(
            booking.status
            == Booking.Status.CONFIRMED
            for booking in overlapping_active_bookings
        )

        has_pending_booking = any(
            booking.status
            == Booking.Status.PENDING
            for booking in overlapping_active_bookings
        )

        confirmed_booking = next(
            (
                booking
                for booking
                in overlapping_active_bookings
                if (
                    booking.status
                    == Booking.Status.CONFIRMED
                )
            ),
            None,
        )

        pending_booking = next(
            (
                booking
                for booking
                in overlapping_active_bookings
                if (
                    booking.status
                    == Booking.Status.PENDING
                )
            ),
            None,
        )

        availability.calendar_booking = None

        if has_confirmed_booking:
            availability.calendar_status = (
                'reserved'
            )
            availability.calendar_status_label = (
                'Reservada'
            )
            availability.calendar_booking = (
                confirmed_booking
            )

        elif has_pending_booking:
            availability.calendar_status = (
                'pending'
            )
            availability.calendar_status_label = (
                'Solicitud pendiente'
            )
            availability.calendar_booking = (
                pending_booking
            )

        else:
            availability.calendar_status = (
                'available'
            )
            availability.calendar_status_label = (
                'Disponible'
            )

    return render(
        request,
        'professionals/calendar.html',
        {
            'professional_profile': professional_profile,
            'services': services,
            'primary_service': primary_service,
            'today': today,
            'display_month': display_month,
            'display_month_label': display_month_label,
            'previous_month': previous_month,
            'next_month': next_month,
            'month_navigation': month_navigation,
            'selected_year': display_month.year,
            'previous_year': display_month.year - 1,
            'next_year': display_month.year + 1,
            'calendar_weeks': calendar_weeks,
            'selected_date': selected_date,
            'selected_availabilities': selected_availabilities,
            'selected_bookings': selected_bookings,
            'selected_active_bookings': selected_active_bookings,
            'selected_history_bookings': selected_history_bookings,
            'monthly_availability_count': monthly_availability_count,
            'monthly_pending_count': monthly_pending_count,
            'monthly_confirmed_count': monthly_confirmed_count,
            'monthly_history_count': monthly_history_count,
        }
    )

