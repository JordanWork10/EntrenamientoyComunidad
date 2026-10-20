from datetime import datetime
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.utils.dateparse import (
    parse_date,
    parse_time,
)

from apps.professionals.models import (
    ProfessionalProfile,
    ProfessionalService,
)

from .forms import BookingCreateForm
from .models import (
    Booking,
    BookingHistory,
)
from .session_review_services import start_review
from .services import (
    create_booking,
    expire_pending_bookings,
    get_available_slots,
)





@login_required(login_url='accounts:login')
def service_booking_slots(
    request,
    service_id
):
    """
    Vista orientada al miembro que desea reservar.

    Muestra fechas amigables y únicamente los bloques que:
    - corresponden a una disponibilidad vigente;
    - respetan exactamente la duración del servicio;
    - no están ocupados por una reserva Pendiente/Confirmada.

    No crea una reserva. La creación ocurre únicamente después
    de pasar por la pantalla de confirmación.
    """

    service = get_object_or_404(
        ProfessionalService.objects.select_related(
            'professional_profile',
            'professional_profile__user',
            'location_commune',
            'location_commune__region',
        ),
        pk=service_id,
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

    today = timezone.localdate()

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

    date_error = ''
    slots = []

    if selected_date_value and selected_date is None:

        date_error = (
            'La fecha seleccionada no es válida.'
        )

    elif selected_date:

        if selected_date < today:

            date_error = (
                'Selecciona una fecha de hoy en adelante.'
            )

        else:

            slots = get_available_slots(
                service,
                selected_date,
            )

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

        # Marcamos si ese día tiene al menos una sesión realmente
        # libre, considerando reservas existentes.
        quick_slots = get_available_slots(
            service,
            quick_date,
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
                'has_slots': bool(
                    quick_slots
                ),
            }
        )

    is_own_service = (
        request.user.id
        == service.professional_profile.user_id
    )

    return render(
        request,
        'bookings/service_booking_slots.html',
        {
            'service': service,
            'selected_date': selected_date,
            'selected_date_value': (
                selected_date_value
            ),
            'weekday_label': (
                weekday_label
            ),
            'slots': slots,
            'slot_count': len(slots),
            'date_error': date_error,
            'today_value': (
                today.isoformat()
            ),
            'quick_dates': (
                quick_dates
            ),
            'is_own_service': (
                is_own_service
            ),
        }
    )


