import calendar as pycalendar
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.locations.models import Commune

from .forms import (
    PublicSpaceFilterForm,
    SpaceAvailabilityForm,
    SpaceAvailabilityExceptionForm,
    SpaceBookingCreateForm,
    SpaceCreateForm,
    SpaceProviderProfileRequestForm,
)
from .models import (
    Space,
    SpaceAvailability,
    SpaceAvailabilityException,
    SpaceAvailabilityExceptionHistory,
    SpaceAvailabilityHistory,
    SpaceBooking,
    SpaceBookingHistory,
    SpaceHistory,
    SpaceImage,
    SpaceEquipment,
    SpaceAmenity,
    SpaceProviderProfile,
    SpaceProviderProfileHistory,
)


EXACT_DATE_AVAILABILITY_REASON = (
    'Disponibilidad publicada desde '
    'el Calendario de arriendos.'
)


def _space_catalog_recommendation_context():
    """
    Prepara las asociaciones que permiten destacar equipamientos
    y comodidades sugeridos según el tipo de espacio seleccionado.

    Las opciones sin asociación siguen disponibles como alternativas
    generales; nunca se ocultan del formulario.
    """

    equipments = (
        SpaceEquipment.objects
        .filter(is_active=True)
        .prefetch_related('recommended_space_types')
        .order_by('display_order', 'name')
    )

    amenities = (
        SpaceAmenity.objects
        .filter(is_active=True)
        .prefetch_related('recommended_space_types')
        .order_by('display_order', 'name')
    )

    equipment_recommendations = {
        str(item.pk): [
            str(space_type.pk)
            for space_type in item.recommended_space_types.all()
        ]
        for item in equipments
    }

    amenity_recommendations = {
        str(item.pk): [
            str(space_type.pk)
            for space_type in item.recommended_space_types.all()
        ]
        for item in amenities
    }

    return {
        'equipment_recommendations': equipment_recommendations,
        'amenity_recommendations': amenity_recommendations,
    }


@login_required(
    login_url='accounts:login'
)
def communes_by_region(request):
    """
    Devuelve las comunas activas pertenecientes
    a una región para el formulario del Proveedor.
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


@login_required(
    login_url='accounts:login'
)
def request_space_provider_profile(request):
    """
    Crea o completa la solicitud de Perfil de
    Proveedor de Espacios.

    Si existe una solicitud Pendiente o Rechazada,
    el usuario puede actualizarla sin eliminar
    el registro anterior.
    """

    member_profile = getattr(
        request.user,
        'member_profile',
        None
    )

    account_ready = all([
        request.user.first_name,
        request.user.last_name,
        request.user.rut,
        request.user.phone,
        request.user.birth_date,
        request.user.commune,
        member_profile is not None,
        request.user.terms_accepted,
        request.user.privacy_accepted,
    ])

    if not account_ready:

        return redirect(
            'accounts:dashboard'
        )

    existing_profile = (
        SpaceProviderProfile.objects
        .filter(
            user=request.user
        )
        .first()
    )

    if (
        existing_profile
        and existing_profile.verification_status
        in (
            SpaceProviderProfile
            .VerificationStatus
            .VERIFIED,

            SpaceProviderProfile
            .VerificationStatus
            .SUSPENDED,
        )
    ):

        return redirect(
            'accounts:dashboard'
        )

    is_editing = (
        existing_profile is not None
    )

    if request.method == 'POST':

        form = (
            SpaceProviderProfileRequestForm(
                request.POST,
                request.FILES,
                instance=existing_profile,
            )
        )

        if form.is_valid():

            with transaction.atomic():

                previous_data = {}

                previous_status = None

                if existing_profile:

                    previous_profile = (
                        SpaceProviderProfile.objects
                        .select_for_update()
                        .get(
                            pk=existing_profile.pk
                        )
                    )

                    previous_data = (
                        previous_profile
                        .audit_snapshot()
                    )

                    previous_status = (
                        previous_profile
                        .verification_status
                    )

                provider_profile = (
                    form.save(
                        commit=False
                    )
                )

                provider_profile.user = (
                    request.user
                )

                provider_profile.verification_status = (
                    SpaceProviderProfile
                    .VerificationStatus
                    .PENDING
                )

                provider_profile.is_public = False

                provider_profile.rejection_reason = ''

                provider_profile.reviewed_at = None

                provider_profile.information_declaration_accepted_at = (
                    timezone.now()
                )

                provider_profile.save()

                if existing_profile is None:

                    action = (
                        SpaceProviderProfileHistory
                        .Action
                        .REQUESTED
                    )

                    reason = (
                        'Solicitud inicial de Perfil '
                        'Proveedor de Espacios.'
                    )

                elif (
                    previous_status
                    == SpaceProviderProfile
                    .VerificationStatus
                    .REJECTED
                ):

                    action = (
                        SpaceProviderProfileHistory
                        .Action
                        .RESUBMITTED
                    )

                    reason = (
                        'Solicitud corregida y reenviada '
                        'por el proveedor.'
                    )

                else:

                    action = (
                        SpaceProviderProfileHistory
                        .Action
                        .UPDATED
                    )

                    reason = (
                        'Solicitud actualizada por '
                        'el proveedor.'
                    )

                SpaceProviderProfileHistory.objects.create(
                    provider_profile=provider_profile,
                    action=action,
                    previous_data=previous_data,
                    new_data=(
                        provider_profile
                        .audit_snapshot()
                    ),
                    changed_by=request.user,
                    reason=reason,
                )

            return redirect(
                'accounts:dashboard'
            )

    else:

        form = (
            SpaceProviderProfileRequestForm(
                instance=existing_profile
            )
        )

    return render(
        request,
        'spaces/request_profile.html',
        {
            'form': form,
            'existing_profile': (
                existing_profile
            ),
            'is_editing': is_editing,
        }
    )


@login_required(
    login_url='accounts:login'
)
def space_provider_dashboard(request):
    """
    Centro de gestión exclusivo para usuarios con
    Perfil de Proveedor de Espacios verificado.

    La vista prepara cada recinto como una tarjeta visual
    con portada y accesos directos a sus acciones principales.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if provider_profile is None:

        return redirect(
            'accounts:dashboard'
        )

    if (
        provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):

        return redirect(
            'accounts:dashboard'
        )

    infrastructure_labels = (
        provider_profile
        .get_managed_infrastructure_labels()
    )

    spaces = list(
        provider_profile.spaces
        .select_related(
            'space_type',
            'commune',
            'commune__region',
        )
        .prefetch_related(
            'images',
            'availability_windows',
            'availability_exceptions',
            'bookings',
        )
        .order_by(
            '-created_at'
        )
    )

    pending_received_bookings = (
        provider_profile.space_bookings
        .filter(
            status=SpaceBooking.Status.PENDING
        )
        .select_related(
            'booked_by',
            'space',
        )
        .order_by(
            'session_date',
            'start_time',
            'created_at',
        )
    )

    provider_pending_booking_count = (
        pending_received_bookings.count()
    )

    provider_pending_booking = (
        pending_received_bookings.first()
    )

    provider_pending_bookings_preview = list(
        pending_received_bookings[:3]
    )

    provider_pending_preview_count = len(
        provider_pending_bookings_preview
    )

    provider_pending_remaining_count = max(
        provider_pending_booking_count
        - provider_pending_preview_count,
        0,
    )

    for space in spaces:

        images = list(
            space.images.all()
        )

        space.dashboard_cover = next(
            (
                image
                for image in images
                if image.is_cover
            ),
            images[0] if images else None,
        )

        space.dashboard_active_availability = (
            sum(
                1
                for item
                in space.availability_windows.all()
                if item.is_active
            )
        )

        space.dashboard_pending_bookings = (
            sum(
                1
                for item
                in space.bookings.all()
                if item.status
                == SpaceBooking.Status.PENDING
            )
        )

        space.dashboard_confirmed_bookings = (
            sum(
                1
                for item
                in space.bookings.all()
                if item.status
                == SpaceBooking.Status.CONFIRMED
            )
        )

    return render(
        request,
        'spaces/dashboard.html',
        {
            'provider_profile': (
                provider_profile
            ),
            'infrastructure_labels': (
                infrastructure_labels
            ),
            'spaces': spaces,
            'space_count': len(
                spaces
            ),
            'provider_pending_booking_count': (
                provider_pending_booking_count
            ),
            'provider_pending_booking': (
                provider_pending_booking
            ),
            'provider_pending_bookings_preview': (
                provider_pending_bookings_preview
            ),
            'provider_pending_preview_count': (
                provider_pending_preview_count
            ),
            'provider_pending_remaining_count': (
                provider_pending_remaining_count
            ),
        }
    )



