import calendar as calendar_module

from datetime import date, datetime, timedelta

from django.contrib.auth import (
    authenticate,
    login,
    logout,
)
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.bookings.incident_notifications import get_session_incident_updates
from apps.bookings.models import Booking, BookingHistory
from apps.bookings.services import expire_pending_bookings
from apps.activities.models import Activity, ActivityRegistration
from apps.locations.models import Commune
from apps.spaces.models import SpaceBooking, SpaceBookingHistory

from .forms import (
    ProfileSettingsForm,
    RegisterForm,
)
from .models import MemberProfile


def register(request):
    """
    Crea la Cuenta Única Universal y su Perfil de Miembro
    dentro de una única transacción.
    """

    if request.user.is_authenticated:
        return redirect(
            'accounts:dashboard'
        )

    if request.method == 'POST':

        form = RegisterForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():

            with transaction.atomic():

                user = form.save(
                    commit=False
                )

                current_time = (
                    timezone.now()
                )

                user.terms_accepted_at = (
                    current_time
                )

                user.privacy_accepted_at = (
                    current_time
                )

                user.save()

                member_profile = (
                    MemberProfile.objects.create(
                        user=user,

                        activity_level=(
                            form.cleaned_data[
                                'activity_level'
                            ]
                        ),

                        emergency_contact_name=(
                            form.cleaned_data[
                                'emergency_contact_name'
                            ]
                        ),

                        emergency_contact_relationship=(
                            form.cleaned_data[
                                'emergency_contact_relationship'
                            ]
                        ),

                        emergency_contact_phone=(
                            form.cleaned_data[
                                'emergency_contact_phone'
                            ]
                        ),

                        fitness_declaration_accepted=(
                            form.cleaned_data[
                                'fitness_declaration_accepted'
                            ]
                        ),

                        fitness_declaration_accepted_at=(
                            current_time
                        ),

                        protected_payment_accepted=(
                            form.cleaned_data[
                                'protected_payment_accepted'
                            ]
                        ),

                        protected_payment_accepted_at=(
                            current_time
                        ),
                    )
                )

                member_profile.interests.set(
                    form.cleaned_data[
                        'interests'
                    ]
                )

            return redirect(
                'accounts:login'
            )

    else:

        form = RegisterForm()

    return render(
        request,
        'accounts/register.html',
        {
            'form': form,
        }
    )


def login_view(request):
    """
    Inicio de sesión utilizando correo electrónico
    y contraseña.
    """

    if request.user.is_authenticated:

        return redirect(
            'accounts:dashboard'
        )

    error = None
    email = ''

    if request.method == 'POST':

        email = (
            request.POST
            .get(
                'email',
                ''
            )
            .strip()
            .lower()
        )

        password = (
            request.POST.get(
                'password',
                ''
            )
        )

        user = authenticate(
            request,
            username=email,
            password=password,
        )

        if user is not None:

            if user.is_active:

                login(
                    request,
                    user
                )

                return redirect(
                    'accounts:dashboard'
                )

        error = (
            'El correo electrónico o la contraseña '
            'son incorrectos.'
        )

    return render(
        request,
        'accounts/login.html',
        {
            'error': error,
            'email': email,
        }
    )