@login_required(login_url='accounts:login')
def confirm_booking(
    request,
    service_id
):
    """
    Muestra y procesa la confirmación de una sesión concreta.

    GET:
        valida que la sesión exista y siga disponible.

    POST:
        vuelve a validar todo y crea la reserva como Pendiente.

    La reserva jamás se crea únicamente con datos enviados
    por el navegador: fecha y horas se contrastan nuevamente
    con los bloques generados por el sistema.
    """

    service = get_object_or_404(
        ProfessionalService.objects.select_related(
            'professional_profile',
            'professional_profile__user',
            'location_commune',
            'location_commune__region',
        ),
        pk=service_id,
        publication_status=(
            ProfessionalService
            .PublicationStatus
            .PUBLISHED
        ),
    )

    # =====================================================
    # DATOS DE LA SESIÓN
    # =====================================================

    if request.method == 'POST':

        form = BookingCreateForm(
            request.POST
        )

    else:

        form = BookingCreateForm(
            initial={
                'session_date': (
                    request.GET.get(
                        'date',
                        ''
                    )
                ),
                'start_time': (
                    request.GET.get(
                        'start',
                        ''
                    )
                ),
                'end_time': (
                    request.GET.get(
                        'end',
                        ''
                    )
                ),
            }
        )

    # Leemos valores para poder mostrar una vista amigable
    # incluso antes de enviar el formulario.
    raw_date = (
        request.POST.get('session_date')
        if request.method == 'POST'
        else request.GET.get('date')
    )

    raw_start = (
        request.POST.get('start_time')
        if request.method == 'POST'
        else request.GET.get('start')
    )

    raw_end = (
        request.POST.get('end_time')
        if request.method == 'POST'
        else request.GET.get('end')
    )

    session_date = (
        parse_date(raw_date)
        if raw_date
        else None
    )

    start_time = (
        parse_time(raw_start)
        if raw_start
        else None
    )

    end_time = (
        parse_time(raw_end)
        if raw_end
        else None
    )

    # =====================================================
    # VALIDAR SESIÓN SELECCIONADA
    # =====================================================

    selected_slot = None
    booking_error = ''

    if (
        session_date
        and start_time
        and end_time
    ):

        available_slots = (
            get_available_slots(
                service,
                session_date,
            )
        )

        selected_slot = next(
            (
                slot
                for slot in available_slots
                if (
                    slot['start_time']
                    == start_time
                    and slot['end_time']
                    == end_time
                )
            ),
            None,
        )

        if selected_slot is None:

            booking_error = (
                'Esta sesión ya no se encuentra disponible. '
                'Vuelve a consultar los horarios del servicio.'
            )

    else:

        booking_error = (
            'La sesión seleccionada no es válida.'
        )

    # =====================================================
    # EVITAR AUTORRESERVA
    # =====================================================

    is_own_service = (
        request.user.id
        == service.professional_profile.user_id
    )

    if is_own_service:

        booking_error = (
            'No puedes reservar tu propio servicio profesional.'
        )

    # =====================================================
    # CREAR RESERVA
    # =====================================================

    if request.method == 'POST':

        if (
            form.is_valid()
            and selected_slot is not None
            and not is_own_service
        ):

            try:

                booking = create_booking(
                    user=request.user,
                    service=service,
                    session_date=(
                        form.cleaned_data[
                            'session_date'
                        ]
                    ),
                    start_time=(
                        form.cleaned_data[
                            'start_time'
                        ]
                    ),
                    end_time=(
                        form.cleaned_data[
                            'end_time'
                        ]
                    ),
                )

            except ValidationError as exc:

                booking_error = (
                    'No fue posible crear la reserva. '
                    'La sesión pudo haber cambiado o sido '
                    'reservada por otra persona.'
                )

                if hasattr(
                    exc,
                    'message_dict'
                ):

                    form.add_error(
                        None,
                        booking_error
                    )

            else:

                messages.success(
                    request,
                    (
                        'Reserva creada correctamente. '
                        'Quedó registrada como Pendiente.'
                    )
                )

                return redirect(
                    'bookings:detail',
                    booking_id=booking.id,
                )

    # =====================================================
    # LUGAR DE ATENCIÓN
    # =====================================================

    location_summary = ''

    if (
        service.mode
        in (
            ProfessionalService
            .ServiceMode
            .IN_PERSON,
            ProfessionalService
            .ServiceMode
            .HYBRID,
        )
    ):

        if (
            service.in_person_location_type
            == ProfessionalService
            .InPersonLocationType
            .PROFESSIONAL_PLACE
        ):

            location_summary = (
                service.location_name
                or 'Lugar del profesional'
            )

        elif (
            service.in_person_location_type
            == ProfessionalService
            .InPersonLocationType
            .USER_HOME
        ):

            location_summary = (
                'Domicilio del usuario'
            )

        elif (
            service.in_person_location_type
            == ProfessionalService
            .InPersonLocationType
            .AGREED_PLACE
        ):

            location_summary = (
                'Lugar acordado con el usuario'
            )

    return render(
        request,
        'bookings/confirm_booking.html',
        {
            'form': form,
            'service': service,
            'session_date': session_date,
            'start_time': start_time,
            'end_time': end_time,
            'selected_slot': selected_slot,
            'booking_error': booking_error,
            'is_own_service': is_own_service,
            'location_summary': (
                location_summary
            ),
        }
    )