@login_required(
    login_url='accounts:login'
)
def provider_rental_calendar(request):
    """
    Calendario mensual del Proveedor de Espacios.

    Reúne:
    - bloques actualmente reservables;
    - solicitudes pendientes;
    - arriendos confirmados;
    - historial del día.

    Si el proveedor administra más de un recinto puede
    filtrar un espacio específico o visualizar todos.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    today = timezone.localdate()

    # -------------------------------------------------
    # ESPACIOS DEL PROVEEDOR
    # -------------------------------------------------

    spaces = list(
        provider_profile.spaces
        .select_related(
            'space_type',
            'commune',
            'commune__region',
        )
        .prefetch_related(
            'availability_windows',
            'availability_exceptions',
        )
        .order_by(
            'name',
            'id',
        )
    )

    selected_space = None

    requested_space = (
        request.GET
        .get('space', '')
        .strip()
    )

    if requested_space.isdigit():
        selected_space = next(
            (
                item
                for item in spaces
                if item.id == int(
                    requested_space
                )
            ),
            None,
        )

    elif len(spaces) == 1:
        selected_space = spaces[0]

    target_spaces = (
        [selected_space]
        if selected_space
        else spaces
    )

    # -------------------------------------------------
    # MES
    # -------------------------------------------------

    requested_month_text = (
        request.GET
        .get('month', '')
        .strip()
    )

    display_month = None

    if requested_month_text:
        try:
            display_month = (
                datetime.strptime(
                    requested_month_text,
                    '%Y-%m',
                )
                .date()
                .replace(
                    day=1
                )
            )
        except ValueError:
            display_month = None

    if display_month is None:
        display_month = today.replace(
            day=1
        )

    def shift_month(month_date, months):

        month_index = (
            month_date.year * 12
            + month_date.month
            - 1
            + months
        )

        year = month_index // 12
        month = month_index % 12 + 1

        return month_date.replace(
            year=year,
            month=month,
            day=1,
        )

    previous_month = shift_month(
        display_month,
        -1,
    )

    next_month = shift_month(
        display_month,
        1,
    )

    month_end = (
        next_month
        - timedelta(days=1)
    )

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

    month_navigation = [
        {
            'number': month_number,
            'short_name': (
                month_names[
                    month_number
                ][:3]
                .upper()
            ),
            'full_name': (
                month_names[
                    month_number
                ]
            ),
            'query_value': (
                f'{display_month.year}-'
                f'{month_number:02d}'
            ),
            'is_active': (
                month_number
                == display_month.month
            ),
        }
        for month_number
        in range(1, 13)
    ]

    # -------------------------------------------------
    # DÍA SELECCIONADO
    # -------------------------------------------------

    selected_date = parse_date(
        request.GET.get(
            'date',
            ''
        )
    )

    if not (
        selected_date
        and selected_date.year
        == display_month.year
        and selected_date.month
        == display_month.month
    ):
        if (
            today.year
            == display_month.year
            and today.month
            == display_month.month
        ):
            selected_date = today
        else:
            selected_date = display_month

    # -------------------------------------------------
    # RESERVAS DEL MES
    # -------------------------------------------------

    month_bookings = list(
        provider_profile.space_bookings
        .filter(
            space__in=target_spaces,
            session_date__range=(
                display_month,
                month_end,
            ),
        )
        .select_related(
            'space',
            'booked_by',
        )
        .prefetch_related(
            'history__changed_by',
        )
        .order_by(
            'session_date',
            'start_time',
            'id',
        )
    )

    bookings_by_date = {}

    for booking in month_bookings:
        bookings_by_date.setdefault(
            booking.session_date,
            [],
        ).append(booking)

    # -------------------------------------------------
    # HELPERS DE ESTADO
    # -------------------------------------------------

    def provider_rejected_booking(
        booking
    ):
        if (
            booking.status
            != SpaceBooking
            .Status
            .CANCELLED
        ):
            return False

        for history_item in booking.history.all():

            previous_status = (
                (history_item.previous_data or {})
                .get('status')
            )

            if (
                history_item.action
                == SpaceBookingHistory
                .Action
                .CANCELLED
                and previous_status
                == SpaceBooking
                .Status
                .PENDING
                and history_item.changed_by_id
                == request.user.id
            ):
                return True

        return False

    def booking_presentation(
        booking
    ):
        rejected = provider_rejected_booking(
            booking
        )

        if rejected:
            status_label = 'No aceptada'
            status_key = 'cancelled'

        elif (
            booking.session_date < today
            and booking.status
            in {
                SpaceBooking.Status.PENDING,
                SpaceBooking.Status.CONFIRMED,
            }
        ):
            status_label = 'Pasada'
            status_key = 'completed'

        else:
            status_label = (
                booking
                .get_status_display()
            )
            status_key = booking.status

        if (
            booking.status
            == SpaceBooking.Status.PENDING
            and booking.session_date >= today
        ):
            action_label = (
                'Revisar solicitud →'
            )
        elif (
            booking.status
            == SpaceBooking.Status.CONFIRMED
            and booking.session_date >= today
        ):
            action_label = (
                'Ver arriendo →'
            )
        else:
            action_label = (
                'Ver detalle →'
            )

        return {
            'booking': booking,
            'status_label': status_label,
            'status_key': status_key,
            'provider_rejected': rejected,
            'action_label': action_label,
        }

    # -------------------------------------------------
    # CALENDARIO
    # -------------------------------------------------

    month_calendar = pycalendar.Calendar(
        firstweekday=0
    )

    calendar_weeks = []
    month_available_count = 0

    for week in (
        month_calendar
        .monthdatescalendar(
            display_month.year,
            display_month.month,
        )
    ):

        week_cells = []

        for day in week:

            in_display_month = (
                day.month
                == display_month.month
                and day.year
                == display_month.year
            )

            day_bookings = (
                bookings_by_date.get(
                    day,
                    []
                )
                if in_display_month
                else []
            )

            available_count = 0

            if (
                in_display_month
                and day >= today
            ):
                for space in target_spaces:
                    available_count += len(
                        space
                        .generate_reservable_slots_for_date(
                            day
                        )
                    )

                month_available_count += (
                    available_count
                )

            pending_count = sum(
                1
                for booking in day_bookings
                if (
                    booking.status
                    == SpaceBooking.Status.PENDING
                    and booking.session_date >= today
                )
            )

            confirmed_count = sum(
                1
                for booking in day_bookings
                if (
                    booking.status
                    == SpaceBooking.Status.CONFIRMED
                    and booking.session_date >= today
                )
            )

            history_count = (
                len(day_bookings)
                - pending_count
                - confirmed_count
            )

            week_cells.append(
                {
                    'date': day,
                    'in_display_month': (
                        in_display_month
                    ),
                    'is_today': (
                        day == today
                    ),
                    'is_selected': (
                        day == selected_date
                    ),
                    'available_count': (
                        available_count
                    ),
                    'pending_count': (
                        pending_count
                    ),
                    'confirmed_count': (
                        confirmed_count
                    ),
                    'history_count': (
                        history_count
                    ),
                    'has_activity': bool(
                        available_count
                        or day_bookings
                    ),
                }
            )

        calendar_weeks.append(
            week_cells
        )

    # -------------------------------------------------
    # CONTADORES DEL MES
    # -------------------------------------------------

    pending_month_count = sum(
        1
        for booking in month_bookings
        if (
            booking.status
            == SpaceBooking.Status.PENDING
            and booking.session_date >= today
        )
    )

    confirmed_month_count = sum(
        1
        for booking in month_bookings
        if (
            booking.status
            == SpaceBooking.Status.CONFIRMED
            and booking.session_date >= today
        )
    )

    history_month_count = (
        len(month_bookings)
        - pending_month_count
        - confirmed_month_count
    )

    # -------------------------------------------------
    # DISPONIBILIDAD DEL DÍA
    # -------------------------------------------------

    selected_available_slots = []

    if selected_date >= today:

        for space in target_spaces:

            for slot in (
                space
                .generate_reservable_slots_for_date(
                    selected_date
                )
            ):
                selected_available_slots.append(
                    {
                        'space': space,
                        'start_time': (
                            slot['start_time']
                        ),
                        'end_time': (
                            slot['end_time']
                        ),
                        'availability_url': (
                            reverse(
                                'spaces:availability',
                                kwargs={
                                    'space_id': (
                                        space.id
                                    )
                                },
                            )
                            + '?date='
                            + selected_date.isoformat()
                        ),
                    }
                )

    selected_available_slots.sort(
        key=lambda item: (
            item['start_time'],
            item['space'].name,
        )
    )

    # -------------------------------------------------
    # SOLICITUDES / ARRIENDOS DEL DÍA
    # -------------------------------------------------

    selected_active_bookings = []
    selected_history_bookings = []

    for booking in bookings_by_date.get(
        selected_date,
        []
    ):

        item = booking_presentation(
            booking
        )

        item['detail_url'] = reverse(
            'spaces:provider_booking_detail',
            kwargs={
                'booking_id': booking.id
            },
        )

        is_active = (
            booking.session_date >= today
            and booking.status
            in {
                SpaceBooking.Status.PENDING,
                SpaceBooking.Status.CONFIRMED,
            }
        )

        if is_active:
            selected_active_bookings.append(
                item
            )
        else:
            selected_history_bookings.append(
                item
            )

    selected_active_bookings.sort(
        key=lambda item: (
            item['booking'].start_time,
            item['booking'].space_name_snapshot,
        )
    )

    selected_history_bookings.sort(
        key=lambda item: (
            item['booking'].start_time,
            item['booking'].space_name_snapshot,
        )
    )

    # -------------------------------------------------
    # URL DE DISPONIBILIDAD DESDE DÍA SELECCIONADO
    # -------------------------------------------------

    general_space_availability_url = None
    selected_space_availability_url = None

    if selected_space:

        exact_availability_url = reverse(
            'spaces:publish_exact_availability',
            kwargs={
                'space_id': selected_space.id,
            },
        )

        # Dentro del Calendario de arriendos, ambos botones
        # de "Agregar disponibilidad" respetan el día que el
        # proveedor está viendo actualmente.
        general_space_availability_url = (
            exact_availability_url
            + '?date='
            + selected_date.isoformat()
        )

        selected_space_availability_url = (
            exact_availability_url
            + '?date='
            + selected_date.isoformat()
        )

    return render(
        request,
        'spaces/provider_calendar.html',
        {
            'provider_profile': provider_profile,
            'spaces': spaces,
            'selected_space': selected_space,
            'today': today,

            'display_month': (
                display_month
            ),
            'display_month_label': (
                display_month_label
            ),
            'previous_month': (
                previous_month
            ),
            'next_month': (
                next_month
            ),
            'previous_year': (
                display_month.year - 1
            ),
            'next_year': (
                display_month.year + 1
            ),
            'month_navigation': (
                month_navigation
            ),

            'selected_date': (
                selected_date
            ),
            'calendar_weeks': (
                calendar_weeks
            ),

            'month_available_count': (
                month_available_count
            ),
            'pending_month_count': (
                pending_month_count
            ),
            'confirmed_month_count': (
                confirmed_month_count
            ),
            'history_month_count': (
                history_month_count
            ),

            'selected_available_slots': (
                selected_available_slots
            ),
            'selected_active_bookings': (
                selected_active_bookings
            ),
            'selected_history_bookings': (
                selected_history_bookings
            ),

            'general_space_availability_url': (
                general_space_availability_url
            ),
            'selected_space_availability_url': (
                selected_space_availability_url
            ),
            'availability_added': (
                request.GET.get('availability_added')
                == '1'
            ),
            'availability_added_start': (
                request.GET.get('start', '')
            ),
            'availability_added_end': (
                request.GET.get('end', '')
            ),
            'availability_added_blocks': (
                request.GET.get('blocks', '')
            ),
        }
    )




@login_required(
    login_url='accounts:login'
)
def create_space(request):

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile.VerificationStatus.VERIFIED
        or not provider_profile.is_public
    ):
        return redirect('accounts:dashboard')

    if request.method == 'POST':

        form = SpaceCreateForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():

            with transaction.atomic():

                space = form.save(
                    commit=False
                )

                space.provider_profile = provider_profile
                space.publication_status = (
                    Space.PublicationStatus.DRAFT
                )

                space.full_clean()
                space.save()
                form.save_m2m()

                cover_image = form.cleaned_data.get(
                    'cover_image'
                )

                if cover_image:
                    SpaceImage.objects.create(
                        space=space,
                        image=cover_image,
                        is_cover=True,
                        display_order=0,
                    )

                gallery_images = (
                    form.cleaned_data.get(
                        'gallery_images',
                        []
                    )
                    or []
                )

                for index, image in enumerate(
                    gallery_images,
                    start=1,
                ):
                    SpaceImage.objects.create(
                        space=space,
                        image=image,
                        is_cover=False,
                        display_order=index,
                    )

                SpaceHistory.objects.create(
                    space=space,
                    action=SpaceHistory.Action.CREATED,
                    previous_data={},
                    new_data=space.audit_snapshot(),
                    changed_by=request.user,
                    reason=(
                        'Espacio creado desde el '
                        'Centro de Espacios.'
                    ),
                )

            return redirect('spaces:dashboard')

    else:
        form = SpaceCreateForm()

    catalog_context = (
        _space_catalog_recommendation_context()
    )

    return render(
        request,
        'spaces/create_space.html',
        {
            'form': form,
            'provider_profile': provider_profile,
            **catalog_context,
        }
    )


@login_required(
    login_url='accounts:login'
)
def space_detail(request, space_id):
    """
    Ficha privada de un espacio perteneciente al
    Proveedor autenticado.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if provider_profile is None:
        return redirect(
            'accounts:dashboard'
        )

    space = get_object_or_404(
        Space.objects
        .select_related(
            'space_type',
            'commune',
            'commune__region',
            'provider_profile',
        )
        .prefetch_related(
            'equipments',
            'amenities',
            'images',
            'history__changed_by',
        ),
        pk=space_id,
        provider_profile=provider_profile,
    )

    images = list(
        space.images.all()
    )

    cover_image = next(
        (
            image
            for image in images
            if image.is_cover
        ),
        images[0] if images else None,
    )

    history = (
        space.history
        .select_related(
            'changed_by'
        )
        .all()
    )

    publication_missing = []

    if cover_image is None:
        publication_missing.append(
            'Agrega una fotografía principal.'
        )

    can_publish = (
        space.publication_status
        == Space.PublicationStatus.DRAFT
        and not publication_missing
    )

    return render(
        request,
        'spaces/space_detail.html',
        {
            'space': space,
            'cover_image': cover_image,
            'images': images,
            'history': history,
            'can_publish': can_publish,
            'publication_missing': publication_missing,
            'active_availability_count': (
                space.availability_windows
                .filter(
                    is_active=True
                )
                .count()
            ),
            'pending_space_booking_count': (
                space.bookings
                .filter(
                    status=(
                        SpaceBooking
                        .Status
                        .PENDING
                    )
                )
                .count()
            ),
            'confirmed_space_booking_count': (
                space.bookings
                .filter(
                    status=(
                        SpaceBooking
                        .Status
                        .CONFIRMED
                    )
                )
                .count()
            ),
        }
    )


