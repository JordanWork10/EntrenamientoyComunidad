from django.contrib import messages

from django.contrib.auth.decorators import login_required

from django.core.exceptions import ValidationError

from django.db import transaction

from django.db.models import Q

from django.shortcuts import get_object_or_404, redirect, render

from django.utils import timezone

from apps.professionals.models import ProfessionalProfile



from .forms import CommunityActivityForm, ProfessionalActivityForm

from .models import Activity, ActivityRegistration





def _published_activity_queryset():

    return (

        Activity.objects

        .filter(

            status=Activity.Status.PUBLISHED,

        )

        .select_related(

            'organizer',

            'category',

            'commune',

            'commune__region',

            'professional_profile',

            'professional_profile__user',

            'space_booking',

            'space_booking__space',

            'space_booking__space__commune',

        )

        .order_by(

            'date',

            'start_time',

            'id',

        )

    )





def _verified_professional_profile(user):
    """
    Devuelve el Perfil Profesional solamente cuando
    está verificado y habilitado públicamente.
    """

    if not getattr(
        user,
        'is_authenticated',
        False,
    ):
        return None

    profile = getattr(
        user,
        'professional_profile',
        None,
    )

    if profile is None:
        return None

    if (
        profile.verification_status
        != ProfessionalProfile
        .VerificationStatus
        .VERIFIED
        or not profile.is_public
    ):
        return None

    return profile



def activities_home(request):

    """

    Catálogo público de Actividades.

    """



    today = timezone.localdate()

    professional_profile = (
        _verified_professional_profile(
            request.user
        )
    )



    activities = list(

        _published_activity_queryset()

        .filter(date__gte=today)

    )



    published_count = len(activities)



    community_count = sum(

        1

        for activity in activities

        if (

            activity.activity_type

            == Activity.ActivityType.COMMUNITY

        )

    )



    professional_count = sum(

        1

        for activity in activities

        if (

            activity.activity_type

            == Activity.ActivityType.PROFESSIONAL

        )

    )



    return render(

        request,

        'activities/home.html',

        {

            'activities': activities,

            'published_count': published_count,

            'community_count': community_count,

            'professional_count': professional_count,
            'professional_profile': professional_profile,
            'can_create_professional': (
                professional_profile is not None
            ),

        },

    )





@login_required(login_url='accounts:login')

def my_activities(request):

    """

    Actividades organizadas por el Miembro

    y actividades en las que participa.

    """



    organized_activities = (

        Activity.objects

        .filter(

            organizer=request.user,

        )

        .select_related(

            'category',

            'commune',

            'commune__region',
            'professional_profile',
            'professional_profile__user',
            'space_booking',
            'space_booking__space',

        )

        .order_by(

            '-date',

            '-start_time',

            '-created_at',

        )

    )



    joined_registrations = (

        ActivityRegistration.objects

        .filter(

            member=request.user,

        )

        .select_related(

            'activity',

            'activity__organizer',

            'activity__category',

            'activity__commune',

            'activity__commune__region',
            'activity__professional_profile',
            'activity__professional_profile__user',
            'activity__space_booking',
            'activity__space_booking__space',

        )

        .order_by(

            '-activity__date',

            '-activity__start_time',

        )

    )



    professional_profile = (
        _verified_professional_profile(
            request.user
        )
    )



    return render(

        request,

        'activities/my_activities.html',

        {

            'organized_activities': organized_activities,

            'joined_registrations': joined_registrations,
            'professional_profile': professional_profile,
            'can_create_professional': (
                professional_profile is not None
            ),

        },

    )





@login_required(login_url='accounts:login')