def _account_updates_for(user):
    """
    Construye las novedades visibles para el Miembro.

    Mantiene las novedades existentes de reservas profesionales y
    arriendos, e incorpora Actividades sin crear una segunda tabla
    de notificaciones. El estado visto/no visto continúa resolviéndose
    en el navegador con las claves estables de cada novedad.
    """

    updates = []

    # =====================================================
    # SERVICIOS PROFESIONALES
    # =====================================================

    professional_events = (
        BookingHistory.objects
        .filter(
            booking__booked_by=user,
            action__in=[
                BookingHistory.Action.CONFIRMED,
                BookingHistory.Action.CANCELLED,
            ],
        )
        .exclude(
            changed_by=user,
        )
        .select_related(
            'booking',
            'booking__professional_profile',
            'booking__professional_profile__user',
            'changed_by',
        )
        .order_by(
            '-created_at',
            '-id',
        )[:20]
    )

    for event in professional_events:

        booking = event.booking
        previous_status = (
            event.previous_data.get('status')
        )

        professional_user = (
            booking.professional_profile.user
        )

        professional_name = (
            professional_user.get_full_name()
            or professional_user.email
        )

        if event.action == BookingHistory.Action.CONFIRMED:
            kind = 'confirmed'
            title = f'{professional_name} confirmó tu sesión'
            summary = (
                f'Tu reserva para {booking.service_name_snapshot} '
                f'quedó confirmada.'
            )

        elif previous_status == Booking.Status.PENDING:
            kind = 'rejected'
            title = f'{professional_name} no pudo aceptar tu solicitud'
            summary = (
                f'La sesión de {booking.service_name_snapshot} '
                f'no se realizará en el horario solicitado.'
            )

        else:
            kind = 'cancelled'
            title = f'{professional_name} canceló tu sesión'
            summary = (
                f'La reserva de {booking.service_name_snapshot} '
                f'ya no se realizará.'
            )

        updates.append({
            'key': f'professional-{event.id}',
            'module': 'professional',
            'module_label': 'SERVICIO PROFESIONAL',
            'kind': kind,
            'title': title,
            'summary': summary,
            'reason': event.reason,
            'subject': booking.service_name_snapshot,
            'person': professional_name,
            'session_date': booking.session_date,
            'start_time': booking.start_time,
            'end_time': booking.end_time,
            'created_at': event.created_at,
            'detail_url': reverse(
                'bookings:detail',
                kwargs={'booking_id': booking.id},
            ),
        })

    # =====================================================
    # ESPACIOS
    # =====================================================

    space_events = (
        SpaceBookingHistory.objects
        .filter(
            booking__booked_by=user,
            action__in=[
                SpaceBookingHistory.Action.CONFIRMED,
                SpaceBookingHistory.Action.CANCELLED,
            ],
        )
        .exclude(
            changed_by=user,
        )
        .select_related(
            'booking',
            'booking__space',
            'booking__provider_profile',
            'booking__provider_profile__user',
            'changed_by',
        )
        .order_by(
            '-created_at',
            '-id',
        )[:20]
    )

    for event in space_events:

        booking = event.booking
        previous_status = (
            event.previous_data.get('status')
        )

        provider_name = (
            booking.provider_name_snapshot
            or booking.provider_profile.display_name
        )

        if event.action == SpaceBookingHistory.Action.CONFIRMED:
            kind = 'confirmed'
            title = f'{provider_name} confirmó tu arriendo'
            summary = (
                f'Tu reserva para {booking.space_name_snapshot} '
                f'quedó confirmada.'
            )

        elif previous_status == SpaceBooking.Status.PENDING:
            kind = 'rejected'
            title = f'{provider_name} no pudo aceptar tu solicitud'
            summary = (
                f'El arriendo de {booking.space_name_snapshot} '
                f'no se realizará en el horario solicitado.'
            )

        else:
            kind = 'cancelled'
            title = f'{provider_name} canceló tu arriendo'
            summary = (
                f'La reserva de {booking.space_name_snapshot} '
                f'ya no se realizará.'
            )

        updates.append({
            'key': f'space-{event.id}',
            'module': 'space',
            'module_label': 'ESPACIO',
            'kind': kind,
            'title': title,
            'summary': summary,
            'reason': event.reason,
            'subject': booking.space_name_snapshot,
            'person': provider_name,
            'session_date': booking.session_date,
            'start_time': booking.start_time,
            'end_time': booking.end_time,
            'created_at': event.created_at,
            'detail_url': reverse(
                'spaces:booking_detail',
                kwargs={'booking_id': booking.id},
            ),
        })

    # =====================================================
    # ACTIVIDADES
    # =====================================================
    #
    # En esta etapa Actividades todavía no posee un historial propio
    # equivalente a BookingHistory/SpaceBookingHistory. Por eso usamos
    # sus registros reales (ActivityRegistration) y las marcas de tiempo
    # de Activity para mostrar novedades útiles sin duplicar datos.
    #
    # La función admite tanto los nombres de campos usados por la versión
    # actual del módulo (title/date) como los nombres alternativos
    # (name/session_date), para no acoplar Mi cuenta a una sola revisión.

    def activity_title(activity):
        return (
            getattr(activity, 'title', None)
            or getattr(activity, 'name', None)
            or 'Actividad'
        )

    def activity_date(activity):
        return (
            getattr(activity, 'date', None)
            or getattr(activity, 'session_date', None)
        )

    def registration_joined_at(registration):
        return (
            getattr(registration, 'joined_at', None)
            or getattr(registration, 'created_at', None)
            or getattr(registration, 'updated_at', None)
        )

    def registration_cancelled_at(registration):
        return (
            getattr(registration, 'cancelled_at', None)
        )

    def activity_cancelled_at(activity):
        return (
            getattr(activity, 'cancelled_at', None)
            or getattr(activity, 'updated_at', None)
        )

    def activity_updated_at(activity):
        return (
            getattr(activity, 'updated_at', None)
        )

    def activity_module_label(actor):
        """
        Construye la identidad visual de la persona relacionada
        con una novedad de Actividades.

        Si tiene foto de perfil, se muestra la foto.
        Si no, se muestran sus iniciales.
        """

        first_name = (
            getattr(actor, 'first_name', '') or ''
        ).strip()

        last_name = (
            getattr(actor, 'last_name', '') or ''
        ).strip()

        email = (
            getattr(actor, 'email', '') or ''
        ).strip()

        actor_name = (
            actor.get_full_name()
            or email
            or 'Miembro'
        )

        initials = (
            (first_name[:1] + last_name[:1]).upper()
        )

        if not initials:
            initials = email[:2].upper() or 'ACT'

        profile_image = getattr(
            actor,
            'profile_image',
            None,
        )

        if profile_image:
            return format_html(
                '<span class="activity-update-actor">'
                '<img src="{}" alt="Foto de {}">'
                '</span>'
                '<span class="activity-update-module-name">'
                'ACTIVIDAD'
                '</span>',
                profile_image.url,
                actor_name,
            )

        return format_html(
            '<span class="activity-update-actor '
            'activity-update-actor-initials">'
            '{}'
            '</span>'
            '<span class="activity-update-module-name">'
            'ACTIVIDAD'
            '</span>',
            initials,
        )

    # -------------------------------------------------
    # NOVEDADES DEL MIEMBRO QUE PARTICIPA
    # -------------------------------------------------

    member_registrations = (
        ActivityRegistration.objects
        .filter(
            member=user,
        )
        .select_related(
            'activity',
            'activity__organizer',
        )
        .order_by(
            '-id',
        )[:30]
    )

    for registration in member_registrations:

        activity = registration.activity
        title_text = activity_title(activity)
        session_date = activity_date(activity)

        organizer_name = (
            activity.organizer.get_full_name()
            or activity.organizer.email
        )

        joined_at = registration_joined_at(
            registration
        )

        registration_status = str(
            registration.status
        )

        activity_status = str(
            activity.status
        )

        detail_url = reverse(
            'activities:detail',
            kwargs={
                'activity_id': activity.id,
            },
        )

        # La inscripción es una novedad real para el Miembro.
        # Se conserva aunque después libere el cupo, para que pase
        # al historial cuando la marque como revisada.
        if joined_at:

            updates.append({
                'key': (
                    f'activity-joined-'
                    f'{registration.id}'
                ),
                'module': 'activity',
                'module_label': activity_module_label(activity.organizer),
                'kind': 'joined',
                'title': (
                    f'Te uniste a {title_text}'
                ),
                'summary': (
                    f'Ya formas parte de esta actividad '
                    f'organizada por {organizer_name}.'
                ),
                'reason': '',
                'subject': title_text,
                'person': organizer_name,
                'session_date': session_date,
                'start_time': activity.start_time,
                'end_time': activity.end_time,
                'created_at': joined_at,
                'detail_url': detail_url,
            })

        # Cancelación completa de la actividad por su organizador.
        if activity_status == 'cancelled':

            cancelled_at = activity_cancelled_at(
                activity
            )

            if cancelled_at:

                updates.append({
                    'key': (
                        f'activity-cancelled-'
                        f'{activity.id}-'
                        f'{int(cancelled_at.timestamp())}'
                    ),
                    'module': 'activity',
                    'module_label': activity_module_label(activity.organizer),
                    'kind': 'cancelled',
                    'title': (
                        f'Se canceló {title_text}'
                    ),
                    'summary': (
                        f'La actividad organizada por '
                        f'{organizer_name} ya no se realizará.'
                    ),
                    'reason': '',
                    'subject': title_text,
                    'person': organizer_name,
                    'session_date': session_date,
                    'start_time': activity.start_time,
                    'end_time': activity.end_time,
                    'created_at': cancelled_at,
                    'detail_url': detail_url,
                })

        # Si el Miembro continúa inscrito y el organizador editó la
        # actividad después de la inscripción, mostramos una novedad
        # genérica para que revise fecha, horario o punto de encuentro.
        elif (
            registration_status == 'registered'
            and activity_status == 'published'
        ):

            updated_at = activity_updated_at(
                activity
            )

            if (
                joined_at
                and updated_at
                and updated_at
                > joined_at + timedelta(seconds=2)
            ):

                updates.append({
                    'key': (
                        f'activity-updated-'
                        f'{activity.id}-'
                        f'{int(updated_at.timestamp())}'
                    ),
                    'module': 'activity',
                    'module_label': activity_module_label(activity.organizer),
                    'kind': 'updated',
                    'title': (
                        f'Se actualizó {title_text}'
                    ),
                    'summary': (
                        'El organizador hizo cambios después '
                        'de tu inscripción. Revisa nuevamente '
                        'los datos de la actividad.'
                    ),
                    'reason': '',
                    'subject': title_text,
                    'person': organizer_name,
                    'session_date': session_date,
                    'start_time': activity.start_time,
                    'end_time': activity.end_time,
                    'created_at': updated_at,
                    'detail_url': detail_url,
                })

    # -------------------------------------------------
    # NOVEDADES PARA QUIEN ORGANIZA
    # -------------------------------------------------

    organizer_registrations = (
        ActivityRegistration.objects
        .filter(
            activity__organizer=user,
        )
        .exclude(
            member=user,
        )
        .select_related(
            'activity',
            'member',
        )
        .order_by(
            '-id',
        )[:30]
    )

    for registration in organizer_registrations:

        activity = registration.activity
        title_text = activity_title(activity)
        session_date = activity_date(activity)

        member_name = (
            registration.member.get_full_name()
            or registration.member.email
        )

        joined_at = registration_joined_at(
            registration
        )

        cancelled_at = registration_cancelled_at(
            registration
        )

        detail_url = reverse(
            'activities:detail',
            kwargs={
                'activity_id': activity.id,
            },
        )

        if joined_at:

            updates.append({
                'key': (
                    f'activity-member-joined-'
                    f'{registration.id}'
                ),
                'module': 'activity',
                'module_label': activity_module_label(registration.member),
                'kind': 'member_joined',
                'title': (
                    f'{member_name} se unió a '
                    f'{title_text}'
                ),
                'summary': (
                    'Tienes una nueva persona inscrita '
                    'en la actividad que organizas.'
                ),
                'reason': '',
                'subject': title_text,
                'person': member_name,
                'session_date': session_date,
                'start_time': activity.start_time,
                'end_time': activity.end_time,
                'created_at': joined_at,
                'detail_url': detail_url,
            })

        if (
            str(registration.status) == 'cancelled'
            and cancelled_at
        ):

            updates.append({
                'key': (
                    f'activity-member-left-'
                    f'{registration.id}-'
                    f'{int(cancelled_at.timestamp())}'
                ),
                'module': 'activity',
                'module_label': activity_module_label(registration.member),
                'kind': 'member_left',
                'title': (
                    f'{member_name} liberó su cupo'
                ),
                'summary': (
                    f'Ya no participa en {title_text}. '
                    'El cupo volvió a quedar disponible.'
                ),
                'reason': '',
                'subject': title_text,
                'person': member_name,
                'session_date': session_date,
                'start_time': activity.start_time,
                'end_time': activity.end_time,
                'created_at': cancelled_at,
                'detail_url': detail_url,
            })

    # =====================================================
    # V123 - NOVEDADES ADMINISTRATIVAS DE INCIDENCIAS
    # =====================================================
    # Se agrega la novedad mas reciente de cada incidencia asociada
    # al usuario autenticado. No se muestran datos administrativos
    # privados ni la declaracion original del Profesional.
    #
    # Las claves son distintas a las novedades de reservas y
    # actividades: cada nuevo estado importante genera una clave
    # diferente, compatible con el historial local del navegador.

    for incident_update in get_session_incident_updates(
        user,
        'member',
        limit=30,
    ):
        booking = incident_update['booking']
        professional_user = booking.professional_profile.user
        professional_name = (
            professional_user.get_full_name()
            or professional_user.email
        )

        kind = incident_update['kind']

        if kind == 'incident_resolved':
            title = 'La plataforma resolvió tu reporte'
            summary = (
                'La administración finalizó la revisión de tu '
                'incidencia. Consulta la decisión y su explicación.'
            )
        elif kind == 'incident_in_review':
            title = 'La plataforma inició la revisión de tu reporte'
            summary = (
                'La administración está revisando tu incidencia '
                'y los antecedentes disponibles.'
            )
        elif kind == 'incident_response':
            title = 'El Profesional presentó sus antecedentes'
            summary = (
                'Se incorporó una declaración del Profesional '
                'al expediente de la incidencia.'
            )
        else:
            # No hay aviso nuevo para el miembro por su propio reporte.
            continue

        updates.append({
            'key': 'member-' + incident_update['key'],
            'module': 'incident',
            'module_label': 'SEGUIMIENTO DE INCIDENCIA',
            'kind': kind,
            'title': title,
            'summary': summary,
            'reason': '',
            'subject': booking.service_name_snapshot,
            'person': professional_name,
            'session_date': booking.session_date,
            'start_time': booking.start_time,
            'end_time': booking.end_time,
            'created_at': incident_update['created_at'],
            'detail_url': incident_update['link_url'],
            'action_label': 'Ver mi incidencia',
            'incident_id': incident_update['incident_id'],
        })

    updates.sort(
        key=lambda item: item['created_at'],
        reverse=True,
    )

    return updates[:30]