@login_required(
    login_url='accounts:login'
)
def space_history(request, space_id):
    """
    Historial completo del espacio en una vista separada.

    La página principal del recinto queda enfocada en la
    operación diaria, mientras esta vista conserva toda la
    trazabilidad disponible.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    space = get_object_or_404(
        Space.objects
        .select_related(
            'space_type',
            'commune',
            'commune__region',
        ),
        pk=space_id,
        provider_profile=provider_profile,
    )

    history = (
        space.history
        .select_related(
            'changed_by'
        )
        .all()
    )

    return render(
        request,
        'spaces/space_history.html',
        {
            'space': space,
            'history': history,
            'history_count': history.count(),
        }
    )


@login_required(
    login_url='accounts:login'
)
def edit_space(request, space_id):
    """
    Permite editar un espacio propio manteniendo
    trazabilidad de los cambios.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    space = get_object_or_404(
        Space.objects
        .select_related(
            'commune',
            'commune__region',
        )
        .prefetch_related(
            'equipments',
            'amenities',
            'images',
        ),
        pk=space_id,
        provider_profile=provider_profile,
    )

    current_cover = (
        space.images
        .filter(
            is_cover=True
        )
        .order_by(
            'display_order',
            'id',
        )
        .first()
    )

    gallery_images = list(
        space.images
        .filter(
            is_cover=False
        )
        .order_by(
            'display_order',
            'id',
        )
    )

    if request.method == 'POST':

        form = SpaceCreateForm(
            request.POST,
            request.FILES,
            instance=space,
        )

        if form.is_valid():

            with transaction.atomic():

                locked_space = (
                    Space.objects
                    .select_for_update()
                    .get(
                        pk=space.pk,
                        provider_profile=provider_profile,
                    )
                )

                previous_data = (
                    locked_space
                    .audit_snapshot()
                )

                edited_space = form.save(
                    commit=False
                )

                edited_space.provider_profile = (
                    provider_profile
                )

                edited_space.full_clean()
                edited_space.save()

                form.save_m2m()

                new_cover = (
                    form.cleaned_data
                    .get(
                        'cover_image'
                    )
                )

                if new_cover:

                    SpaceImage.objects.filter(
                        space=edited_space,
                        is_cover=True,
                    ).update(
                        is_cover=False
                    )

                    SpaceImage.objects.create(
                        space=edited_space,
                        image=new_cover,
                        is_cover=True,
                        display_order=0,
                    )

                added_gallery_images = (
                    form.cleaned_data.get(
                        'gallery_images',
                        []
                    )
                    or []
                )

                last_display_order = (
                    edited_space.images
                    .order_by(
                        '-display_order',
                        '-id',
                    )
                    .values_list(
                        'display_order',
                        flat=True,
                    )
                    .first()
                    or 0
                )

                for index, image in enumerate(
                    added_gallery_images,
                    start=last_display_order + 1,
                ):
                    SpaceImage.objects.create(
                        space=edited_space,
                        image=image,
                        is_cover=False,
                        display_order=index,
                    )

                SpaceHistory.objects.create(
                    space=edited_space,
                    action=(
                        SpaceHistory
                        .Action
                        .UPDATED
                    ),
                    previous_data=previous_data,
                    new_data=(
                        edited_space
                        .audit_snapshot()
                    ),
                    changed_by=request.user,
                    reason=(
                        'Información del espacio '
                        'actualizada desde el '
                        'Centro de Espacios.'
                    ),
                )

            return redirect(
                'spaces:space_detail',
                space_id=space.id,
            )

    else:

        form = SpaceCreateForm(
            instance=space
        )

    catalog_context = (
        _space_catalog_recommendation_context()
    )

    return render(
        request,
        'spaces/edit_space.html',
        {
            'form': form,
            'space': space,
            'current_cover': current_cover,
            'gallery_images': gallery_images,
            **catalog_context,
        }
    )