def create_community_activity(request):

    """

    Crear una actividad comunitaria.



    La región del Miembro puede utilizarse como referencia,

    pero la comuna debe seleccionarse conscientemente.

    """



    initial = {

        'date': timezone.localdate(),

    }



    if request.user.commune_id:

        initial['region'] = (

            request.user.commune.region_id

        )



    if request.method == 'POST':

        form = CommunityActivityForm(

            request.POST,

            request.FILES,

        )



        if form.is_valid():

            action = request.POST.get(

                'action',

                'draft',

            )



            try:

                with transaction.atomic():

                    activity = form.save(

                        commit=False

                    )



                    activity.organizer = (

                        request.user

                    )



                    activity.activity_type = (

                        Activity

                        .ActivityType

                        .COMMUNITY

                    )



                    activity.modality = (

                        Activity

                        .Modality

                        .IN_PERSON

                    )



                    activity.price = 0

                    activity.professional_profile = None



                    activity.status = (

                        Activity.Status.DRAFT

                    )



                    activity.full_clean()

                    activity.save()



                    if action == 'publish':

                        activity.publish()



            except ValidationError as exc:

                for message in exc.messages:

                    form.add_error(

                        None,

                        message,

                    )



            else:

                if action == 'publish':

                    messages.success(

                        request,

                        (

                            'Tu actividad comunitaria '

                            'quedó publicada.'

                        ),

                    )



                    return redirect(

                        'activities:detail',

                        activity_id=activity.pk,

                    )



                messages.success(

                    request,

                    (

                        'Tu actividad quedó guardada '

                        'como borrador.'

                    ),

                )



                return redirect(

                    'activities:my_activities'

                )



    else:

        form = CommunityActivityForm(

            initial=initial

        )



    return render(

        request,

        'activities/create_community.html',

        {

            'form': form,

        },

    )





@login_required(login_url='accounts:login')

def edit_community_activity(

    request,

    activity_id,

):

    """

    Editar una actividad comunitaria propia.



    Solamente el organizador puede editarla.



    Se permite editar actividades:

    - Borrador.

    - Publicadas.



    Editar una actividad publicada no cuenta como

    una nueva publicación semanal.

    """



    activity = get_object_or_404(

        Activity.objects.select_related(

            'organizer',

            'category',

            'commune',

            'commune__region',

        ),

        pk=activity_id,

        organizer=request.user,

        activity_type=(

            Activity.ActivityType.COMMUNITY

        ),

        status__in=[

            Activity.Status.DRAFT,

            Activity.Status.PUBLISHED,

        ],

    )



    if request.method == 'POST':

        form = CommunityActivityForm(

            request.POST,

            request.FILES,

            instance=activity,

        )



        if form.is_valid():

            try:

                with transaction.atomic():

                    locked_activity = (

                        get_object_or_404(

                            Activity.objects

                            .select_for_update(),

                            pk=activity.pk,

                            organizer=request.user,

                            activity_type=(

                                Activity

                                .ActivityType

                                .COMMUNITY

                            ),

                            status__in=[

                                Activity.Status.DRAFT,

                                Activity.Status.PUBLISHED,

                            ],

                        )

                    )



                    form = CommunityActivityForm(

                        request.POST,

                        request.FILES,

                        instance=locked_activity,

                    )



                    if not form.is_valid():

                        raise ValidationError(

                            (

                                'Revisa los datos '

                                'antes de guardar '

                                'los cambios.'

                            )

                        )



                    updated_activity = (

                        form.save(

                            commit=False

                        )

                    )



                    updated_activity.organizer = (

                        request.user

                    )



                    updated_activity.activity_type = (

                        Activity

                        .ActivityType

                        .COMMUNITY

                    )



                    updated_activity.modality = (

                        Activity

                        .Modality

                        .IN_PERSON

                    )



                    updated_activity.price = 0



                    updated_activity.professional_profile = (

                        None

                    )



                    updated_activity.full_clean()

                    updated_activity.save()



            except ValidationError as exc:

                for message in exc.messages:

                    form.add_error(

                        None,

                        message,

                    )



            else:

                messages.success(

                    request,

                    (

                        'Los cambios de tu actividad '

                        'se guardaron correctamente.'

                    ),

                )



                return redirect(

                    'activities:detail',

                    activity_id=activity.pk,

                )



    else:

        form = CommunityActivityForm(

            instance=activity,

        )



    return render(

        request,

        'activities/edit_community.html',

        {

            'form': form,

            'activity': activity,

        },

    )