@login_required(login_url='accounts:login')
def booking_detail(
    request,
    booking_id
):
    """
    Muestra una reserva perteneciente al usuario autenticado.

    Incluye:
    - snapshot de la reserva;
    - estado actual;
    - historial completo;
    - cancelación habilitada solo cuando corresponde.
    """

    expire_pending_bookings(
        booked_by=request.user
    )

    booking = get_object_or_404(
        request.user.bookings.select_related(
            'service',
            'professional_profile',
            'professional_profile__user',
        ),
        pk=booking_id,
    )

    history_entries = (
        booking.history
        .select_related(
            'changed_by'
        )
        .order_by(
            '-created_at'
        )
    )

    local_timezone = (
        timezone.get_current_timezone()
    )

    session_start_datetime = (
        timezone.make_aware(
            datetime.combine(
                booking.session_date,
                booking.start_time,
            ),
            local_timezone,
        )
    )

    cancellable_statuses = [
        Booking.Status.PENDING,
        Booking.Status.CONFIRMED,
    ]

    can_cancel = (
        booking.status in cancellable_statuses
        and timezone.now()
        < session_start_datetime
    )

    return render(
        request,
        'bookings/booking_detail.html',
        {
            'booking': booking,
            'history_entries': (
                history_entries
            ),
            'session_start_datetime': (
                session_start_datetime
            ),
            'can_cancel': (
                can_cancel
            ),
        }
    )


@login_required(login_url='accounts:login')
def my_bookings(
    request
):
    """
    Muestra las reservas pertenecientes al usuario autenticado.

    Se separan en:
    - próximas: Pendientes o Confirmadas desde hoy en adelante;
    - historial: Canceladas, Completadas o reservas pasadas.

    Esta vista es solo de consulta.
    """

    expire_pending_bookings(
        booked_by=request.user
    )

    today = timezone.localdate()

    base_queryset = (
        request.user
        .bookings
        .select_related(
            'service',
            'professional_profile',
            'professional_profile__user',
        )
    )

    upcoming_statuses = [
        Booking.Status.PENDING,
        Booking.Status.CONFIRMED,
    ]

    upcoming_bookings = (
        base_queryset
        .filter(
            session_date__gte=today,
            status__in=upcoming_statuses,
        )
        .order_by(
            'session_date',
            'start_time',
        )
    )

    # El historial se presenta con etiquetas coherentes con la vista
    # profesional, sin modificar los estados guardados en PostgreSQL.
    history_bookings = list(
        base_queryset
        .exclude(
            session_date__gte=today,
            status__in=upcoming_statuses,
        )
        .order_by(
            '-session_date',
            '-start_time',
        )
    )

    for history_booking in history_bookings:
        if (
            history_booking.session_date < today
            and history_booking.status in upcoming_statuses
        ):
            # Una sesion pasada no esta necesariamente completada.
            # Este distintivo afecta solo al texto y a la apariencia.
            history_booking.ui_status_label = 'Pasada'
            history_booking.ui_status_key = 'past'
        else:
            history_booking.ui_status_label = (
                history_booking.get_status_display()
            )
            history_booking.ui_status_key = history_booking.status

    return render(
        request,
        'bookings/my_bookings.html',
        {
            'upcoming_bookings': (
                upcoming_bookings
            ),
            'history_bookings': (
                history_bookings
            ),
            'upcoming_count': (
                upcoming_bookings.count()
            ),
            'history_count': (
                len(history_bookings)
            ),
        }
    )