@login_required(
    login_url='accounts:login'
)
@require_POST
def publish_space(request, space_id):
    """
    Publica un espacio propio que se encuentre en Borrador.

    La transición se realiza dentro de una transacción y
    queda registrada en SpaceHistory.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    with transaction.atomic():

        space = get_object_or_404(
            Space.objects
            .select_for_update()
            .select_related(
                'provider_profile',
            ),
            pk=space_id,
            provider_profile=provider_profile,
        )

        if (
            space.publication_status
            != Space.PublicationStatus.DRAFT
        ):
            return redirect(
                'spaces:space_detail',
                space_id=space.id,
            )

        has_cover_image = (
            space.images
            .filter(
                is_cover=True
            )
            .exists()
        )

        if not has_cover_image:
            return redirect(
                'spaces:space_detail',
                space_id=space.id,
            )

        previous_data = (
            space.audit_snapshot()
        )

        space.publication_status = (
            Space.PublicationStatus.PUBLISHED
        )

        space.published_at = (
            timezone.now()
        )

        space.full_clean()

        space.save(
            update_fields=[
                'publication_status',
                'published_at',
                'updated_at',
            ]
        )

        SpaceHistory.objects.create(
            space=space,
            action=(
                SpaceHistory
                .Action
                .PUBLISHED
            ),
            previous_data=previous_data,
            new_data=(
                space.audit_snapshot()
            ),
            changed_by=request.user,
            reason=(
                'Espacio publicado desde '
                'el Centro de Espacios.'
            ),
        )

    return redirect(
        'spaces:space_detail',
        space_id=space.id,
    )


def public_space_catalog(request):
    """
    Catálogo público de espacios publicados.
    """

    spaces = (
        Space.objects
        .filter(
            publication_status=(
                Space.PublicationStatus.PUBLISHED
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

    form = PublicSpaceFilterForm(
        request.GET or None
    )

    if form.is_valid():

        q = form.cleaned_data.get(
            'q'
        )

        space_type = form.cleaned_data.get(
            'space_type'
        )

        region = form.cleaned_data.get(
            'region'
        )

        commune = form.cleaned_data.get(
            'commune'
        )

        min_capacity = form.cleaned_data.get(
            'min_capacity'
        )

        max_price = form.cleaned_data.get(
            'max_price'
        )

        equipments = form.cleaned_data.get(
            'equipments'
        )

        amenities = form.cleaned_data.get(
            'amenities'
        )

        if q:
            spaces = spaces.filter(
                Q(
                    name__icontains=q
                )
                | Q(
                    description__icontains=q
                )
                | Q(
                    space_type__name__icontains=q
                )
                | Q(
                    commune__name__icontains=q
                )
                | Q(
                    address__icontains=q
                )
            )

        if space_type:
            spaces = spaces.filter(
                space_type=space_type
            )

        if region:
            spaces = spaces.filter(
                commune__region=region
            )

        if commune:
            spaces = spaces.filter(
                commune=commune
            )

        if min_capacity:
            spaces = spaces.filter(
                capacity__gte=min_capacity
            )

        if max_price:
            spaces = spaces.filter(
                hourly_price_clp__lte=max_price
            )

        if equipments:
            for equipment in equipments:
                spaces = spaces.filter(
                    equipments=equipment
                )

        if amenities:
            for amenity in amenities:
                spaces = spaces.filter(
                    amenities=amenity
                )

    spaces = spaces.distinct()

    space_cards = []

    for space in spaces:

        images = list(
            space.images.all()
        )

        cover_image = next(
            (
                image
                for image in images
                if image.is_cover
            ),
            images[0] if images else None,
        )

        space_cards.append(
            {
                'space': space,
                'cover_image': cover_image,
            }
        )

    return render(
        request,
        'spaces/public_catalog.html',
        {
            'form': form,
            'space_cards': space_cards,
            'result_count': len(
                space_cards
            ),
        }
    )


def public_space_detail(request, space_id):
    """
    Ficha pública de un espacio publicado.
    """

    space = get_object_or_404(
        Space.objects
        .filter(
            publication_status=(
                Space.PublicationStatus.PUBLISHED
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
        ),
        pk=space_id,
    )

    images = list(
        space.images.all()
    )

    cover_image = next(
        (
            image
            for image in images
            if image.is_cover
        ),
        images[0] if images else None,
    )

    gallery_images = [
        image
        for image in images
        if (
            cover_image is None
            or image.id != cover_image.id
        )
    ]

    return render(
        request,
        'spaces/public_detail.html',
        {
            'space': space,
            'cover_image': cover_image,
            'gallery_images': gallery_images,
            'has_active_availability': (
                space.availability_windows
                .filter(
                    is_active=True
                )
                .exists()
                or space.availability_exceptions
                .filter(
                    is_active=True,
                    date__gte=timezone.localdate(),
                    exception_type=(
                        SpaceAvailabilityException
                        .ExceptionType
                        .SPECIAL_HOURS
                    ),
                )
                .exists()
            ),
        }
    )


@login_required(
    login_url='accounts:login'
)
def publish_space_exact_availability(
    request,
    space_id,
):
    """
    Publica disponibilidad para una fecha exacta.

    Esta pantalla NO crea disponibilidad semanal.
    Utiliza una excepción SPECIAL_HOURS para que el
    horario afecte solamente al día seleccionado.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    space = get_object_or_404(
        Space.objects.select_related(
            'space_type',
            'commune',
            'commune__region',
        ),
        pk=space_id,
        provider_profile=provider_profile,
    )

    today = timezone.localdate()

    focus_date = parse_date(
        request.GET.get(
            'date',
            ''
        )
    )

    if (
        focus_date is None
        or focus_date < today
    ):
        focus_date = today

    if request.method == 'POST':

        post_data = request.POST.copy()

        # Este flujo siempre publica horas especiales
        # para UNA fecha exacta.
        post_data['exception_type'] = (
            SpaceAvailabilityException
            .ExceptionType
            .SPECIAL_HOURS
        )

        form = SpaceAvailabilityExceptionForm(
            post_data
        )

        if form.is_valid():

            exception = form.save(
                commit=False
            )

            exception.space = space
            exception.is_active = True
            exception.created_by = request.user
            exception.reason = (
                'Disponibilidad publicada desde '
                'el Calendario de arriendos.'
            )

            start_dt = datetime.combine(
                exception.date,
                exception.start_time,
            )

            end_dt = datetime.combine(
                exception.date,
                exception.end_time,
            )

            duration_minutes = int(
                (
                    end_dt
                    - start_dt
                )
                .total_seconds()
                // 60
            )

            if duration_minutes <= 0:

                form.add_error(
                    'end_time',
                    (
                        'La hora de término debe ser '
                        'posterior a la hora de inicio.'
                    ),
                )

            elif duration_minutes < 60:

                form.add_error(
                    'end_time',
                    (
                        'La disponibilidad debe durar '
                        'al menos 60 minutos.'
                    ),
                )

            elif duration_minutes % 60 != 0:

                form.add_error(
                    'end_time',
                    (
                        'Usa una duración formada por '
                        'bloques completos de 60 minutos.'
                    ),
                )

            existing_exception = (
                space
                .availability_exceptions
                .filter(
                    date=exception.date,
                    is_active=True,
                )
                .first()
            )

            if existing_exception:

                form.add_error(
                    'date',
                    (
                        'Ya existe una configuración '
                        'específica para esta fecha. '
                        'Puedes administrarla desde '
                        'Gestionar disponibilidad.'
                    ),
                )

            if not form.errors:

                try:
                    exception.full_clean()

                except ValidationError as exc:

                    for message in exc.messages:
                        form.add_error(
                            None,
                            message
                        )

                else:

                    with transaction.atomic():

                        exception.save()

                        SpaceAvailabilityExceptionHistory.objects.create(
                            exception=exception,
                            action=(
                                SpaceAvailabilityExceptionHistory
                                .Action
                                .CREATED
                            ),
                            previous_data={},
                            new_data=(
                                exception.audit_snapshot()
                            ),
                            changed_by=request.user,
                            reason=(
                                'Disponibilidad para fecha '
                                'exacta publicada desde el '
                                'Calendario de arriendos.'
                            ),
                        )

                    calendar_url = reverse(
                        'spaces:provider_calendar'
                    )

                    query_string = urlencode(
                        {
                            'month': (
                                exception.date.strftime(
                                    '%Y-%m'
                                )
                            ),
                            'date': (
                                exception.date.isoformat()
                            ),
                            'space': space.id,
                            'availability_added': 1,
                            'start': (
                                exception.start_time.strftime(
                                    '%H:%M'
                                )
                            ),
                            'end': (
                                exception.end_time.strftime(
                                    '%H:%M'
                                )
                            ),
                            'blocks': (
                                duration_minutes // 60
                            ),
                        }
                    )

                    return redirect(
                        (
                            f'{calendar_url}'
                            f'?{query_string}'
                            f'#disponibilidad-publicada'
                        )
                    )

    else:

        form = SpaceAvailabilityExceptionForm(
            initial={
                'date': focus_date,
                'exception_type': (
                    SpaceAvailabilityException
                    .ExceptionType
                    .SPECIAL_HOURS
                ),
            }
        )

    return render(
        request,
        'spaces/publish_exact_availability.html',
        {
            'provider_profile': provider_profile,
            'space': space,
            'form': form,
            'focus_date': focus_date,
        }
    )