@login_required(login_url='accounts:login')
def create_professional_activity(request):
    """
    Crear una actividad profesional.

    Solo un Profesional verificado y público puede usar
    este flujo. La actividad puede ser gratuita o pagada,
    presencial, online o híbrida.
    """

    professional_profile = (
        _verified_professional_profile(
            request.user
        )
    )

    if professional_profile is None:
        messages.error(
            request,
            (
                'Necesitas un Perfil Profesional verificado '
                'y público para crear actividades profesionales.'
            ),
        )

        return redirect(
            'activities:home'
        )

    initial = {
        'date': timezone.localdate(),
        'modality': Activity.Modality.IN_PERSON,
        'price': 0,
    }

    if request.user.commune_id:
        initial['region'] = (
            request.user.commune.region_id
        )

    if request.method == 'POST':
        form = ProfessionalActivityForm(
            request.POST,
            request.FILES,
            user=request.user,
            professional_profile=(
                professional_profile
            ),
        )

        if form.is_valid():
            action = request.POST.get(
                'action',
                'draft',
            )

            try:
                with transaction.atomic():
                    activity = form.save(
                        commit=False
                    )

                    activity.organizer = (
                        request.user
                    )

                    activity.activity_type = (
                        Activity
                        .ActivityType
                        .PROFESSIONAL
                    )

                    activity.professional_profile = (
                        professional_profile
                    )

                    activity.status = (
                        Activity.Status.DRAFT
                    )

                    activity.full_clean()
                    activity.save()

                    if action == 'publish':
                        activity.publish()

            except ValidationError as exc:
                for message in exc.messages:
                    form.add_error(
                        None,
                        message,
                    )

            else:
                if action == 'publish':
                    messages.success(
                        request,
                        (
                            'Tu actividad profesional '
                            'quedó publicada.'
                        ),
                    )

                    return redirect(
                        'activities:detail',
                        activity_id=activity.pk,
                    )

                messages.success(
                    request,
                    (
                        'Tu actividad profesional quedó '
                        'guardada como borrador.'
                    ),
                )

                return redirect(
                    'activities:my_activities'
                )

    else:
        form = ProfessionalActivityForm(
            initial=initial,
            user=request.user,
            professional_profile=(
                professional_profile
            ),
        )

    return render(
        request,
        'activities/professional_form.html',
        {
            'form': form,
            'professional_profile': (
                professional_profile
            ),
            'is_edit': False,
            'activity': None,
        },
    )