def _activity_duration_minutes(activity):
    """
    Calcula la duración de una actividad sin depender de que
    el modelo tenga una propiedad específica para ello.
    """

    if not activity.start_time or not activity.end_time:
        return 0

    start_datetime = datetime.combine(
        activity.date,
        activity.start_time,
    )

    end_datetime = datetime.combine(
        activity.date,
        activity.end_time,
    )

    return max(
        int(
            (
                end_datetime
                - start_datetime
            ).total_seconds()
            // 60
        ),
        0,
    )


def _activity_display_state(
    activity,
    relationship,
    registration_status=None,
    today=None,
):
    """
    Devuelve un estado pensado para la experiencia del Miembro.

    relationship:
    - organizer: el usuario organiza la actividad.
    - participant: el usuario se inscribió en la actividad.

    No modifica la base de datos; solo traduce el estado actual
    para Mi agenda y Mi actividad.
    """

    if today is None:
        today = timezone.localdate()

    if activity.status == Activity.Status.CANCELLED:
        return (
            'cancelled',
            'Cancelada',
            False,
        )

    # El modelo de Actividades puede nombrar el estado final como
    # "finished" o "completed" según la versión. Comparamos el valor
    # persistido y no un atributo del Enum para mantener compatibilidad.
    if str(activity.status) in {
        'finished',
        'completed',
    }:
        return (
            'completed',
            'Finalizada',
            False,
        )

    if relationship == 'participant':

        if registration_status == ActivityRegistration.Status.CANCELLED:
            return (
                'cancelled',
                'Cupo liberado',
                False,
            )

        if registration_status == 'attended':
            return (
                'completed',
                'Asistió',
                False,
            )

        if registration_status == 'no_show':
            return (
                'completed',
                'No asistió',
                False,
            )

        if (
            registration_status
            == ActivityRegistration.Status.REGISTERED
        ):
            if activity.date < today:
                return (
                    'completed',
                    'Realizada',
                    False,
                )

            return (
                'registered',
                'Inscrito',
                activity.status == Activity.Status.PUBLISHED,
            )

    if relationship == 'organizer':

        if activity.date < today:
            return (
                'completed',
                'Realizada',
                False,
            )

        if activity.status == Activity.Status.PUBLISHED:
            return (
                'organized',
                'Organizas',
                True,
            )

    return (
        str(activity.status),
        activity.get_status_display(),
        False,
    )


def _activity_member_total(user):
    """
    Cuenta actividades relacionadas con el Miembro una sola vez,
    ya sea porque las organiza o porque participa en ellas.
    Los borradores no se consideran actividad registrada general.
    """

    joined_activity_ids = (
        ActivityRegistration.objects
        .filter(
            member=user
        )
        .values_list(
            'activity_id',
            flat=True,
        )
    )

    return (
        Activity.objects
        .filter(
            Q(organizer=user)
            | Q(id__in=joined_activity_ids)
        )
        .exclude(
            status=Activity.Status.DRAFT
        )
        .distinct()
        .count()
    )