@login_required(
    login_url='accounts:login'
)
def space_availability(request, space_id):
    """
    Gestiona disponibilidad semanal recurrente y
    excepciones para fechas específicas.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    provider_spaces = list(
        provider_profile.spaces
        .select_related(
            'space_type',
            'commune',
            'commune__region',
        )
        .order_by(
            'name',
            'id',
        )
    )

    space = get_object_or_404(
        Space.objects.select_related(
            'space_type',
            'commune',
            'commune__region',
        ),
        pk=space_id,
        provider_profile=provider_profile,
    )

    calendar_focus_date = parse_date(
        request.GET.get(
            'date',
            ''
        )
    )

    if (
        calendar_focus_date
        and calendar_focus_date
        < timezone.localdate()
    ):
        calendar_focus_date = None

    form_type = request.POST.get(
        'form_type',
        'weekly',
    )

    if request.method == 'POST' and form_type == 'exception':

        form = SpaceAvailabilityForm()

        exception_form = (
            SpaceAvailabilityExceptionForm(
                request.POST
            )
        )

        if exception_form.is_valid():

            exception = exception_form.save(
                commit=False
            )

            exception.space = space
            exception.is_active = True
            exception.created_by = request.user

            try:
                exception.full_clean()

            except ValidationError as exc:

                for message in exc.messages:
                    exception_form.add_error(
                        None,
                        message
                    )

            else:

                with transaction.atomic():

                    exception.save()

                    SpaceAvailabilityExceptionHistory.objects.create(
                        exception=exception,
                        action=(
                            SpaceAvailabilityExceptionHistory
                            .Action
                            .CREATED
                        ),
                        previous_data={},
                        new_data=(
                            exception.audit_snapshot()
                        ),
                        changed_by=request.user,
                        reason=(
                            exception.reason
                            or (
                                'Excepción de disponibilidad '
                                'creada desde el Centro de Espacios.'
                            )
                        ),
                    )

                return redirect(
                    'spaces:availability',
                    space_id=space.id,
                )

    elif request.method == 'POST':

        exception_form = (
            SpaceAvailabilityExceptionForm()
        )

        form = SpaceAvailabilityForm(
            request.POST
        )

        if form.is_valid():

            availability = form.save(
                commit=False
            )

            availability.space = space
            availability.is_active = True

            try:
                availability.full_clean()

            except ValidationError as exc:

                for message in exc.messages:
                    form.add_error(
                        None,
                        message
                    )

            else:

                with transaction.atomic():

                    availability.save()

                    SpaceAvailabilityHistory.objects.create(
                        availability=availability,
                        action=(
                            SpaceAvailabilityHistory
                            .Action
                            .CREATED
                        ),
                        previous_data={},
                        new_data=(
                            availability
                            .audit_snapshot()
                        ),
                        changed_by=request.user,
                        reason=(
                            'Disponibilidad semanal creada '
                            'desde el Centro de Espacios.'
                        ),
                    )

                return redirect(
                    'spaces:availability',
                    space_id=space.id,
                )

    else:

        form = SpaceAvailabilityForm()

        exception_initial = {}

        if calendar_focus_date:
            exception_initial['date'] = (
                calendar_focus_date
            )
            exception_initial[
                'exception_type'
            ] = (
                SpaceAvailabilityException
                .ExceptionType
                .SPECIAL_HOURS
            )

        exception_form = (
            SpaceAvailabilityExceptionForm(
                initial=exception_initial
            )
        )

    availability_windows = (
        space.availability_windows
        .all()
        .order_by(
            'weekday',
            'start_time',
            'valid_from',
        )
    )

    active_windows = [
        item
        for item in availability_windows
        if item.is_active
    ]

    inactive_windows = [
        item
        for item in availability_windows
        if not item.is_active
    ]

    exact_date_reason = (
        EXACT_DATE_AVAILABILITY_REASON
    )

    exceptions = list(
        space.availability_exceptions
        .all()
        .order_by(
            'date',
            'created_at',
        )
    )

    exact_date_exceptions = [
        item
        for item in exceptions
        if (
            item.is_active
            and item.reason == exact_date_reason
        )
    ]

    inactive_exact_date_exceptions = [
        item
        for item in exceptions
        if (
            not item.is_active
            and item.reason == exact_date_reason
        )
    ]

    manual_active_exceptions = [
        item
        for item in exceptions
        if (
            item.is_active
            and item.reason != exact_date_reason
        )
    ]

    manual_inactive_exceptions = [
        item
        for item in exceptions
        if (
            not item.is_active
            and item.reason != exact_date_reason
        )
    ]

    history = list(
        SpaceAvailabilityHistory.objects
        .filter(
            availability__space=space
        )
        .select_related(
            'availability',
            'changed_by',
        )
        .order_by(
            '-created_at',
            '-id',
        )
    )

    exception_history = list(
        SpaceAvailabilityExceptionHistory.objects
        .filter(
            exception__space=space
        )
        .select_related(
            'exception',
            'changed_by',
        )
        .order_by(
            '-created_at',
            '-id',
        )
    )

    exact_date_history = [
        event
        for event in exception_history
        if event.exception.reason == exact_date_reason
    ]

    manual_exception_history = [
        event
        for event in exception_history
        if event.exception.reason != exact_date_reason
    ]

    total_history_count = (
        len(history)
        + len(exception_history)
    )

    availability_feedback = request.GET.get(
        'feedback',
        ''
    )

    availability_feedback_date = request.GET.get(
        'feedback_date',
        ''
    )

    availability_feedback_start = request.GET.get(
        'feedback_start',
        ''
    )

    availability_feedback_end = request.GET.get(
        'feedback_end',
        ''
    )

    return render(
        request,
        'spaces/availability.html',
        {
            'space': space,
            'provider_spaces': provider_spaces,
            'provider_space_count': len(provider_spaces),
            'form': form,
            'exception_form': exception_form,
            'active_windows': active_windows,
            'inactive_windows': inactive_windows,
            'active_count': len(
                active_windows
            ),
            'exact_date_exceptions': exact_date_exceptions,
            'inactive_exact_date_exceptions': (
                inactive_exact_date_exceptions
            ),
            'exact_date_count': len(
                exact_date_exceptions
            ),
            'manual_active_exceptions': (
                manual_active_exceptions
            ),
            'manual_inactive_exceptions': (
                manual_inactive_exceptions
            ),
            'manual_exception_count': len(
                manual_active_exceptions
            ),
            'history': history,
            'history_count': len(history),
            'exception_history': exception_history,
            'exact_date_history': exact_date_history,
            'exact_date_history_count': len(
                exact_date_history
            ),
            'manual_exception_history': (
                manual_exception_history
            ),
            'manual_exception_history_count': len(
                manual_exception_history
            ),
            'total_history_count': total_history_count,
            'status_error': request.GET.get(
                'status_error'
            ),
            'exception_error': request.GET.get(
                'exception_error'
            ),
            'calendar_focus_date': (
                calendar_focus_date
            ),

            'availability_feedback': (
                availability_feedback
            ),

            'availability_feedback_date': (
                availability_feedback_date
            ),

            'availability_feedback_start': (
                availability_feedback_start
            ),

            'availability_feedback_end': (
                availability_feedback_end
            ),
        }
    )


@login_required(
    login_url='accounts:login'
)
@require_POST
def set_space_availability_status(
    request,
    space_id,
    availability_id,
):
    """
    Activa o desactiva una disponibilidad sin eliminarla.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    space = get_object_or_404(
        Space,
        pk=space_id,
        provider_profile=provider_profile,
    )

    action = request.POST.get(
        'action'
    )

    with transaction.atomic():

        availability = get_object_or_404(
            SpaceAvailability.objects
            .select_for_update(),
            pk=availability_id,
            space=space,
        )

        previous_data = (
            availability.audit_snapshot()
        )

        if (
            action == 'deactivate'
            and availability.is_active
        ):

            availability.is_active = False

            availability.save(
                update_fields=[
                    'is_active',
                    'updated_at',
                ]
            )

            history_action = (
                SpaceAvailabilityHistory
                .Action
                .DEACTIVATED
            )

            reason = (
                'Disponibilidad desactivada '
                'desde el Centro de Espacios.'
            )

        elif (
            action == 'activate'
            and not availability.is_active
        ):

            availability.is_active = True

            try:
                availability.full_clean()

            except ValidationError:

                url = reverse(
                    'spaces:availability',
                    kwargs={
                        'space_id': space.id,
                    }
                )

                return redirect(
                    f'{url}?status_error=overlap'
                )

            availability.save(
                update_fields=[
                    'is_active',
                    'updated_at',
                ]
            )

            history_action = (
                SpaceAvailabilityHistory
                .Action
                .ACTIVATED
            )

            reason = (
                'Disponibilidad reactivada '
                'desde el Centro de Espacios.'
            )

        else:

            return redirect(
                'spaces:availability',
                space_id=space.id,
            )

        SpaceAvailabilityHistory.objects.create(
            availability=availability,
            action=history_action,
            previous_data=previous_data,
            new_data=(
                availability.audit_snapshot()
            ),
            changed_by=request.user,
            reason=reason,
        )

    feedback = (
        'weekly_deactivated'
        if history_action
        == SpaceAvailabilityHistory.Action.DEACTIVATED
        else 'weekly_activated'
    )

    query = urlencode(
        {
            'feedback': feedback,
        }
    )

    url = reverse(
        'spaces:availability',
        kwargs={
            'space_id': space.id,
        }
    )

    return redirect(
        f'{url}?{query}#cambio-disponibilidad'
    )