@login_required(login_url='accounts:login')
def edit_professional_activity(
    request,
    activity_id,
):
    """
    Editar una actividad profesional propia que aún se
    encuentre en borrador o publicada.
    """

    professional_profile = (
        _verified_professional_profile(
            request.user
        )
    )

    if professional_profile is None:
        messages.error(
            request,
            (
                'Tu Perfil Profesional debe estar '
                'verificado y público.'
            ),
        )

        return redirect(
            'activities:home'
        )

    activity = get_object_or_404(
        Activity.objects
        .select_related(
            'organizer',
            'professional_profile',
            'category',
            'commune',
            'commune__region',
            'space_booking',
            'space_booking__space',
            'space_booking__space__commune',
            'space_booking__space__commune__region',
        ),
        pk=activity_id,
        organizer=request.user,
        professional_profile=professional_profile,
        activity_type=(
            Activity.ActivityType.PROFESSIONAL
        ),
        status__in=[
            Activity.Status.DRAFT,
            Activity.Status.PUBLISHED,
        ],
    )

    if request.method == 'POST':
        form = ProfessionalActivityForm(
            request.POST,
            request.FILES,
            instance=activity,
            user=request.user,
            professional_profile=(
                professional_profile
            ),
        )

        if form.is_valid():
            action = request.POST.get(
                'action',
                'save',
            )

            try:
                with transaction.atomic():
                    locked_activity = (
                        get_object_or_404(
                            Activity.objects
                            .select_for_update(),
                            pk=activity.pk,
                            organizer=request.user,
                            professional_profile=(
                                professional_profile
                            ),
                            activity_type=(
                                Activity
                                .ActivityType
                                .PROFESSIONAL
                            ),
                            status__in=[
                                Activity.Status.DRAFT,
                                Activity.Status.PUBLISHED,
                            ],
                        )
                    )

                    form = ProfessionalActivityForm(
                        request.POST,
                        request.FILES,
                        instance=locked_activity,
                        user=request.user,
                        professional_profile=(
                            professional_profile
                        ),
                    )

                    if not form.is_valid():
                        raise ValidationError(
                            (
                                'Revisa los datos antes '
                                'de guardar los cambios.'
                            )
                        )

                    updated_activity = (
                        form.save(
                            commit=False
                        )
                    )

                    updated_activity.organizer = (
                        request.user
                    )

                    updated_activity.activity_type = (
                        Activity
                        .ActivityType
                        .PROFESSIONAL
                    )

                    updated_activity.professional_profile = (
                        professional_profile
                    )

                    updated_activity.full_clean()
                    updated_activity.save()

                    if (
                        action == 'publish'
                        and updated_activity.status
                        == Activity.Status.DRAFT
                    ):
                        updated_activity.publish()

            except ValidationError as exc:
                for message in exc.messages:
                    form.add_error(
                        None,
                        message,
                    )

            else:
                if (
                    action == 'publish'
                    and updated_activity.status
                    == Activity.Status.PUBLISHED
                ):
                    messages.success(
                        request,
                        (
                            'Los cambios se guardaron y tu '
                            'actividad profesional quedó publicada.'
                        ),
                    )

                else:
                    messages.success(
                        request,
                        (
                            'Los cambios de tu actividad '
                            'profesional se guardaron correctamente.'
                        ),
                    )

                return redirect(
                    'activities:detail',
                    activity_id=activity.pk,
                )

    else:
        form = ProfessionalActivityForm(
            instance=activity,
            user=request.user,
            professional_profile=(
                professional_profile
            ),
        )

    return render(
        request,
        'activities/professional_form.html',
        {
            'form': form,
            'professional_profile': (
                professional_profile
            ),
            'is_edit': True,
            'activity': activity,
        },
    )


@login_required(login_url='accounts:login')
def publish_professional_activity(
    request,
    activity_id,
):
    """
    Publicar un borrador profesional.
    """

    if request.method != 'POST':
        return redirect(
            'activities:detail',
            activity_id=activity_id,
        )

    professional_profile = (
        _verified_professional_profile(
            request.user
        )
    )

    if professional_profile is None:
        messages.error(
            request,
            (
                'Tu Perfil Profesional debe estar '
                'verificado y público.'
            ),
        )

        return redirect(
            'activities:home'
        )

    try:
        with transaction.atomic():
            activity = get_object_or_404(
                Activity.objects
                .select_for_update(),
                pk=activity_id,
                organizer=request.user,
                professional_profile=(
                    professional_profile
                ),
                activity_type=(
                    Activity
                    .ActivityType
                    .PROFESSIONAL
                ),
            )

            if (
                activity.status
                != Activity.Status.DRAFT
            ):
                messages.info(
                    request,
                    (
                        'Esta actividad ya no '
                        'está en borrador.'
                    ),
                )

                return redirect(
                    'activities:detail',
                    activity_id=activity.pk,
                )

            activity.publish()

    except ValidationError as exc:
        messages.error(
            request,
            ' '.join(exc.messages),
        )

        return redirect(
            'activities:detail',
            activity_id=activity_id,
        )

    messages.success(
        request,
        (
            'Tu actividad profesional '
            'quedó publicada.'
        ),
    )

    return redirect(
        'activities:detail',
        activity_id=activity_id,
    )