@login_required(
    login_url='accounts:login'
)
def dashboard(request):
    """
    Panel principal de la Cuenta Única Universal.

    Determina además si la cuenta cumple con los
    requisitos base necesarios para solicitar un
    Perfil Profesional.

    Actividades se integra aquí como tercer módulo del
    Miembro, sin alterar el bloque visual específico de
    próximas reservas profesionales y arriendos.
    """

    member_profile = getattr(
        request.user,
        'member_profile',
        None
    )

    professional_profile = getattr(
        request.user,
        'professional_profile',
        None
    )

    account_ready_for_professional = all([
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

    # -------------------------------------------------
    # LO PRÓXIMO: SERVICIOS + ESPACIOS
    # -------------------------------------------------
    # Conservamos el bloque existente tal como funciona.
    # Actividades se muestra desde los accesos rápidos,
    # Mi agenda y Mi actividad en esta etapa.

    local_now = timezone.localtime()
    today = local_now.date()
    current_time = (
        local_now.time().replace(
            tzinfo=None
        )
    )

    future_filter = (
        Q(session_date__gt=today)
        | Q(
            session_date=today,
            start_time__gte=current_time,
        )
    )

    professional_bookings = (
        Booking.objects
        .filter(
            booked_by=request.user,
            status__in=[
                Booking.Status.PENDING,
                Booking.Status.CONFIRMED,
            ],
        )
        .filter(
            future_filter
        )
        .select_related(
            'professional_profile__user',
        )
        .order_by(
            'session_date',
            'start_time',
            'id',
        )
    )

    space_bookings = (
        SpaceBooking.objects
        .filter(
            booked_by=request.user,
            status__in=[
                SpaceBooking.Status.PENDING,
                SpaceBooking.Status.CONFIRMED,
            ],
        )
        .filter(
            future_filter
        )
        .select_related(
            'space',
            'provider_profile__user',
        )
        .prefetch_related(
            'space__images',
        )
        .order_by(
            'session_date',
            'start_time',
            'id',
        )
    )

    next_professional_booking = (
        professional_bookings.first()
    )
    next_space_booking = (
        space_bookings.first()
    )

    next_booking = None
    next_booking_kind = None
    next_space_cover = None

    if (
        next_professional_booking
        and next_space_booking
    ):
        professional_key = (
            next_professional_booking.session_date,
            next_professional_booking.start_time,
        )
        space_key = (
            next_space_booking.session_date,
            next_space_booking.start_time,
        )

        if professional_key <= space_key:
            next_booking = (
                next_professional_booking
            )
            next_booking_kind = 'professional'
        else:
            next_booking = (
                next_space_booking
            )
            next_booking_kind = 'space'

    elif next_professional_booking:
        next_booking = (
            next_professional_booking
        )
        next_booking_kind = 'professional'

    elif next_space_booking:
        next_booking = (
            next_space_booking
        )
        next_booking_kind = 'space'

    if next_booking_kind == 'space':
        next_space_cover = (
            next_booking.space.images
            .filter(
                is_cover=True
            )
            .first()
        )

        if next_space_cover is None:
            next_space_cover = (
                next_booking.space.images
                .order_by(
                    'display_order',
                    'id',
                )
                .first()
            )

    professional_upcoming_count = (
        professional_bookings.count()
    )
    space_upcoming_count = (
        space_bookings.count()
    )
    upcoming_booking_total = (
        professional_upcoming_count
        + space_upcoming_count
    )

    # -------------------------------------------------
    # ACTIVIDADES DEL MIEMBRO
    # -------------------------------------------------
    # Cuenta una actividad si el usuario la organiza o si
    # mantiene una inscripción activa. Se usa distinct para
    # evitar dobles conteos si una relación se repitiera.

    activity_future_filter = (
        Q(date__gt=today)
        | Q(
            date=today,
            start_time__gte=current_time,
        )
    )

    joined_upcoming_activity_ids = (
        ActivityRegistration.objects
        .filter(
            member=request.user,
            status=(
                ActivityRegistration.Status.REGISTERED
            ),
        )
        .values_list(
            'activity_id',
            flat=True,
        )
    )

    activity_upcoming_count = (
        Activity.objects
        .filter(
            Q(organizer=request.user)
            | Q(id__in=joined_upcoming_activity_ids),
            status=Activity.Status.PUBLISHED,
        )
        .filter(
            activity_future_filter
        )
        .distinct()
        .count()
    )

    account_upcoming_total = (
        upcoming_booking_total
        + activity_upcoming_count
    )

    # -------------------------------------------------
    # MI ACTIVIDAD: CONTADORES GENERALES
    # -------------------------------------------------

    total_member_activity_count = (
        Booking.objects
        .filter(
            booked_by=request.user
        )
        .count()
        +
        SpaceBooking.objects
        .filter(
            booked_by=request.user
        )
        .count()
        +
        _activity_member_total(
            request.user
        )
    )

    account_activity_history_count = max(
        total_member_activity_count
        - account_upcoming_total,
        0,
    )

    professional_booking_preview = list(
        professional_bookings[:3]
    )

    professional_remaining_count = max(
        professional_upcoming_count - 3,
        0,
    )

    space_booking_preview = list(
        space_bookings[:3]
    )

    space_remaining_count = max(
        space_upcoming_count - 3,
        0,
    )

    # -------------------------------------------------
    # AGENDA MIXTA: SERVICIOS + ESPACIOS
    # -------------------------------------------------
    # Se conserva para el bloque visual existente de Mi cuenta.

    mixed_upcoming_candidates = []

    for booking in professional_booking_preview:
        mixed_upcoming_candidates.append({
            'kind': 'professional',
            'booking': booking,
            'cover': None,
            'sort_key': (
                booking.session_date,
                booking.start_time,
                0,
                booking.id,
            ),
        })

    for booking in space_booking_preview:
        images = list(
            booking.space.images.all()
        )

        cover = next(
            (
                image
                for image in images
                if getattr(image, 'is_cover', False)
            ),
            images[0] if images else None,
        )

        mixed_upcoming_candidates.append({
            'kind': 'space',
            'booking': booking,
            'cover': cover,
            'sort_key': (
                booking.session_date,
                booking.start_time,
                1,
                booking.id,
            ),
        })

    mixed_upcoming_candidates.sort(
        key=lambda item: item['sort_key']
    )

    mixed_upcoming_preview = (
        mixed_upcoming_candidates[:3]
    )

    mixed_remaining_count = max(
        upcoming_booking_total
        - len(mixed_upcoming_preview),
        0,
    )

    account_updates = _account_updates_for(
        request.user
    )

    return render(
        request,
        'accounts/dashboard.html',
        {
            'member_profile': (
                member_profile
            ),

            'professional_profile': (
                professional_profile
            ),

            'account_ready_for_professional': (
                account_ready_for_professional
            ),

            'next_booking': (
                next_booking
            ),

            'next_booking_kind': (
                next_booking_kind
            ),

            'next_space_cover': (
                next_space_cover
            ),

            'professional_upcoming_count': (
                professional_upcoming_count
            ),

            'professional_booking_preview': (
                professional_booking_preview
            ),

            'professional_remaining_count': (
                professional_remaining_count
            ),

            'space_upcoming_count': (
                space_upcoming_count
            ),

            'space_booking_preview': (
                space_booking_preview
            ),

            'space_remaining_count': (
                space_remaining_count
            ),

            'activity_upcoming_count': (
                activity_upcoming_count
            ),

            'upcoming_booking_total': (
                upcoming_booking_total
            ),

            'account_upcoming_total': (
                account_upcoming_total
            ),

            'account_activity_history_count': (
                account_activity_history_count
            ),

            'mixed_upcoming_preview': (
                mixed_upcoming_preview
            ),

            'mixed_remaining_count': (
                mixed_remaining_count
            ),

            'account_updates': (
                account_updates
            ),

            'account_update_count': (
                len(account_updates)
            ),
        }
    )

@login_required(
    login_url='accounts:login'
)
def member_agenda(request):
    """
    Agenda mensual del Miembro.

    Reúne en un solo calendario:
    - reservas de servicios profesionales;
    - arriendos de espacios;
    - actividades comunitarias organizadas por el Miembro;
    - actividades en las que participa;
    - solicitudes pendientes;
    - reservas confirmadas;
    - actividad histórica del día.

    No crea una segunda fuente de verdad. Solo organiza
    Booking, SpaceBooking, Activity y ActivityRegistration
    para que el Miembro visualice su actividad en una pantalla.
    """

    user = request.user

    # Mantiene las solicitudes profesionales antiguas limpias.
    expire_pending_bookings(
        booked_by=user
    )

    today = timezone.localdate()

    # =====================================================
    # MES A MOSTRAR
    # =====================================================

    requested_month = (
        request.GET
        .get('month', '')
        .strip()
    )

    display_month = None

    if requested_month:
        try:
            year_text, month_text = (
                requested_month.split('-', 1)
            )

            display_month = date(
                int(year_text),
                int(month_text),
                1,
            )

        except (TypeError, ValueError):
            display_month = None

    if display_month is None:
        display_month = today.replace(
            day=1
        )

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

    # =====================================================
    # FECHA SELECCIONADA
    # =====================================================

    selected_date = None

    requested_date = (
        request.GET
        .get('date', '')
        .strip()
    )

    if requested_date:
        try:
            selected_date = (
                datetime.strptime(
                    requested_date,
                    '%Y-%m-%d',
                )
                .date()
            )
        except ValueError:
            selected_date = None

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

    # =====================================================
    # RESERVAS DEL MES
    # =====================================================

    professional_bookings = list(
        Booking.objects
        .filter(
            booked_by=user,
            session_date__range=(
                display_month,
                month_end,
            ),
        )
        .select_related(
            'professional_profile',
            'professional_profile__user',
            'service',
        )
        .order_by(
            'session_date',
            'start_time',
            'id',
        )
    )

    space_bookings = list(
        SpaceBooking.objects
        .filter(
            booked_by=user,
            session_date__range=(
                display_month,
                month_end,
            ),
        )
        .select_related(
            'space',
            'space__space_type',
            'provider_profile',
            'provider_profile__user',
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

    # =====================================================
    # ACTIVIDADES DEL MES
    # =====================================================

    organized_activities = list(
        Activity.objects
        .filter(
            organizer=user,
            date__range=(
                display_month,
                month_end,
            ),
        )
        .exclude(
            status=Activity.Status.DRAFT
        )
        .select_related(
            'organizer',
            'category',
            'commune',
            'commune__region',
        )
        .order_by(
            'date',
            'start_time',
            'id',
        )
    )

    joined_activity_registrations = list(
        ActivityRegistration.objects
        .filter(
            member=user,
            activity__date__range=(
                display_month,
                month_end,
            ),
        )
        .select_related(
            'activity',
            'activity__organizer',
            'activity__category',
            'activity__commune',
            'activity__commune__region',
        )
        .order_by(
            'activity__date',
            'activity__start_time',
            'activity__id',
        )
    )

    member_activity_entries = []

    for activity in organized_activities:
        status_key, status_label, is_active = (
            _activity_display_state(
                activity,
                'organizer',
                today=today,
            )
        )

        member_activity_entries.append({
            'activity': activity,
            'relationship': 'organizer',
            'registration_status': None,
            'status_key': status_key,
            'status_label': status_label,
            'is_active': is_active,
        })

    for registration in joined_activity_registrations:
        activity = registration.activity

        # El organizador no necesita una segunda entrada del
        # mismo evento aunque existiera información histórica.
        if activity.organizer_id == user.id:
            continue

        status_key, status_label, is_active = (
            _activity_display_state(
                activity,
                'participant',
                registration.status,
                today=today,
            )
        )

        member_activity_entries.append({
            'activity': activity,
            'relationship': 'participant',
            'registration_status': registration.status,
            'status_key': status_key,
            'status_label': status_label,
            'is_active': is_active,
        })

    member_activity_entries.sort(
        key=lambda entry: (
            entry['activity'].date,
            entry['activity'].start_time,
            entry['activity'].id,
        )
    )

    # =====================================================
    # CONTADORES DEL MES
    # =====================================================

    professional_month_count = len(
        professional_bookings
    )

    space_month_count = len(
        space_bookings
    )

    activity_month_count = len(
        member_activity_entries
    )

    pending_month_count = (
        sum(
            1
            for booking
            in professional_bookings
            if (
                booking.status
                == Booking.Status.PENDING
            )
        )
        +
        sum(
            1
            for booking
            in space_bookings
            if (
                booking.status
                == SpaceBooking.Status.PENDING
            )
        )
    )

    confirmed_month_count = (
        sum(
            1
            for booking
            in professional_bookings
            if (
                booking.status
                == Booking.Status.CONFIRMED
            )
        )
        +
        sum(
            1
            for booking
            in space_bookings
            if (
                booking.status
                == SpaceBooking.Status.CONFIRMED
            )
        )
    )

    # =====================================================
    # MAPAS POR FECHA
    # =====================================================

    professional_by_date = {}
    space_by_date = {}
    activity_by_date = {}

    current_date = display_month

    while current_date <= month_end:
        professional_by_date[
            current_date
        ] = []

        space_by_date[
            current_date
        ] = []

        activity_by_date[
            current_date
        ] = []

        current_date += timedelta(
            days=1
        )

    for booking in professional_bookings:
        professional_by_date.setdefault(
            booking.session_date,
            [],
        ).append(booking)

    for booking in space_bookings:
        space_by_date.setdefault(
            booking.session_date,
            [],
        ).append(booking)

    for entry in member_activity_entries:
        activity_by_date.setdefault(
            entry['activity'].date,
            [],
        ).append(entry)

    # =====================================================
    # CELDAS DEL CALENDARIO
    # =====================================================

    calendar_weeks = []

    month_calendar = (
        calendar_module.Calendar(
            firstweekday=0,
        )
    )

    for week in (
        month_calendar
        .monthdatescalendar(
            display_month.year,
            display_month.month,
        )
    ):
        week_cells = []

        for cell_date in week:

            in_month = (
                cell_date.year
                == display_month.year
                and cell_date.month
                == display_month.month
            )

            day_professional = (
                professional_by_date.get(
                    cell_date,
                    [],
                )
                if in_month
                else []
            )

            day_spaces = (
                space_by_date.get(
                    cell_date,
                    [],
                )
                if in_month
                else []
            )

            day_activities = (
                activity_by_date.get(
                    cell_date,
                    [],
                )
                if in_month
                else []
            )

            professional_active = [
                booking
                for booking
                in day_professional
                if booking.status in [
                    Booking.Status.PENDING,
                    Booking.Status.CONFIRMED,
                ]
            ]

            space_active = [
                booking
                for booking
                in day_spaces
                if booking.status in [
                    SpaceBooking.Status.PENDING,
                    SpaceBooking.Status.CONFIRMED,
                ]
            ]

            activity_active = [
                entry
                for entry
                in day_activities
                if entry['is_active']
            ]

            activity_history = [
                entry
                for entry
                in day_activities
                if not entry['is_active']
            ]

            pending_count = (
                sum(
                    1
                    for booking
                    in professional_active
                    if (
                        booking.status
                        == Booking.Status.PENDING
                    )
                )
                +
                sum(
                    1
                    for booking
                    in space_active
                    if (
                        booking.status
                        == SpaceBooking.Status.PENDING
                    )
                )
            )

            confirmed_count = (
                sum(
                    1
                    for booking
                    in professional_active
                    if (
                        booking.status
                        == Booking.Status.CONFIRMED
                    )
                )
                +
                sum(
                    1
                    for booking
                    in space_active
                    if (
                        booking.status
                        == SpaceBooking.Status.CONFIRMED
                    )
                )
            )

            history_count = (
                len(day_professional)
                + len(day_spaces)
                - len(professional_active)
                - len(space_active)
                + len(activity_history)
            )

            week_cells.append({
                'date': cell_date,
                'in_month': in_month,
                'is_today': (
                    cell_date == today
                ),
                'is_selected': (
                    cell_date
                    == selected_date
                ),
                'professional_count': (
                    len(
                        professional_active
                    )
                ),
                'space_count': (
                    len(
                        space_active
                    )
                ),
                'activity_count': (
                    len(
                        activity_active
                    )
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
                    day_professional
                    or day_spaces
                    or day_activities
                ),
            })

        calendar_weeks.append(
            week_cells
        )

    # =====================================================
    # DETALLE DEL DÍA SELECCIONADO
    # =====================================================

    selected_professional = (
        professional_by_date.get(
            selected_date,
            [],
        )
    )

    selected_spaces = (
        space_by_date.get(
            selected_date,
            [],
        )
    )

    selected_activities = (
        activity_by_date.get(
            selected_date,
            [],
        )
    )

    selected_active_items = []
    selected_history_items = []

    def professional_name(booking):
        profile_user = (
            booking
            .professional_profile
            .user
        )

        return (
            profile_user.get_full_name()
            or profile_user.email
        )

    for booking in selected_professional:

        item = {
            'kind': 'professional',
            'module_label': (
                'SERVICIO PROFESIONAL'
            ),
            'title': (
                booking
                .service_name_snapshot
            ),
            'person_label': (
                'Profesional'
            ),
            'person_name': (
                professional_name(
                    booking
                )
            ),
            'status': booking.status,
            'status_label': (
                booking
                .get_status_display()
            ),
            'start_time': (
                booking.start_time
            ),
            'end_time': (
                booking.end_time
            ),
            'duration_minutes': (
                booking
                .duration_minutes
            ),
            'price_clp': (
                booking.price_clp
            ),
            'detail_url': reverse(
                'bookings:detail',
                kwargs={
                    'booking_id': (
                        booking.id
                    )
                },
            ),
            'action_label': (
                'Ver reserva →'
            ),
        }

        if booking.status in [
            Booking.Status.PENDING,
            Booking.Status.CONFIRMED,
        ]:
            selected_active_items.append(
                item
            )
        else:
            selected_history_items.append(
                item
            )

    for booking in selected_spaces:

        provider_rejected = False

        if (
            booking.status
            == SpaceBooking.Status.CANCELLED
        ):
            for history_item in booking.history.all():

                previous_status = (
                    (history_item.previous_data or {})
                    .get('status')
                )

                if (
                    history_item.action
                    == SpaceBookingHistory.Action.CANCELLED
                    and previous_status
                    == SpaceBooking.Status.PENDING
                    and history_item.changed_by_id
                    == booking.provider_profile.user_id
                ):
                    provider_rejected = True
                    break

        if provider_rejected:
            display_status_label = (
                'No aceptada'
            )
        else:
            display_status_label = (
                booking.get_status_display()
            )

        item = {
            'kind': 'space',
            'module_label': (
                'ARRIENDO DE ESPACIO'
            ),
            'title': (
                booking
                .space_name_snapshot
            ),
            'person_label': (
                'Proveedor'
            ),
            'person_name': (
                booking
                .provider_name_snapshot
            ),
            'status': booking.status,
            'status_label': (
                display_status_label
            ),
            'start_time': (
                booking.start_time
            ),
            'end_time': (
                booking.end_time
            ),
            'duration_minutes': (
                booking
                .duration_minutes
            ),
            'price_clp': (
                booking.price_clp
            ),
            'detail_url': reverse(
                'spaces:booking_detail',
                kwargs={
                    'booking_id': (
                        booking.id
                    )
                },
            ),
            'action_label': (
                'Ver arriendo →'
            ),
        }

        if booking.status in [
            SpaceBooking.Status.PENDING,
            SpaceBooking.Status.CONFIRMED,
        ]:
            selected_active_items.append(
                item
            )
        else:
            selected_history_items.append(
                item
            )

    for entry in selected_activities:
        activity = entry['activity']
        relationship = entry['relationship']

        organizer_name = (
            activity.organizer.get_full_name()
            or activity.organizer.email
        )

        if relationship == 'organizer':
            person_label = 'Tu rol'
            person_name = 'Organizas esta actividad'
        else:
            person_label = 'Organiza'
            person_name = organizer_name

        item = {
            'kind': 'activity',
            'module_label': (
                'ACTIVIDAD COMUNITARIA'
                if activity.activity_type
                == Activity.ActivityType.COMMUNITY
                else 'ACTIVIDAD PROFESIONAL'
            ),
            'title': activity.title,
            'person_label': person_label,
            'person_name': person_name,
            'status': entry['status_key'],
            'status_label': entry['status_label'],
            'start_time': activity.start_time,
            'end_time': activity.end_time,
            'duration_minutes': (
                _activity_duration_minutes(
                    activity
                )
            ),
            'price_clp': (
                getattr(
                    activity,
                    'price',
                    0,
                )
            ),
            'detail_url': reverse(
                'activities:detail',
                kwargs={
                    'activity_id': activity.id,
                },
            ),
            'action_label': (
                'Ver actividad →'
            ),
        }

        if entry['is_active']:
            selected_active_items.append(
                item
            )
        else:
            selected_history_items.append(
                item
            )

    kind_order = {
        'professional': 0,
        'space': 1,
        'activity': 2,
    }

    selected_active_items.sort(
        key=lambda item: (
            item['start_time'],
            kind_order.get(
                item['kind'],
                9,
            ),
        )
    )

    selected_history_items.sort(
        key=lambda item: (
            item['start_time'],
            kind_order.get(
                item['kind'],
                9,
            ),
        )
    )

    return render(
        request,
        'accounts/member_agenda.html',
        {
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

            'professional_month_count': (
                professional_month_count
            ),

            'space_month_count': (
                space_month_count
            ),

            'activity_month_count': (
                activity_month_count
            ),

            'pending_month_count': (
                pending_month_count
            ),

            'confirmed_month_count': (
                confirmed_month_count
            ),

            'selected_active_items': (
                selected_active_items
            ),

            'selected_history_items': (
                selected_history_items
            ),
        }
    )

@login_required(
    login_url='accounts:login'
)
def activity_history(request):
    """
    Vista unificada de actividad del Miembro.

    Reúne reservas profesionales, arriendos de espacios y
    actividades comunitarias relacionadas con la cuenta.
    """

    user = request.user

    # -------------------------------------------------
    # FILTROS
    # -------------------------------------------------

    search_query = (
        request.GET
        .get('q', '')
        .strip()
    )

    activity_type = (
        request.GET
        .get('type', 'all')
        .strip()
    )

    status_filter = (
        request.GET
        .get('status', 'all')
        .strip()
    )

    exact_date_raw = (
        request.GET
        .get('date', '')
        .strip()
    )

    date_from_raw = (
        request.GET
        .get('date_from', '')
        .strip()
    )

    date_to_raw = (
        request.GET
        .get('date_to', '')
        .strip()
    )

    allowed_types = {
        'all',
        'professional',
        'space',
        'activity',
    }

    allowed_statuses = {
        'all',
        'pending',
        'confirmed',
        'registered',
        'organized',
        'rejected',
        'cancelled',
        'completed',
    }

    if activity_type not in allowed_types:
        activity_type = 'all'

    if status_filter not in allowed_statuses:
        status_filter = 'all'

    def parse_date(value):
        if not value:
            return None

        try:
            return datetime.strptime(
                value,
                '%Y-%m-%d',
            ).date()

        except ValueError:
            return None

    exact_date = parse_date(
        exact_date_raw
    )

    date_from = parse_date(
        date_from_raw
    )

    date_to = parse_date(
        date_to_raw
    )

    # La fecha exacta y el rango son dos modos distintos.
    if exact_date:
        date_from = None
        date_to = None
        date_from_raw = ''
        date_to_raw = ''

    elif date_from or date_to:
        exact_date = None
        exact_date_raw = ''

    # -------------------------------------------------
    # CONTADORES GENERALES
    # -------------------------------------------------

    total_professional_count = (
        Booking.objects
        .filter(
            booked_by=user
        )
        .count()
    )

    total_space_count = (
        SpaceBooking.objects
        .filter(
            booked_by=user
        )
        .count()
    )

    total_community_activity_count = (
        _activity_member_total(
            user
        )
    )

    total_activity_count = (
        total_professional_count
        + total_space_count
        + total_community_activity_count
    )

    # -------------------------------------------------
    # RESERVAS PROFESIONALES
    # -------------------------------------------------

    professional_bookings = (
        Booking.objects
        .filter(
            booked_by=user
        )
        .select_related(
            'professional_profile__user',
        )
        .prefetch_related(
            'history',
        )
        .order_by(
            '-session_date',
            '-start_time',
            '-id',
        )
    )

    if activity_type in {
        'space',
        'activity',
    }:
        professional_bookings = (
            professional_bookings.none()
        )

    if search_query:
        professional_bookings = (
            professional_bookings
            .filter(
                Q(
                    service_name_snapshot__icontains=(
                        search_query
                    )
                )
                | Q(
                    professional_profile__user__first_name__icontains=(
                        search_query
                    )
                )
                | Q(
                    professional_profile__user__last_name__icontains=(
                        search_query
                    )
                )
                | Q(
                    location_name_snapshot__icontains=(
                        search_query
                    )
                )
                | Q(
                    location_commune_snapshot__icontains=(
                        search_query
                    )
                )
            )
        )

    if exact_date:
        professional_bookings = (
            professional_bookings
            .filter(
                session_date=exact_date
            )
        )

    if date_from:
        professional_bookings = (
            professional_bookings
            .filter(
                session_date__gte=date_from
            )
        )

    if date_to:
        professional_bookings = (
            professional_bookings
            .filter(
                session_date__lte=date_to
            )
        )

    # -------------------------------------------------
    # ARRIENDOS DE ESPACIOS
    # -------------------------------------------------

    space_bookings = (
        SpaceBooking.objects
        .filter(
            booked_by=user
        )
        .select_related(
            'space',
            'space__space_type',
            'provider_profile__user',
        )
        .prefetch_related(
            'space__images',
            'history',
        )
        .order_by(
            '-session_date',
            '-start_time',
            '-id',
        )
    )

    if activity_type in {
        'professional',
        'activity',
    }:
        space_bookings = (
            space_bookings.none()
        )

    if search_query:
        space_bookings = (
            space_bookings
            .filter(
                Q(
                    space_name_snapshot__icontains=(
                        search_query
                    )
                )
                | Q(
                    provider_name_snapshot__icontains=(
                        search_query
                    )
                )
                | Q(
                    space_type_snapshot__icontains=(
                        search_query
                    )
                )
                | Q(
                    commune_snapshot__icontains=(
                        search_query
                    )
                )
            )
        )

    if exact_date:
        space_bookings = (
            space_bookings
            .filter(
                session_date=exact_date
            )
        )

    if date_from:
        space_bookings = (
            space_bookings
            .filter(
                session_date__gte=date_from
            )
        )

    if date_to:
        space_bookings = (
            space_bookings
            .filter(
                session_date__lte=date_to
            )
        )

    # -------------------------------------------------
    # ACTIVIDADES
    # -------------------------------------------------

    organized_activities = (
        Activity.objects
        .filter(
            organizer=user
        )
        .exclude(
            status=Activity.Status.DRAFT
        )
        .select_related(
            'organizer',
            'category',
            'commune',
            'commune__region',
        )
        .order_by(
            '-date',
            '-start_time',
            '-id',
        )
    )

    joined_activity_registrations = (
        ActivityRegistration.objects
        .filter(
            member=user
        )
        .select_related(
            'activity',
            'activity__organizer',
            'activity__category',
            'activity__commune',
            'activity__commune__region',
        )
        .order_by(
            '-activity__date',
            '-activity__start_time',
            '-activity__id',
        )
    )

    if activity_type in {
        'professional',
        'space',
    }:
        organized_activities = (
            organized_activities.none()
        )
        joined_activity_registrations = (
            joined_activity_registrations.none()
        )

    if search_query:
        activity_search = (
            Q(title__icontains=search_query)
            | Q(category__name__icontains=search_query)
            | Q(commune__name__icontains=search_query)
            | Q(organizer__first_name__icontains=search_query)
            | Q(organizer__last_name__icontains=search_query)
            | Q(meeting_point__icontains=search_query)
        )

        organized_activities = (
            organized_activities
            .filter(
                activity_search
            )
        )

        joined_activity_registrations = (
            joined_activity_registrations
            .filter(
                Q(activity__title__icontains=search_query)
                | Q(activity__category__name__icontains=search_query)
                | Q(activity__commune__name__icontains=search_query)
                | Q(activity__organizer__first_name__icontains=search_query)
                | Q(activity__organizer__last_name__icontains=search_query)
                | Q(activity__meeting_point__icontains=search_query)
            )
        )

    if exact_date:
        organized_activities = (
            organized_activities
            .filter(
                date=exact_date
            )
        )
        joined_activity_registrations = (
            joined_activity_registrations
            .filter(
                activity__date=exact_date
            )
        )

    if date_from:
        organized_activities = (
            organized_activities
            .filter(
                date__gte=date_from
            )
        )
        joined_activity_registrations = (
            joined_activity_registrations
            .filter(
                activity__date__gte=date_from
            )
        )

    if date_to:
        organized_activities = (
            organized_activities
            .filter(
                date__lte=date_to
            )
        )
        joined_activity_registrations = (
            joined_activity_registrations
            .filter(
                activity__date__lte=date_to
            )
        )

    # -------------------------------------------------
    # ESTADO HUMANO DE SERVICIOS / ESPACIOS
    # -------------------------------------------------

    def resolved_status(
        booking,
        module,
    ):
        """
        Diferencia una cancelación real de una solicitud
        pendiente que el Profesional/Proveedor no aceptó.
        """

        if booking.status != 'cancelled':
            return (
                booking.status,
                booking.get_status_display(),
            )

        histories = list(
            booking.history.all()
        )

        cancel_event = next(
            (
                entry
                for entry in histories
                if entry.action == 'cancelled'
            ),
            None,
        )

        if (
            cancel_event
            and cancel_event.previous_data.get(
                'status'
            ) == 'pending'
            and cancel_event.changed_by_id
            and cancel_event.changed_by_id
            != user.id
        ):
            return (
                'rejected',
                'No aceptada',
            )

        return (
            'cancelled',
            'Cancelada',
        )

    # -------------------------------------------------
    # CONSTRUIR ACTIVIDAD UNIFICADA
    # -------------------------------------------------

    activity_items = []

    for booking in professional_bookings:

        status_key, status_label = (
            resolved_status(
                booking,
                'professional',
            )
        )

        if (
            status_filter != 'all'
            and status_key != status_filter
        ):
            continue

        professional_user = (
            booking.professional_profile.user
        )

        professional_name = (
            professional_user.get_full_name()
            or professional_user.email
        )

        location_text = (
            booking.location_name_snapshot
            or booking.location_commune_snapshot
            or booking.get_mode_snapshot_display()
        )

        activity_items.append({
            'module': 'professional',
            'module_label': (
                'SERVICIO PROFESIONAL'
            ),
            'title': (
                booking.service_name_snapshot
            ),
            'person_label': 'Profesional',
            'person': professional_name,
            'subtitle': location_text,
            'session_date': (
                booking.session_date
            ),
            'start_time': booking.start_time,
            'end_time': booking.end_time,
            'duration_minutes': (
                booking.duration_minutes
            ),
            'price_clp': booking.price_clp,
            'status_key': status_key,
            'status_label': status_label,
            'reason': (
                booking.cancellation_reason
                if status_key
                in {
                    'rejected',
                    'cancelled',
                }
                else ''
            ),
            'detail_url': reverse(
                'bookings:detail',
                kwargs={
                    'booking_id': booking.id,
                },
            ),
            'image': (
                professional_user.profile_image
                if professional_user.profile_image
                else None
            ),
            'sort_key': (
                booking.session_date,
                booking.start_time,
                0,
                booking.id,
            ),
        })

    for booking in space_bookings:

        status_key, status_label = (
            resolved_status(
                booking,
                'space',
            )
        )

        if (
            status_filter != 'all'
            and status_key != status_filter
        ):
            continue

        images = list(
            booking.space.images.all()
        )

        cover = next(
            (
                image
                for image in images
                if getattr(
                    image,
                    'is_cover',
                    False,
                )
            ),
            images[0] if images else None,
        )

        activity_items.append({
            'module': 'space',
            'module_label': (
                'ESPACIO'
            ),
            'title': (
                booking.space_name_snapshot
            ),
            'person_label': 'Proveedor',
            'person': (
                booking.provider_name_snapshot
            ),
            'subtitle': (
                f'{booking.space_type_snapshot}'
                + (
                    f' · {booking.commune_snapshot}'
                    if booking.commune_snapshot
                    else ''
                )
            ),
            'session_date': (
                booking.session_date
            ),
            'start_time': booking.start_time,
            'end_time': booking.end_time,
            'duration_minutes': (
                booking.duration_minutes
            ),
            'price_clp': booking.price_clp,
            'status_key': status_key,
            'status_label': status_label,
            'reason': (
                booking.cancellation_reason
                if status_key
                in {
                    'rejected',
                    'cancelled',
                }
                else ''
            ),
            'detail_url': reverse(
                'spaces:booking_detail',
                kwargs={
                    'booking_id': booking.id,
                },
            ),
            'image': (
                cover.image
                if cover
                else None
            ),
            'sort_key': (
                booking.session_date,
                booking.start_time,
                1,
                booking.id,
            ),
        })

    today = timezone.localdate()

    def append_activity_item(
        activity,
        relationship,
        registration_status=None,
    ):
        status_key, status_label, _ = (
            _activity_display_state(
                activity,
                relationship,
                registration_status,
                today=today,
            )
        )

        if (
            status_filter != 'all'
            and status_key != status_filter
        ):
            return

        organizer_name = (
            activity.organizer.get_full_name()
            or activity.organizer.email
        )

        if relationship == 'organizer':
            person_label = 'Tu rol'
            person = 'Organizas esta actividad'
        else:
            person_label = 'Organiza'
            person = organizer_name

        subtitle_parts = []

        if activity.category_id:
            subtitle_parts.append(
                activity.category.name
            )

        if activity.commune_id:
            subtitle_parts.append(
                activity.commune.name
            )

        subtitle = ' · '.join(
            subtitle_parts
        )

        activity_items.append({
            'module': 'activity',
            'module_label': (
                'ACTIVIDAD COMUNITARIA'
                if activity.activity_type
                == Activity.ActivityType.COMMUNITY
                else 'ACTIVIDAD PROFESIONAL'
            ),
            'title': activity.title,
            'person_label': person_label,
            'person': person,
            'subtitle': subtitle,
            'session_date': activity.date,
            'start_time': activity.start_time,
            'end_time': activity.end_time,
            'duration_minutes': (
                _activity_duration_minutes(
                    activity
                )
            ),
            'price_clp': getattr(
                activity,
                'price',
                0,
            ),
            'status_key': status_key,
            'status_label': status_label,
            'reason': getattr(
                activity,
                'cancellation_reason',
                '',
            ),
            'detail_url': reverse(
                'activities:detail',
                kwargs={
                    'activity_id': activity.id,
                },
            ),
            'image': (
                activity.image
                if activity.image
                else None
            ),
            'sort_key': (
                activity.date,
                activity.start_time,
                2,
                activity.id,
            ),
        })

    for activity in organized_activities:
        append_activity_item(
            activity,
            'organizer',
        )

    for registration in joined_activity_registrations:
        activity = registration.activity

        if activity.organizer_id == user.id:
            continue

        append_activity_item(
            activity,
            'participant',
            registration.status,
        )

    # -------------------------------------------------
    # PRÓXIMAS + HISTORIAL
    # -------------------------------------------------

    upcoming_items = []
    history_items = []

    for item in activity_items:
        is_future_or_today = (
            item['session_date']
            >= today
        )

        is_active_status = (
            item['status_key']
            in {
                'pending',
                'confirmed',
                'registered',
                'organized',
            }
        )

        if (
            is_future_or_today
            and is_active_status
        ):
            upcoming_items.append(
                item
            )
        else:
            history_items.append(
                item
            )

    upcoming_items.sort(
        key=lambda item: (
            item['session_date'],
            item['start_time'],
            item['sort_key'][2],
            item['sort_key'][3],
        )
    )

    history_items.sort(
        key=lambda item: (
            item['session_date'],
            item['start_time'],
            item['sort_key'][2],
            item['sort_key'][3],
        ),
        reverse=True,
    )

    # Contadores de módulo según los filtros actuales.
    filtered_professional_count = sum(
        1
        for item in activity_items
        if item['module'] == 'professional'
    )

    filtered_space_count = sum(
        1
        for item in activity_items
        if item['module'] == 'space'
    )

    filtered_activity_count = sum(
        1
        for item in activity_items
        if item['module'] == 'activity'
    )

    # -------------------------------------------------
    # PAGINACIÓN DEL HISTORIAL
    # -------------------------------------------------

    paginator = Paginator(
        history_items,
        12,
    )

    history_page_obj = paginator.get_page(
        request.GET.get(
            'page'
        )
    )

    query_without_page = (
        request.GET.copy()
    )

    query_without_page.pop(
        'page',
        None,
    )

    filter_query = (
        query_without_page.urlencode()
    )

    filtered_result_count = (
        len(upcoming_items)
        + len(history_items)
    )

    return render(
        request,
        'accounts/activity_history.html',
        {
            'upcoming_items': (
                upcoming_items
            ),

            'upcoming_count': (
                len(upcoming_items)
            ),

            'history_page_obj': (
                history_page_obj
            ),

            'history_count': (
                len(history_items)
            ),

            'filtered_professional_count': (
                filtered_professional_count
            ),

            'filtered_space_count': (
                filtered_space_count
            ),

            'filtered_activity_count': (
                filtered_activity_count
            ),

            'result_count': (
                filtered_result_count
            ),

            'total_activity_count': (
                total_activity_count
            ),

            'total_professional_count': (
                total_professional_count
            ),

            'total_space_count': (
                total_space_count
            ),

            'total_community_activity_count': (
                total_community_activity_count
            ),

            'filter_query': (
                filter_query
            ),

            'filters': {
                'q': search_query,
                'type': activity_type,
                'status': status_filter,
                'date': exact_date_raw,
                'date_from': date_from_raw,
                'date_to': date_to_raw,
            },
        }
    )

def logout_view(request):
    """
    Cierra la sesión actual.
    """

    logout(request)

    return redirect(
        'accounts:login'
    )


def communes_by_region(request):
    """
    Devuelve las comunas activas pertenecientes
    a una región seleccionada.
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
def profile_settings(request):
    """
    Permite editar la Cuenta Única Universal
    y el Perfil de Miembro.
    """

    member_profile = getattr(
        request.user,
        'member_profile',
        None
    )

    if member_profile is None:

        return redirect(
            'accounts:dashboard'
        )

    if request.method == 'POST':

        form = ProfileSettingsForm(
            request.POST,
            request.FILES,
            instance=request.user,
            member_profile=member_profile,
        )

        if form.is_valid():

            with transaction.atomic():

                form.save()

            return redirect(
                'accounts:profile_settings'
            )

    else:

        form = ProfileSettingsForm(
            instance=request.user,
            member_profile=member_profile,
        )

    return render(
        request,
        'accounts/profile_settings.html',
        {
            'form': form,

            'member_profile': (
                member_profile
            ),
        }
    )