@login_required(
    login_url='accounts:login'
)
@require_POST
def set_space_availability_exception_status(
    request,
    space_id,
    exception_id,
):
    """
    Activa o desactiva una excepción sin eliminarla.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    space = get_object_or_404(
        Space,
        pk=space_id,
        provider_profile=provider_profile,
    )

    action = request.POST.get(
        'action'
    )

    with transaction.atomic():

        exception = get_object_or_404(
            SpaceAvailabilityException.objects
            .select_for_update(),
            pk=exception_id,
            space=space,
        )

        previous_data = (
            exception.audit_snapshot()
        )

        is_exact_date_availability = (
            exception.reason
            == EXACT_DATE_AVAILABILITY_REASON
        )

        if (
            action == 'deactivate'
            and exception.is_active
        ):

            exception.is_active = False

            exception.save(
                update_fields=[
                    'is_active',
                    'updated_at',
                ]
            )

            history_action = (
                SpaceAvailabilityExceptionHistory
                .Action
                .DEACTIVATED
            )

            reason = (
                'Excepción desactivada desde '
                'el Centro de Espacios.'
            )

        elif (
            action == 'activate'
            and not exception.is_active
        ):

            if exception.date < timezone.localdate():

                url = reverse(
                    'spaces:availability',
                    kwargs={
                        'space_id': space.id,
                    }
                )

                return redirect(
                    f'{url}?exception_error=past'
                )

            exception.is_active = True

            try:
                exception.full_clean()

            except ValidationError:

                url = reverse(
                    'spaces:availability',
                    kwargs={
                        'space_id': space.id,
                    }
                )

                return redirect(
                    f'{url}?exception_error=conflict'
                )

            exception.save(
                update_fields=[
                    'is_active',
                    'updated_at',
                ]
            )

            history_action = (
                SpaceAvailabilityExceptionHistory
                .Action
                .ACTIVATED
            )

            reason = (
                'Excepción reactivada desde '
                'el Centro de Espacios.'
            )

        else:

            return redirect(
                'spaces:availability',
                space_id=space.id,
            )

        SpaceAvailabilityExceptionHistory.objects.create(
            exception=exception,
            action=history_action,
            previous_data=previous_data,
            new_data=(
                exception.audit_snapshot()
            ),
            changed_by=request.user,
            reason=reason,
        )

    if is_exact_date_availability:

        feedback = (
            'date_deactivated'
            if history_action
            == SpaceAvailabilityExceptionHistory
            .Action
            .DEACTIVATED
            else 'date_activated'
        )

    else:

        feedback = (
            'exception_deactivated'
            if history_action
            == SpaceAvailabilityExceptionHistory
            .Action
            .DEACTIVATED
            else 'exception_activated'
        )

    feedback_data = {
        'feedback': feedback,
        'feedback_date': (
            exception.date.strftime(
                '%d/%m/%Y'
            )
        ),
    }

    if (
        exception.start_time
        and exception.end_time
    ):

        feedback_data[
            'feedback_start'
        ] = exception.start_time.strftime(
            '%H:%M'
        )

        feedback_data[
            'feedback_end'
        ] = exception.end_time.strftime(
            '%H:%M'
        )

    query = urlencode(
        feedback_data
    )

    url = reverse(
        'spaces:availability',
        kwargs={
            'space_id': space.id,
        }
    )

    return redirect(
        f'{url}?{query}#cambio-disponibilidad'
    )

def public_space_slots(request, space_id):
    """
    Calendario público mensual con horizonte de 12 meses.

    Las excepciones de fecha tienen prioridad sobre
    la disponibilidad semanal recurrente.
    """

    space = get_object_or_404(
        Space.objects
        .filter(
            publication_status=(
                Space.PublicationStatus.PUBLISHED
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
            'availability_windows',
            'availability_exceptions',
        ),
        pk=space_id,
    )

    today = timezone.localdate()

    horizon_end = (
        today
        + timedelta(
            days=365
        )
    )

    first_allowed_month = today.replace(
        day=1
    )

    last_allowed_month = horizon_end.replace(
        day=1
    )

    requested_date = parse_date(
        request.GET.get(
            'date',
            ''
        )
    )

    selected_day_value = request.GET.get(
        'day',
        ''
    ).strip()

    selected_month_value = request.GET.get(
        'month_number',
        ''
    ).strip()

    selected_year_value = request.GET.get(
        'year',
        ''
    ).strip()

    if (
        not requested_date
        and selected_day_value.isdigit()
        and selected_month_value.isdigit()
        and selected_year_value.isdigit()
    ):
        requested_date = parse_date(
            f'{selected_year_value}-'
            f'{int(selected_month_value):02d}-'
            f'{int(selected_day_value):02d}'
        )

    if not (
        requested_date
        and today <= requested_date <= horizon_end
    ):
        requested_date = None

    selected_date = requested_date

    requested_month_text = (
        request.GET.get(
            'month',
            ''
        )
        .strip()
    )

    requested_month = None

    if requested_month_text:

        try:
            requested_month = (
                datetime.strptime(
                    requested_month_text,
                    '%Y-%m',
                )
                .date()
                .replace(
                    day=1
                )
            )
        except ValueError:
            requested_month = None

    if selected_date:
        display_month = selected_date.replace(
            day=1
        )

    elif (
        requested_month
        and first_allowed_month
        <= requested_month
        <= last_allowed_month
    ):
        display_month = requested_month

    else:
        display_month = first_allowed_month

    def shift_month(month_date, months):

        month_index = (
            month_date.year * 12
            + month_date.month
            - 1
            + months
        )

        year = month_index // 12
        month = month_index % 12 + 1

        return month_date.replace(
            year=year,
            month=month,
            day=1,
        )

    previous_month = shift_month(
        display_month,
        -1,
    )

    next_month = shift_month(
        display_month,
        1,
    )

    if previous_month < first_allowed_month:
        previous_month = None

    if next_month > last_allowed_month:
        next_month = None

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

    active_windows = [
        window
        for window in (
            space.availability_windows.all()
        )
        if window.is_active
    ]

    active_exception_map = {
        item.date: item
        for item in (
            space.availability_exceptions.all()
        )
        if item.is_active
    }

    def date_has_recurring_window(target_date):

        return any(
            window.weekday == target_date.weekday()
            and window.valid_from <= target_date
            and (
                window.valid_until is None
                or window.valid_until >= target_date
            )
            for window in active_windows
        )

    month_calendar = pycalendar.Calendar(
        firstweekday=0
    )

    calendar_weeks = []

    for week in month_calendar.monthdatescalendar(
        display_month.year,
        display_month.month,
    ):

        week_cells = []

        for day in week:

            in_display_month = (
                day.month == display_month.month
                and day.year == display_month.year
            )

            in_horizon = (
                today <= day <= horizon_end
            )

            exception = (
                active_exception_map.get(
                    day
                )
            )

            has_configured_window = False
            available_slot_count = 0

            if (
                in_display_month
                and in_horizon
            ):

                if (
                    exception
                    and exception.exception_type
                    == SpaceAvailabilityException
                    .ExceptionType
                    .BLOCKED
                ):
                    status = 'blocked'

                else:

                    has_configured_window = (
                        bool(
                            exception
                            and exception.exception_type
                            == SpaceAvailabilityException
                            .ExceptionType
                            .SPECIAL_HOURS
                        )
                        or date_has_recurring_window(
                            day
                        )
                    )

                    if has_configured_window:

                        available_slot_count = len(
                            space
                            .generate_reservable_slots_for_date(
                                day
                            )
                        )

                    if available_slot_count > 0:
                        status = 'available'

                    elif has_configured_window:
                        status = 'unavailable'

                    else:
                        status = 'no_schedule'

            elif not in_display_month:
                status = 'outside'

            elif day < today:
                status = 'past'

            else:
                status = 'outside'

            week_cells.append(
                {
                    'date': day,
                    'day_number': day.day,
                    'in_display_month': (
                        in_display_month
                    ),
                    'in_horizon': in_horizon,
                    'status': status,
                    'has_configured_window': (
                        has_configured_window
                    ),
                    'available_slot_count': (
                        available_slot_count
                    ),
                    'is_today': day == today,
                    'is_selected': (
                        selected_date == day
                    ),
                    'has_exception': (
                        exception is not None
                    ),
                    'exception_type': (
                        exception.exception_type
                        if exception
                        else ''
                    ),
                }
            )

        calendar_weeks.append(
            week_cells
        )

    selected_slots = []

    if selected_date:
        selected_slots = (
            space
            .generate_reservable_slots_for_date(
                selected_date
            )
        )

    selected_exception = (
        active_exception_map.get(
            selected_date
        )
        if selected_date
        else None
    )

    return render(
        request,
        'spaces/public_availability.html',
        {
            'space': space,
            'today': today,
            'horizon_end': horizon_end,
            'display_month': display_month,
            'display_month_label': (
                display_month_label
            ),
            'previous_month': previous_month,
            'next_month': next_month,
            'calendar_weeks': calendar_weeks,
            'selected_date': selected_date,
            'selected_slots': selected_slots,
            'selected_exception': selected_exception,
            'slot_count': len(
                selected_slots
            ),
            'day_options': range(1, 32),
            'month_options': (
                (1, 'Enero'),
                (2, 'Febrero'),
                (3, 'Marzo'),
                (4, 'Abril'),
                (5, 'Mayo'),
                (6, 'Junio'),
                (7, 'Julio'),
                (8, 'Agosto'),
                (9, 'Septiembre'),
                (10, 'Octubre'),
                (11, 'Noviembre'),
                (12, 'Diciembre'),
            ),
            'year_options': range(
                today.year,
                horizon_end.year + 1,
            ),
            'is_owner': (
                request.user.is_authenticated
                and request.user.id
                == space.provider_profile.user_id
            ),
        }
    )


@login_required(
    login_url='accounts:login'
)
def confirm_space_booking(request, space_id):
    """
    Revisa y crea una reserva Pendiente para un bloque
    de 60 minutos de un espacio publicado.
    """

    space = get_object_or_404(
        Space.objects
        .filter(
            publication_status=(
                Space.PublicationStatus.PUBLISHED
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
        ),
        pk=space_id,
    )

    is_owner = (
        request.user.id
        == space.provider_profile.user_id
    )

    booking_error = None
    session_date = None
    start_time = None
    end_time = None

    if request.method == 'POST':

        form = SpaceBookingCreateForm(
            request.POST
        )

        if form.is_valid():

            session_date = (
                form.cleaned_data[
                    'session_date'
                ]
            )

            start_time = (
                form.cleaned_data[
                    'start_time'
                ]
            )

            end_time = (
                form.cleaned_data[
                    'end_time'
                ]
            )

            if is_owner:
                booking_error = (
                    'No puedes reservar un espacio '
                    'administrado por tu propia cuenta.'
                )

            else:

                try:

                    with transaction.atomic():

                        locked_space = (
                            Space.objects
                            .select_for_update()
                            .select_related(
                                'space_type',
                                'commune',
                                'provider_profile',
                                'provider_profile__user',
                            )
                            .get(
                                pk=space.id
                            )
                        )

                        available_slots = (
                            locked_space
                            .generate_reservable_slots_for_date(
                                session_date
                            )
                        )

                        slot_exists = any(
                            slot['start_time']
                            == start_time
                            and slot['end_time']
                            == end_time
                            for slot in available_slots
                        )

                        if not slot_exists:
                            raise ValidationError(
                                (
                                    'El bloque seleccionado ya '
                                    'no se encuentra disponible.'
                                )
                            )

                        booking = SpaceBooking(
                            booked_by=request.user,
                            space=locked_space,
                            provider_profile=(
                                locked_space
                                .provider_profile
                            ),
                            session_date=session_date,
                            start_time=start_time,
                            end_time=end_time,
                            duration_minutes=60,
                            price_clp=(
                                locked_space
                                .hourly_price_clp
                            ),
                            status=(
                                SpaceBooking
                                .Status
                                .PENDING
                            ),
                        )

                        booking.save()

                        SpaceBookingHistory.objects.create(
                            booking=booking,
                            action=(
                                SpaceBookingHistory
                                .Action
                                .CREATED
                            ),
                            previous_data={},
                            new_data=(
                                booking
                                .audit_snapshot()
                            ),
                            changed_by=request.user,
                            reason=(
                                'Reserva creada desde '
                                'la selección de un '
                                'bloque disponible.'
                            ),
                        )

                    return redirect(
                        'spaces:booking_detail',
                        booking_id=booking.id,
                    )

                except ValidationError as exc:

                    booking_error = (
                        exc.messages[0]
                        if exc.messages
                        else (
                            'No fue posible crear '
                            'la reserva.'
                        )
                    )

    else:

        initial = {
            'session_date': request.GET.get(
                'date',
                ''
            ),
            'start_time': request.GET.get(
                'start',
                ''
            ),
            'end_time': request.GET.get(
                'end',
                ''
            ),
        }

        form = SpaceBookingCreateForm(
            initial=initial
        )

        session_date = parse_date(
            initial['session_date']
        )

        try:
            start_time = datetime.strptime(
                initial['start_time'],
                '%H:%M',
            ).time()
        except (
            TypeError,
            ValueError,
        ):
            start_time = None

        try:
            end_time = datetime.strptime(
                initial['end_time'],
                '%H:%M',
            ).time()
        except (
            TypeError,
            ValueError,
        ):
            end_time = None

        if not all([
            session_date,
            start_time,
            end_time,
        ]):
            booking_error = (
                'El bloque seleccionado no es válido.'
            )

        elif not is_owner:

            available_slots = (
                space
                .generate_reservable_slots_for_date(
                    session_date
                )
            )

            slot_exists = any(
                slot['start_time']
                == start_time
                and slot['end_time']
                == end_time
                for slot in available_slots
            )

            if not slot_exists:
                booking_error = (
                    'El bloque seleccionado ya '
                    'no se encuentra disponible.'
                )

        else:
            booking_error = (
                'No puedes reservar un espacio '
                'administrado por tu propia cuenta.'
            )

    return render(
        request,
        'spaces/confirm_space_booking.html',
        {
            'space': space,
            'form': form,
            'session_date': session_date,
            'start_time': start_time,
            'end_time': end_time,
            'booking_error': booking_error,
            'is_owner': is_owner,
        }
    )


@login_required(
    login_url='accounts:login'
)
def space_booking_detail(request, booking_id):
    """
    Detalle de una reserva de espacio perteneciente
    al miembro autenticado.
    """

    booking = get_object_or_404(
        SpaceBooking.objects
        .select_related(
            'space',
            'provider_profile',
            'provider_profile__user',
            'booked_by',
        )
        .prefetch_related(
            'history__changed_by',
        ),
        pk=booking_id,
        booked_by=request.user,
    )

    history = (
        booking.history
        .select_related(
            'changed_by'
        )
        .all()
    )

    current_timezone = (
        timezone.get_current_timezone()
    )

    session_start = timezone.make_aware(
        datetime.combine(
            booking.session_date,
            booking.start_time,
        ),
        current_timezone,
    )

    can_cancel = (
        booking.status
        in [
            SpaceBooking.Status.PENDING,
            SpaceBooking.Status.CONFIRMED,
        ]
        and timezone.localtime()
        < session_start
    )

    return render(
        request,
        'spaces/space_booking_detail.html',
        {
            'booking': booking,
            'history': history,
            'can_cancel': can_cancel,
            'cancel_error': request.GET.get(
                'cancel_error'
            ),
        }
    )


@login_required(
    login_url='accounts:login'
)
def provider_received_space_bookings(request):
    """
    Centro de gestión de reservas recibidas por el
    Proveedor de Espacios autenticado.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    today = timezone.localdate()

    bookings = (
        SpaceBooking.objects
        .filter(
            provider_profile=provider_profile
        )
        .select_related(
            'space',
            'booked_by',
        )
        .prefetch_related(
            'history__changed_by',
        )
    )

    # -------------------------------------------------
    # PRÓXIMOS
    # -------------------------------------------------
    # Solo deben considerarse "próximos" aquellos
    # arriendos cuya fecha aún no ha pasado.

    pending_bookings = (
        bookings
        .filter(
            status=(
                SpaceBooking
                .Status
                .PENDING
            ),
            session_date__gte=today,
        )
        .order_by(
            'session_date',
            'start_time',
            '-created_at',
        )
    )

    confirmed_bookings = (
        bookings
        .filter(
            status=(
                SpaceBooking
                .Status
                .CONFIRMED
            ),
            session_date__gte=today,
        )
        .order_by(
            'session_date',
            'start_time',
            '-created_at',
        )
    )

    upcoming_bookings = (
        bookings
        .filter(
            status__in=[
                SpaceBooking
                .Status
                .PENDING,
                SpaceBooking
                .Status
                .CONFIRMED,
            ],
            session_date__gte=today,
        )
        .order_by(
            'session_date',
            'start_time',
            '-created_at',
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
        bookings
        .filter(
            Q(
                status__in=[
                    SpaceBooking
                    .Status
                    .CANCELLED,
                    SpaceBooking
                    .Status
                    .COMPLETED,
                ]
            )
            |
            Q(
                status__in=[
                    SpaceBooking
                    .Status
                    .PENDING,
                    SpaceBooking
                    .Status
                    .CONFIRMED,
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

    for history_booking in history_bookings:

        history_booking.provider_rejected = False

        if (
            history_booking.status
            == SpaceBooking
            .Status
            .CANCELLED
        ):
            for history_item in history_booking.history.all():

                previous_status = (
                    (history_item.previous_data or {})
                    .get('status')
                )

                if (
                    history_item.action
                    == SpaceBookingHistory
                    .Action
                    .CANCELLED
                    and previous_status
                    == SpaceBooking
                    .Status
                    .PENDING
                    and history_item.changed_by_id
                    == request.user.id
                ):
                    history_booking.provider_rejected = True
                    break

        # Etiqueta humana solo para presentación.
        if history_booking.provider_rejected:
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
                SpaceBooking.Status.PENDING,
                SpaceBooking.Status.CONFIRMED,
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
                history_booking
                .get_status_display()
            )
            history_booking.ui_status_key = (
                history_booking.status
            )

    return render(
        request,
        'spaces/provider_received_bookings.html',
        {
            'provider_profile': provider_profile,
            'pending_bookings': pending_bookings,
            'confirmed_bookings': confirmed_bookings,
            'upcoming_bookings': upcoming_bookings,
            'history_bookings': history_bookings,
            'pending_count': pending_bookings.count(),
            'confirmed_count': confirmed_bookings.count(),
            'history_count': len(history_bookings),
            'total_count': bookings.count(),
        }
    )


@login_required(
    login_url='accounts:login'
)
def provider_space_booking_detail(
    request,
    booking_id,
):
    """
    Detalle de una reserva recibida por el Proveedor.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    booking = get_object_or_404(
        SpaceBooking.objects
        .select_related(
            'space',
            'booked_by',
            'provider_profile',
        )
        .prefetch_related(
            'history__changed_by',
        ),
        pk=booking_id,
        provider_profile=provider_profile,
    )

    history = (
        booking.history
        .select_related(
            'changed_by'
        )
        .all()
    )

    # Diferencia entre:
    # - solicitud pendiente rechazada por el proveedor;
    # - reserva ya aceptada que después fue cancelada.
    provider_rejected = False

    if (
        booking.status
        == SpaceBooking
        .Status
        .CANCELLED
    ):
        for history_item in history:

            previous_status = (
                (history_item.previous_data or {})
                .get('status')
            )

            if (
                history_item.action
                == SpaceBookingHistory
                .Action
                .CANCELLED
                and previous_status
                == SpaceBooking
                .Status
                .PENDING
                and history_item.changed_by_id
                == request.user.id
            ):
                provider_rejected = True
                break

    # Etiquetas humanas para el historial visible
    # dentro del detalle.
    for history_item in history:

        history_item.ui_action_label = (
            history_item.get_action_display()
        )

        previous_status = (
            (history_item.previous_data or {})
            .get('status')
        )

        if (
            history_item.action
            == SpaceBookingHistory
            .Action
            .CANCELLED
            and previous_status
            == SpaceBooking
            .Status
            .PENDING
            and history_item.changed_by_id
            == request.user.id
        ):
            history_item.ui_action_label = (
                'Solicitud no aceptada'
            )

    current_timezone = (
        timezone.get_current_timezone()
    )

    session_end = timezone.make_aware(
        datetime.combine(
            booking.session_date,
            booking.end_time,
        ),
        current_timezone,
    )

    now = timezone.localtime()

    can_complete = (
        booking.status
        == SpaceBooking
        .Status
        .CONFIRMED
        and now >= session_end
    )

    completion_waiting = (
        booking.status
        == SpaceBooking
        .Status
        .CONFIRMED
        and now < session_end
    )

    return render(
        request,
        'spaces/provider_booking_detail.html',
        {
            'booking': booking,
            'history': history,
            'provider_rejected': (
                provider_rejected
            ),
            'can_confirm': (
                booking.status
                == SpaceBooking
                .Status
                .PENDING
            ),
            'can_cancel': (
                booking.status
                in [
                    SpaceBooking
                    .Status
                    .PENDING,
                    SpaceBooking
                    .Status
                    .CONFIRMED,
                ]
            ),
            'can_complete': can_complete,
            'completion_waiting': completion_waiting,
            'completion_available_at': session_end,
            'cancel_error': (
                request.GET.get(
                    'cancel_error'
                )
            ),
            'completion_error': (
                request.GET.get(
                    'completion_error'
                )
            ),
        }
    )


@login_required(
    login_url='accounts:login'
)
@require_POST
def provider_confirm_space_booking(
    request,
    booking_id,
):
    """
    Confirma una reserva Pendiente.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    with transaction.atomic():

        booking = get_object_or_404(
            SpaceBooking.objects
            .select_for_update(),
            pk=booking_id,
            provider_profile=provider_profile,
        )

        if (
            booking.status
            != SpaceBooking
            .Status
            .PENDING
        ):
            return redirect(
                'spaces:provider_booking_detail',
                booking_id=booking.id,
            )

        previous_data = (
            booking.audit_snapshot()
        )

        booking.status = (
            SpaceBooking
            .Status
            .CONFIRMED
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

        SpaceBookingHistory.objects.create(
            booking=booking,
            action=(
                SpaceBookingHistory
                .Action
                .CONFIRMED
            ),
            previous_data=previous_data,
            new_data=(
                booking.audit_snapshot()
            ),
            changed_by=request.user,
            reason=(
                'Reserva confirmada por el '
                'Proveedor de Espacios.'
            ),
        )

    return redirect(
        'spaces:provider_booking_detail',
        booking_id=booking.id,
    )


@login_required(
    login_url='accounts:login'
)
@require_POST
def provider_cancel_space_booking(
    request,
    booking_id,
):
    """
    Cancela una reserva Pendiente o Confirmada y
    libera nuevamente el bloque horario.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    reason = (
        request.POST.get(
            'reason',
            ''
        )
        .strip()
    )

    if len(reason) < 5:
        return redirect(
            (
                reverse(
                    'spaces:provider_booking_detail',
                    kwargs={
                        'booking_id': booking_id,
                    }
                )
                + '?cancel_error=reason'
            )
        )

    with transaction.atomic():

        booking = get_object_or_404(
            SpaceBooking.objects
            .select_for_update(),
            pk=booking_id,
            provider_profile=provider_profile,
        )

        if (
            booking.status
            not in [
                SpaceBooking
                .Status
                .PENDING,
                SpaceBooking
                .Status
                .CONFIRMED,
            ]
        ):
            return redirect(
                'spaces:provider_booking_detail',
                booking_id=booking.id,
            )

        previous_data = (
            booking.audit_snapshot()
        )

        booking.status = (
            SpaceBooking
            .Status
            .CANCELLED
        )

        booking.cancellation_reason = (
            reason
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

        SpaceBookingHistory.objects.create(
            booking=booking,
            action=(
                SpaceBookingHistory
                .Action
                .CANCELLED
            ),
            previous_data=previous_data,
            new_data=(
                booking.audit_snapshot()
            ),
            changed_by=request.user,
            reason=reason,
        )

    return redirect(
        'spaces:provider_booking_detail',
        booking_id=booking.id,
    )


@login_required(
    login_url='accounts:login'
)
def my_space_bookings(request):
    """
    Lista las reservas de espacios pertenecientes al
    miembro autenticado, separadas entre próximas e historial.
    """

    bookings = (
        SpaceBooking.objects
        .filter(
            booked_by=request.user
        )
        .select_related(
            'space',
            'provider_profile',
            'provider_profile__user',
        )
        .order_by(
            'session_date',
            'start_time',
            '-created_at',
        )
    )

    now = timezone.localtime()
    current_timezone = timezone.get_current_timezone()

    upcoming_bookings = []
    history_bookings = []

    for booking in bookings:

        session_end = timezone.make_aware(
            datetime.combine(
                booking.session_date,
                booking.end_time,
            ),
            current_timezone,
        )

        if (
            booking.status
            in [
                SpaceBooking.Status.PENDING,
                SpaceBooking.Status.CONFIRMED,
            ]
            and session_end >= now
        ):
            upcoming_bookings.append(
                booking
            )

        else:
            history_bookings.append(
                booking
            )

    return render(
        request,
        'spaces/my_space_bookings.html',
        {
            'upcoming_bookings': upcoming_bookings,
            'history_bookings': history_bookings,
            'upcoming_count': len(
                upcoming_bookings
            ),
            'history_count': len(
                history_bookings
            ),
            'total_count': bookings.count(),
        }
    )


@login_required(
    login_url='accounts:login'
)
@require_POST
def cancel_my_space_booking(
    request,
    booking_id,
):
    """
    Permite al miembro cancelar su propia reserva
    antes del inicio del bloque.
    """

    reason = (
        request.POST.get(
            'reason',
            ''
        )
        .strip()
    )

    if len(reason) < 5:
        return redirect(
            (
                reverse(
                    'spaces:booking_detail',
                    kwargs={
                        'booking_id': booking_id,
                    }
                )
                + '?cancel_error=reason'
            )
        )

    with transaction.atomic():

        booking = get_object_or_404(
            SpaceBooking.objects
            .select_for_update()
            .select_related(
                'space',
                'booked_by',
            ),
            pk=booking_id,
            booked_by=request.user,
        )

        if (
            booking.status
            not in [
                SpaceBooking.Status.PENDING,
                SpaceBooking.Status.CONFIRMED,
            ]
        ):
            return redirect(
                'spaces:booking_detail',
                booking_id=booking.id,
            )

        current_timezone = (
            timezone.get_current_timezone()
        )

        session_start = timezone.make_aware(
            datetime.combine(
                booking.session_date,
                booking.start_time,
            ),
            current_timezone,
        )

        if timezone.localtime() >= session_start:
            return redirect(
                (
                    reverse(
                        'spaces:booking_detail',
                        kwargs={
                            'booking_id': booking.id,
                        }
                    )
                    + '?cancel_error=started'
                )
            )

        previous_data = (
            booking.audit_snapshot()
        )

        booking.status = (
            SpaceBooking.Status.CANCELLED
        )

        booking.cancellation_reason = (
            reason
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

        SpaceBookingHistory.objects.create(
            booking=booking,
            action=(
                SpaceBookingHistory
                .Action
                .CANCELLED
            ),
            previous_data=previous_data,
            new_data=(
                booking.audit_snapshot()
            ),
            changed_by=request.user,
            reason=reason,
        )

    return redirect(
        'spaces:booking_detail',
        booking_id=booking.id,
    )


@login_required(
    login_url='accounts:login'
)
@require_POST
def provider_complete_space_booking(
    request,
    booking_id,
):
    """
    Completa una reserva Confirmada únicamente
    después de que finalice el bloque reservado.
    """

    provider_profile = getattr(
        request.user,
        'space_provider_profile',
        None
    )

    if (
        provider_profile is None
        or provider_profile.verification_status
        != SpaceProviderProfile
        .VerificationStatus
        .VERIFIED
        or not provider_profile.is_public
    ):
        return redirect(
            'accounts:dashboard'
        )

    with transaction.atomic():

        booking = get_object_or_404(
            SpaceBooking.objects
            .select_for_update(),
            pk=booking_id,
            provider_profile=provider_profile,
        )

        if (
            booking.status
            != SpaceBooking
            .Status
            .CONFIRMED
        ):
            return redirect(
                'spaces:provider_booking_detail',
                booking_id=booking.id,
            )

        current_timezone = (
            timezone.get_current_timezone()
        )

        session_end = timezone.make_aware(
            datetime.combine(
                booking.session_date,
                booking.end_time,
            ),
            current_timezone,
        )

        if timezone.localtime() < session_end:

            url = reverse(
                'spaces:provider_booking_detail',
                kwargs={
                    'booking_id': booking.id,
                }
            )

            return redirect(
                f'{url}?completion_error=too_early'
            )

        previous_data = (
            booking.audit_snapshot()
        )

        booking.status = (
            SpaceBooking
            .Status
            .COMPLETED
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

        SpaceBookingHistory.objects.create(
            booking=booking,
            action=(
                SpaceBookingHistory
                .Action
                .COMPLETED
            ),
            previous_data=previous_data,
            new_data=(
                booking.audit_snapshot()
            ),
            changed_by=request.user,
            reason=(
                'Reserva completada por el '
                'Proveedor de Espacios una vez '
                'finalizado el horario reservado.'
            ),
        )

    return redirect(
        'spaces:provider_booking_detail',
        booking_id=booking.id,
    )