def activity_detail(

    request,

    activity_id,

):

    """

    Ficha pública de una actividad.



    El organizador también puede revisar

    sus propios borradores.

    """



    queryset = (

        Activity.objects

        .select_related(

            'organizer',

            'category',

            'commune',

            'commune__region',

            'professional_profile',

            'professional_profile__user',
            'space_booking',
            'space_booking__space',
            'space_booking__space__commune',
            'space_booking__space__commune__region',

        )

    )



    if request.user.is_authenticated:

        queryset = queryset.filter(

            Q(

                status=(

                    Activity.Status.PUBLISHED

                )

            )

            |

            Q(

                organizer=request.user

            )

        )



    else:

        queryset = queryset.filter(

            status=Activity.Status.PUBLISHED

        )



    activity = get_object_or_404(

        queryset,

        pk=activity_id,

    )



    registration = None



    if request.user.is_authenticated:

        registration = (

            ActivityRegistration.objects

            .filter(

                activity=activity,

                member=request.user,

            )

            .first()

        )



    can_join = (

        activity.status

        == Activity.Status.PUBLISHED



        and activity.date

        >= timezone.localdate()



        and not activity.is_full

        and not (
            activity.activity_type
            == Activity.ActivityType.PROFESSIONAL
            and activity.price > 0
        )



        and (

            not request.user.is_authenticated

            or activity.organizer_id

            != request.user.id

        )



        and (

            registration is None

            or registration.status

            == ActivityRegistration.Status.CANCELLED

        )

    )



    is_registered = (

        registration is not None

        and registration.status

        == ActivityRegistration.Status.REGISTERED

    )

    is_owner = (
        request.user.is_authenticated
        and activity.organizer_id
        == request.user.id
    )

    can_access_online_info = (
        is_owner
        or is_registered
    )

    paid_registration_pending = (
        activity.activity_type
        == Activity.ActivityType.PROFESSIONAL
        and activity.price > 0
        and not is_owner
        and not is_registered
    )



    return render(

        request,

        'activities/detail.html',

        {

            'activity': activity,

            'registration': registration,

            'can_join': can_join,

            'is_registered': is_registered,
            'is_owner': is_owner,
            'can_access_online_info': (
                can_access_online_info
            ),
            'paid_registration_pending': (
                paid_registration_pending
            ),

        },

    )





@login_required(login_url='accounts:login')

def publish_community_activity(

    request,

    activity_id,

):

    """

    Publicar un borrador comunitario.

    """



    if request.method != 'POST':

        return redirect(

            'activities:detail',

            activity_id=activity_id,

        )



    try:

        with transaction.atomic():

            activity = get_object_or_404(

                Activity.objects

                .select_for_update(),

                pk=activity_id,

                organizer=request.user,

                activity_type=(

                    Activity

                    .ActivityType

                    .COMMUNITY

                ),

            )



            if (

                activity.status

                != Activity.Status.DRAFT

            ):

                messages.info(

                    request,

                    (

                        'Esta actividad ya no '

                        'está en borrador.'

                    ),

                )



                return redirect(

                    'activities:detail',

                    activity_id=activity.pk,

                )



            activity.publish()



    except ValidationError as exc:

        messages.error(

            request,

            ' '.join(exc.messages),

        )



        return redirect(

            'activities:detail',

            activity_id=activity_id,

        )



    messages.success(

        request,

        (

            'Tu actividad comunitaria '

            'quedó publicada.'

        ),

    )



    return redirect(

        'activities:detail',

        activity_id=activity_id,

    )





@login_required(login_url='accounts:login')