@login_required(login_url='accounts:login')
def professional_received_bookings(
    request
):
    """
    Muestra las solicitudes y sesiones recibidas por el Profesional autenticado.

    Se separan en:
    - próximas: Pendientes o Confirmadas desde hoy en adelante;
    - historial: No aceptadas, Canceladas, Completadas o sesiones pasadas.

    La presentación distingue una solicitud Pendiente rechazada por el
    Profesional de una reserva Confirmada que posteriormente fue cancelada.
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

    expire_pending_bookings(
        professional_profile=professional_profile
    )

    today = timezone.localdate()

    base_queryset = (
        Booking.objects
        .filter(
            professional_profile=professional_profile
        )
        .select_related(
            'booked_by',
            'service',
            'professional_profile',
        )
        .prefetch_related(
            'history__changed_by',
        )
    )

    active_statuses = [
        Booking.Status.PENDING,
        Booking.Status.CONFIRMED,
    ]

    upcoming_bookings = (
        base_queryset
        .filter(
            session_date__gte=today,
            status__in=active_statuses,
        )
        .order_by(
            'session_date',
            'start_time',
        )
    )

    # -------------------------------------------------
    # HISTORIAL
    # -------------------------------------------------
    # Entran:
    # - canceladas;
    # - completadas;
    # - pendientes/confirmadas cuya fecha ya pasó.
    #
    # Se ordena primero por el último cambio realizado.

    history_bookings = list(
        base_queryset
        .filter(
            Q(
                status__in=[
                    Booking.Status.CANCELLED,
                    Booking.Status.COMPLETED,
                    Booking.Status.EXPIRED,
                ]
            )
            |
            Q(
                status__in=[
                    Booking.Status.PENDING,
                    Booking.Status.CONFIRMED,
                ],
                session_date__lt=today,
            )
        )
        .order_by(
            '-updated_at',
            '-session_date',
            '-start_time',
        )
    )

    # -------------------------------------------------
    # ETIQUETAS HUMANAS DEL HISTORIAL
    # -------------------------------------------------
    # No aceptada:
    # la solicitud estaba Pendiente y fue cerrada por este Profesional.
    #
    # Cancelada:
    # una reserva ya aceptada fue cancelada posteriormente, o la canceló
    # el propio miembro.
    #
    # Pasada:
    # seguía Pendiente/Confirmada, pero la fecha de la sesión ya ocurrió.

    for history_booking in history_bookings:

        history_booking.professional_rejected = False

        if (
            history_booking.status
            == Booking.Status.CANCELLED
        ):

            for history_item in history_booking.history.all():

                previous_status = (
                    (history_item.previous_data or {})
                    .get('status')
                )

                if (
                    history_item.action
                    == BookingHistory.Action.CANCELLED
                    and previous_status
                    == Booking.Status.PENDING
                    and history_item.changed_by_id
                    == request.user.id
                ):
                    history_booking.professional_rejected = True
                    break

        if history_booking.professional_rejected:

            history_booking.ui_status_label = (
                'No aceptada'
            )
            history_booking.ui_status_key = (
                'cancelled'
            )

        elif (
            history_booking.session_date
            < today
            and history_booking.status
            in {
                Booking.Status.PENDING,
                Booking.Status.CONFIRMED,
            }
        ):

            history_booking.ui_status_label = (
                'Pasada'
            )
            history_booking.ui_status_key = (
                'completed'
            )

        else:

            history_booking.ui_status_label = (
                history_booking.get_status_display()
            )
            history_booking.ui_status_key = (
                history_booking.status
            )

    pending_count = (
        upcoming_bookings
        .filter(
            status=Booking.Status.PENDING
        )
        .count()
    )

    confirmed_count = (
        upcoming_bookings
        .filter(
            status=Booking.Status.CONFIRMED
        )
        .count()
    )

    return render(
        request,
        'bookings/professional_received_bookings.html',
        {
            'professional_profile': (
                professional_profile
            ),
            'upcoming_bookings': (
                upcoming_bookings
            ),
            'history_bookings': (
                history_bookings
            ),
            'pending_count': (
                pending_count
            ),
            'confirmed_count': (
                confirmed_count
            ),
            'history_count': (
                len(history_bookings)
            ),
        }
    )


@login_required(login_url='accounts:login')
def professional_booking_detail(
    request,
    booking_id
):
    """
    Detalle de una reserva recibida por el Profesional autenticado.

    El Profesional solo puede consultar reservas pertenecientes
    a sus propios servicios.
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

    expire_pending_bookings(
        professional_profile=professional_profile
    )

    booking = get_object_or_404(
        Booking.objects.select_related(
            'booked_by',
            'service',
            'professional_profile',
        ),
        pk=booking_id,
        professional_profile=professional_profile,
    )

    history_entries = (
        booking.history
        .select_related(
            'changed_by'
        )
        .order_by(
            '-created_at'
        )
    )

    local_timezone = (
        timezone.get_current_timezone()
    )

    session_end_datetime = (
        timezone.make_aware(
            datetime.combine(
                booking.session_date,
                booking.end_time,
            ),
            local_timezone,
        )
    )

    can_complete = (
        booking.status
        == Booking.Status.CONFIRMED
        and timezone.now()
        >= session_end_datetime
    )

    return render(
        request,
        'bookings/professional_booking_detail.html',
        {
            'booking': booking,
            'professional_profile': (
                professional_profile
            ),
            'history_entries': (
                history_entries
            ),
            'session_end_datetime': (
                session_end_datetime
            ),
            'can_complete': (
                can_complete
            ),
        }
    )