def join_activity(

    request,

    activity_id,

):

    """

    Inscribir a un Miembro en una actividad.



    Se bloquea la actividad mientras se calcula el

    cupo para evitar superar la capacidad máxima.

    """



    if request.method != 'POST':

        return redirect(

            'activities:detail',

            activity_id=activity_id,

        )



    with transaction.atomic():

        activity = get_object_or_404(

            Activity.objects

            .select_for_update(),

            pk=activity_id,

            status=(

                Activity.Status.PUBLISHED

            ),

        )



        if (

            activity.date

            < timezone.localdate()

        ):

            messages.error(

                request,

                (

                    'Esta actividad ya ocurrió '

                    'y no admite nuevas inscripciones.'

                ),

            )



            return redirect(

                'activities:detail',

                activity_id=activity.pk,

            )



        if (

            activity.organizer_id

            == request.user.id

        ):

            messages.info(

                request,

                (

                    'Eres quien organiza esta actividad; '

                    'no necesitas inscribirte.'

                ),

            )



            return redirect(

                'activities:detail',

                activity_id=activity.pk,

            )



        if (
            activity.activity_type
            == Activity.ActivityType.PROFESSIONAL
            and activity.price > 0
        ):
            messages.info(
                request,
                (
                    'Esta actividad requiere pago. '
                    'La inscripción pagada se habilitará '
                    'junto al módulo de pagos.'
                ),
            )

            return redirect(
                'activities:detail',
                activity_id=activity.pk,
            )



        active_count = (

            ActivityRegistration.objects

            .filter(

                activity=activity,

                status=(

                    ActivityRegistration

                    .Status

                    .REGISTERED

                ),

            )

            .count()

        )



        if (

            active_count

            >= activity.capacity

        ):

            messages.error(

                request,

                (

                    'Los cupos de esta actividad '

                    'ya están completos.'

                ),

            )



            return redirect(

                'activities:detail',

                activity_id=activity.pk,

            )



        registration, created = (

            ActivityRegistration.objects

            .get_or_create(

                activity=activity,

                member=request.user,

                defaults={

                    'status': (

                        ActivityRegistration

                        .Status

                        .REGISTERED

                    ),

                },

            )

        )



        if not created:

            if (

                registration.status

                == ActivityRegistration

                .Status

                .CANCELLED

            ):

                registration.status = (

                    ActivityRegistration

                    .Status

                    .REGISTERED

                )



                registration.full_clean()



                registration.save(

                    update_fields=[

                        'status',

                        'updated_at',

                    ]

                )



            elif (

                registration.status

                == ActivityRegistration

                .Status

                .REGISTERED

            ):

                messages.info(

                    request,

                    (

                        'Ya estás inscrito '

                        'en esta actividad.'

                    ),

                )



                return redirect(

                    'activities:detail',

                    activity_id=activity.pk,

                )



            else:

                messages.error(

                    request,

                    (

                        'Esta inscripción ya tiene '

                        'un estado final y no puede '

                        'reactivarse.'

                    ),

                )



                return redirect(

                    'activities:detail',

                    activity_id=activity.pk,

                )



    messages.success(

        request,

        (

            'Te uniste a la actividad '

            'correctamente.'

        ),

    )



    return redirect(

        'activities:detail',

        activity_id=activity_id,

    )





@login_required(login_url='accounts:login')

def leave_activity(

    request,

    activity_id,

):

    """

    Liberar el cupo de un Miembro.

    """



    if request.method != 'POST':

        return redirect(

            'activities:detail',

            activity_id=activity_id,

        )



    with transaction.atomic():

        registration = get_object_or_404(

            ActivityRegistration.objects

            .select_for_update()

            .select_related(

                'activity'

            ),

            activity_id=activity_id,

            member=request.user,

            status=(

                ActivityRegistration

                .Status

                .REGISTERED

            ),

        )



        if (
            registration.activity.activity_type
            == Activity.ActivityType.PROFESSIONAL
            and registration.activity.price > 0
        ):
            messages.info(
                request,
                (
                    'Esta inscripción está asociada a un pago aprobado. '
                    'La cancelación y devolución se gestionarán desde '
                    'el flujo de reembolsos del módulo de Pagos.'
                ),
            )

            return redirect(
                'activities:detail',
                activity_id=activity_id,
            )

        registration.status = (

            ActivityRegistration

            .Status

            .CANCELLED

        )



        registration.save(

            update_fields=[

                'status',

                'updated_at',

            ]

        )



    messages.success(

        request,

        (

            'Tu cupo quedó liberado. '

            'Puedes volver a unirte mientras '

            'haya disponibilidad.'

        ),

    )



    return redirect(

        'activities:detail',

        activity_id=activity_id,

    )