@login_required(login_url='accounts:login')
@require_POST
def professional_confirm_booking(
    request,
    booking_id
):
    """
    Confirma una reserva Pendiente perteneciente al Profesional
    autenticado.

    La operación:
    - usa POST + CSRF;
    - bloquea la reserva durante el cambio;
    - valida que pertenezca al Profesional;
    - solo permite Pendiente -> Confirmada;
    - conserva el estado anterior y el nuevo en BookingHistory.
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

    expire_pending_bookings(
        professional_profile=professional_profile
    )

    with transaction.atomic():

        booking = get_object_or_404(
            Booking.objects
            .select_for_update()
            .select_related(
                'booked_by',
                'service',
                'professional_profile',
            ),
            pk=booking_id,
            professional_profile=professional_profile,
        )

        if booking.status != Booking.Status.PENDING:

            messages.warning(
                request,
                (
                    'Esta reserva ya no se encuentra Pendiente '
                    'y no puede confirmarse nuevamente.'
                )
            )

            return redirect(
                'bookings:professional_detail',
                booking_id=booking.id,
            )

        previous_data = (
            booking.audit_snapshot()
        )

        booking.status = (
            Booking.Status.CONFIRMED
        )

        booking.confirmed_at = (
            timezone.now()
        )

        booking.save(
            update_fields=[
                'status',
                'confirmed_at',
                'updated_at',
            ]
        )

        BookingHistory.objects.create(
            booking=booking,
            action=(
                BookingHistory
                .Action
                .CONFIRMED
            ),
            previous_data=previous_data,
            new_data=(
                booking.audit_snapshot()
            ),
            changed_by=request.user,
            reason=(
                'Reserva confirmada por el Profesional '
                'desde el Centro Profesional.'
            ),
        )

    messages.success(
        request,
        'La reserva fue confirmada correctamente.'
    )

    return redirect(
        'bookings:professional_detail',
        booking_id=booking.id,
    )


@login_required(login_url='accounts:login')
@require_POST
def professional_cancel_booking(
    request,
    booking_id
):
    """
    Cancela una reserva Pendiente o Confirmada perteneciente
    al Profesional autenticado.

    Reglas:
    - usa POST + CSRF;
    - exige un motivo de cancelación;
    - solo admite Pendiente/Confirmada -> Cancelada;
    - conserva confirmed_at si alguna vez fue confirmada;
    - registra cancelled_at;
    - crea BookingHistory con estado anterior y nuevo;
    - al quedar Cancelada, deja de bloquear el horario.
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

    expire_pending_bookings(
        professional_profile=professional_profile
    )

    cancellation_reason = (
        request.POST
        .get(
            'cancellation_reason',
            ''
        )
        .strip()
    )

    if len(cancellation_reason) < 5:

        messages.warning(
            request,
            (
                'Debes indicar un motivo de cancelación '
                'de al menos 5 caracteres.'
            )
        )

        return redirect(
            'bookings:professional_detail',
            booking_id=booking_id,
        )

    with transaction.atomic():

        booking = get_object_or_404(
            Booking.objects
            .select_for_update()
            .select_related(
                'booked_by',
                'service',
                'professional_profile',
            ),
            pk=booking_id,
            professional_profile=professional_profile,
        )

        allowed_statuses = [
            Booking.Status.PENDING,
            Booking.Status.CONFIRMED,
        ]

        if booking.status not in allowed_statuses:

            messages.warning(
                request,
                (
                    'Esta reserva ya se encuentra cerrada '
                    'y no puede cancelarse nuevamente.'
                )
            )

            return redirect(
                'bookings:professional_detail',
                booking_id=booking.id,
            )

        previous_data = (
            booking.audit_snapshot()
        )

        booking.status = (
            Booking.Status.CANCELLED
        )

        booking.cancellation_reason = (
            cancellation_reason
        )

        booking.cancelled_at = (
            timezone.now()
        )

        booking.save(
            update_fields=[
                'status',
                'cancellation_reason',
                'cancelled_at',
                'updated_at',
            ]
        )

        BookingHistory.objects.create(
            booking=booking,
            action=(
                BookingHistory
                .Action
                .CANCELLED
            ),
            previous_data=previous_data,
            new_data=(
                booking.audit_snapshot()
            ),
            changed_by=request.user,
            reason=(
                cancellation_reason
            ),
        )

    messages.success(
        request,
        (
            'La reserva fue cancelada. '
            'El horario volvió a quedar disponible '
            'si la disponibilidad profesional continúa vigente.'
        )
    )

    return redirect(
        'bookings:professional_detail',
        booking_id=booking.id,
    )


@login_required(login_url='accounts:login')
@require_POST
def professional_complete_booking(
    request,
    booking_id
):
    """
    Marca como Completada una reserva Confirmada perteneciente
    al Profesional autenticado.

    Reglas:
    - usa POST + CSRF;
    - solo permite Confirmada -> Completada;
    - no permite completar antes de la hora real de término;
    - registra completed_at;
    - crea BookingHistory con estado anterior y nuevo;
    - Completada es un estado final y deja de bloquear el horario.
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

    with transaction.atomic():

        booking = get_object_or_404(
            Booking.objects
            .select_for_update()
            .select_related(
                'booked_by',
                'service',
                'professional_profile',
            ),
            pk=booking_id,
            professional_profile=professional_profile,
        )

        if (
            booking.status
            != Booking.Status.CONFIRMED
        ):

            messages.warning(
                request,
                (
                    'Solo una reserva Confirmada '
                    'puede marcarse como Completada.'
                )
            )

            return redirect(
                'bookings:professional_detail',
                booking_id=booking.id,
            )

        local_timezone = (
            timezone.get_current_timezone()
        )

        session_end_datetime = (
            timezone.make_aware(
                datetime.combine(
                    booking.session_date,
                    booking.end_time,
                ),
                local_timezone,
            )
        )

        if (
            timezone.now()
            < session_end_datetime
        ):

            messages.warning(
                request,
                (
                    'La sesión todavía no ha terminado. '
                    'Solo podrá marcarse como Completada '
                    'después de su hora de término.'
                )
            )

            return redirect(
                'bookings:professional_detail',
                booking_id=booking.id,
            )

        previous_data = (
            booking.audit_snapshot()
        )

        booking.status = (
            Booking.Status.COMPLETED
        )

        booking.completed_at = (
            timezone.now()
        )

        booking.save(
            update_fields=[
                'status',
                'completed_at',
                'updated_at',
            ]
        )

        BookingHistory.objects.create(
            booking=booking,
            action=(
                BookingHistory
                .Action
                .COMPLETED
            ),
            previous_data=previous_data,
            new_data=(
                booking.audit_snapshot()
            ),
            changed_by=request.user,
            reason=(
                'Reserva marcada como Completada '
                'por el Profesional después de '
                'finalizar la sesión.'
            ),
        )


        # V121: crear seguimiento del Miembro en la misma transacción.
        # No modifica el estado Completada ni el historial existente.
        start_review(booking)

    messages.success(
        request,
        (
            'La reserva fue marcada como Completada '
            'y el cambio quedó registrado en el historial.'
        )
    )

    return redirect(
        'bookings:professional_detail',
        booking_id=booking.id,
    )


@login_required(login_url='accounts:login')
@require_POST
def cancel_my_booking(
    request,
    booking_id
):
    """
    Permite al usuario cancelar una reserva propia.

    Reglas:
    - solo puede cancelar sus propias reservas;
    - solo Pendiente o Confirmada;
    - debe hacerlo antes del inicio de la sesión;
    - exige motivo;
    - registra Cancelada + cancelled_at;
    - crea BookingHistory;
    - la reserva nunca se elimina.
    """

    expire_pending_bookings(
        booked_by=request.user
    )

    cancellation_reason = (
        request.POST
        .get(
            'cancellation_reason',
            ''
        )
        .strip()
    )

    if len(cancellation_reason) < 5:

        messages.warning(
            request,
            (
                'Debes indicar un motivo de cancelación '
                'de al menos 5 caracteres.'
            )
        )

        return redirect(
            'bookings:detail',
            booking_id=booking_id,
        )

    with transaction.atomic():

        booking = get_object_or_404(
            Booking.objects
            .select_for_update()
            .select_related(
                'service',
                'professional_profile',
                'professional_profile__user',
            ),
            pk=booking_id,
            booked_by=request.user,
        )

        allowed_statuses = [
            Booking.Status.PENDING,
            Booking.Status.CONFIRMED,
        ]

        if booking.status not in allowed_statuses:

            messages.warning(
                request,
                (
                    'Esta reserva ya se encuentra cerrada '
                    'y no puede cancelarse.'
                )
            )

            return redirect(
                'bookings:detail',
                booking_id=booking.id,
            )

        local_timezone = (
            timezone.get_current_timezone()
        )

        session_start_datetime = (
            timezone.make_aware(
                datetime.combine(
                    booking.session_date,
                    booking.start_time,
                ),
                local_timezone,
            )
        )

        if timezone.now() >= session_start_datetime:

            messages.warning(
                request,
                (
                    'La sesión ya comenzó o alcanzó su hora '
                    'de inicio. Ya no puede cancelarse desde '
                    'Mi Cuenta.'
                )
            )

            return redirect(
                'bookings:detail',
                booking_id=booking.id,
            )

        previous_data = (
            booking.audit_snapshot()
        )

        booking.status = (
            Booking.Status.CANCELLED
        )

        booking.cancellation_reason = (
            cancellation_reason
        )

        booking.cancelled_at = (
            timezone.now()
        )

        booking.save(
            update_fields=[
                'status',
                'cancellation_reason',
                'cancelled_at',
                'updated_at',
            ]
        )

        BookingHistory.objects.create(
            booking=booking,
            action=(
                BookingHistory
                .Action
                .CANCELLED
            ),
            previous_data=previous_data,
            new_data=(
                booking.audit_snapshot()
            ),
            changed_by=request.user,
            reason=(
                cancellation_reason
            ),
        )

    messages.success(
        request,
        (
            'La reserva fue cancelada correctamente. '
            'El cambio quedó registrado en el historial.'
        )
    )

    return redirect(
        'bookings:detail',
        booking_id=booking.id,
    )

