from django.conf import settings

from django.core.exceptions import ValidationError

from django.db import models

from django.utils import timezone



from apps.locations.models import Commune

from apps.professionals.models import ProfessionalProfile





class ActivityCategory(models.Model):

    name = models.CharField(

        max_length=80,

        unique=True,

        verbose_name='Nombre'

    )



    slug = models.SlugField(

        max_length=100,

        unique=True,

        verbose_name='Slug'

    )



    is_active = models.BooleanField(

        default=True,

        verbose_name='Activa'

    )



    created_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha de creación'

    )



    class Meta:

        verbose_name = 'Categoría de actividad'

        verbose_name_plural = 'Categorías de actividades'

        ordering = ['name']



    def __str__(self):

        return self.name





class Activity(models.Model):



    class ActivityType(models.TextChoices):

        COMMUNITY = 'community', 'Comunitaria'

        PROFESSIONAL = 'professional', 'Profesional'



    class Modality(models.TextChoices):

        IN_PERSON = 'in_person', 'Presencial'

        ONLINE = 'online', 'Online'

        HYBRID = 'hybrid', 'Híbrida'



    class Level(models.TextChoices):

        ALL = 'all', 'Todos los niveles'

        BEGINNER = 'beginner', 'Inicial'

        INTERMEDIATE = 'intermediate', 'Intermedio'

        ADVANCED = 'advanced', 'Avanzado'



    class Status(models.TextChoices):

        DRAFT = 'draft', 'Borrador'

        PUBLISHED = 'published', 'Publicada'

        FINISHED = 'finished', 'Finalizada'

        CANCELLED = 'cancelled', 'Cancelada'



    organizer = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.PROTECT,

        related_name='organized_activities',

        verbose_name='Organizador'

    )



    activity_type = models.CharField(

        max_length=20,

        choices=ActivityType.choices,

        verbose_name='Tipo de actividad'

    )



    professional_profile = models.ForeignKey(

        ProfessionalProfile,

        on_delete=models.PROTECT,

        related_name='activities',

        null=True,

        blank=True,

        verbose_name='Perfil profesional'

    )



    space_booking = models.ForeignKey(

        'spaces.SpaceBooking',

        on_delete=models.PROTECT,

        related_name='professional_activities',

        null=True,

        blank=True,

        verbose_name='Reserva de espacio asociada'

    )



    category = models.ForeignKey(

        ActivityCategory,

        on_delete=models.PROTECT,

        related_name='activities',

        verbose_name='Categoría'

    )



    title = models.CharField(

        max_length=140,

        verbose_name='Nombre de la actividad'

    )



    description = models.TextField(

        max_length=1000,

        verbose_name='Descripción'

    )



    image = models.ImageField(

        upload_to='activities/',

        null=True,

        blank=True,

        verbose_name='Imagen'

    )



    modality = models.CharField(

        max_length=20,

        choices=Modality.choices,

        default=Modality.IN_PERSON,

        verbose_name='Modalidad'

    )



    date = models.DateField(

        verbose_name='Fecha'

    )



    start_time = models.TimeField(

        verbose_name='Hora de inicio'

    )



    end_time = models.TimeField(

        verbose_name='Hora de término'

    )



    capacity = models.PositiveIntegerField(

        verbose_name='Cupos disponibles'

    )



    level = models.CharField(

        max_length=20,

        choices=Level.choices,

        default=Level.ALL,

        verbose_name='Nivel'

    )



    requirements = models.TextField(

        max_length=600,

        blank=True,

        verbose_name='Requisitos o recomendaciones'

    )



    commune = models.ForeignKey(

        Commune,

        on_delete=models.PROTECT,

        related_name='activities',

        null=True,

        blank=True,

        verbose_name='Comuna'

    )



    meeting_point = models.CharField(

        max_length=180,

        blank=True,

        verbose_name='Punto de encuentro'

    )



    location_reference = models.CharField(

        max_length=255,

        blank=True,

        verbose_name='Dirección o referencia'

    )



    route_or_destination = models.CharField(

        max_length=255,

        blank=True,

        verbose_name='Ruta o destino'

    )



    price = models.PositiveIntegerField(

        default=0,

        verbose_name='Precio por participante'

    )



    online_access_info = models.TextField(

        max_length=500,

        blank=True,

        verbose_name='Información de acceso online'

    )



    status = models.CharField(

        max_length=20,

        choices=Status.choices,

        default=Status.DRAFT,

        verbose_name='Estado'

    )



    published_at = models.DateTimeField(

        null=True,

        blank=True,

        verbose_name='Fecha de publicación'

    )



    created_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha de creación'

    )



    updated_at = models.DateTimeField(

        auto_now=True,

        verbose_name='Última actualización'

    )



    class Meta:

        verbose_name = 'Actividad'

        verbose_name_plural = 'Actividades'

        ordering = ['date', 'start_time', 'id']



    def clean(self):

        errors = {}

        if (
            self.end_time
            and self.start_time
            and self.end_time <= self.start_time
        ):
            errors['end_time'] = (
                'La hora de término debe ser posterior '
                'a la hora de inicio.'
            )

        if (
            self.capacity is not None
            and self.capacity < 1
        ):
            errors['capacity'] = (
                'La actividad debe tener al menos 1 cupo.'
            )

        if self.activity_type == self.ActivityType.COMMUNITY:

            if self.price != 0:
                errors['price'] = (
                    'Las actividades comunitarias deben ser gratuitas.'
                )

            if self.professional_profile_id:
                errors['professional_profile'] = (
                    'Una actividad comunitaria no debe asociarse '
                    'a un perfil profesional.'
                )

            if self.space_booking_id:
                errors['space_booking'] = (
                    'Una actividad comunitaria no utiliza '
                    'una reserva profesional de espacio.'
                )

            if self.modality != self.Modality.IN_PERSON:
                errors['modality'] = (
                    'Por ahora las actividades comunitarias '
                    'serán presenciales.'
                )

        if self.activity_type == self.ActivityType.PROFESSIONAL:

            if not self.professional_profile_id:
                errors['professional_profile'] = (
                    'Una actividad profesional debe estar asociada '
                    'a un perfil profesional.'
                )

            elif (
                self.organizer_id
                and self.professional_profile.user_id
                != self.organizer_id
            ):
                errors['professional_profile'] = (
                    'El Perfil Profesional debe pertenecer '
                    'a la cuenta que organiza la actividad.'
                )

            elif (
                self.professional_profile.verification_status
                != 'verified'
                or not self.professional_profile.is_public
            ):
                errors['professional_profile'] = (
                    'Solo un Profesional verificado y público '
                    'puede publicar actividades profesionales.'
                )

        if self.space_booking_id:

            booking = self.space_booking

            if (
                self.activity_type
                != self.ActivityType.PROFESSIONAL
            ):
                errors['space_booking'] = (
                    'Solo una actividad profesional puede '
                    'asociarse a una reserva de espacio.'
                )

            elif self.modality == self.Modality.ONLINE:
                errors['space_booking'] = (
                    'Una actividad online no necesita '
                    'una reserva de espacio.'
                )

            elif (
                self.organizer_id
                and booking.booked_by_id
                != self.organizer_id
            ):
                errors['space_booking'] = (
                    'La reserva de espacio seleccionada '
                    'no pertenece a tu cuenta.'
                )

            elif booking.status != 'confirmed':
                errors['space_booking'] = (
                    'Solo puedes asociar una reserva '
                    'de espacio confirmada.'
                )

            else:
                if self.date and self.date != booking.session_date:
                    errors['date'] = (
                        'La fecha de la actividad debe coincidir '
                        'con la reserva de espacio asociada.'
                    )

                if (
                    self.start_time
                    and self.start_time < booking.start_time
                ):
                    errors['start_time'] = (
                        'La actividad no puede comenzar antes '
                        'del bloque de espacio reservado.'
                    )

                if (
                    self.end_time
                    and self.end_time > booking.end_time
                ):
                    errors['end_time'] = (
                        'La actividad no puede terminar después '
                        'del bloque de espacio reservado.'
                    )

                if booking.space_id:
                    self.commune = booking.space.commune

                if not self.meeting_point:
                    self.meeting_point = (
                        booking.space_name_snapshot
                        or booking.space.name
                    )

                if not self.location_reference:
                    self.location_reference = (
                        booking.address_snapshot
                        or booking.space.address
                    )

        if self.modality in [
            self.Modality.IN_PERSON,
            self.Modality.HYBRID,
        ]:
            if not self.commune_id:
                errors['commune'] = (
                    'Debes indicar la comuna de la '
                    'actividad presencial.'
                )

            if not self.meeting_point:
                errors['meeting_point'] = (
                    'Debes indicar un punto de encuentro '
                    'para la actividad presencial.'
                )

        if self.modality in [
            self.Modality.ONLINE,
            self.Modality.HYBRID,
        ]:
            if not self.online_access_info:
                errors['online_access_info'] = (
                    'Debes indicar la información de acceso '
                    'para la parte online de la actividad.'
                )

        if errors:
            raise ValidationError(errors)



    def publish(self):

        self.full_clean()



        if self.activity_type == self.ActivityType.COMMUNITY:

            if self.published_at is None:

                from apps.subscriptions.services import (
                    get_member_community_publication_limit,
                )

                now = timezone.localtime()

                week_start = now.date() - timezone.timedelta(days=now.weekday())

                week_end = week_start + timezone.timedelta(days=6)



                publication_limit = (
                    get_member_community_publication_limit(
                        self.organizer,
                        at=now,
                    )
                )



                published_count = (
                    Activity.objects
                    .filter(
                        organizer=self.organizer,
                        activity_type=self.ActivityType.COMMUNITY,
                        published_at__date__range=(week_start, week_end),
                    )
                    .exclude(pk=self.pk)
                    .count()
                )



                if published_count >= publication_limit:

                    if publication_limit == 1:
                        limit_text = (
                            'Tu plan actual permite 1 actividad comunitaria '
                            'publicada por semana.'
                        )
                    else:
                        limit_text = (
                            f'Tu plan actual permite hasta {publication_limit} '
                            'actividades comunitarias publicadas por semana '
                            f'y ya utilizaste las {publication_limit}.'
                        )

                    raise ValidationError(
                        (
                            f'{limit_text} '
                            'Puedes guardar borradores sin consumir este límite.'
                        )
                    )



        self.status = self.Status.PUBLISHED



        if not self.published_at:

            self.published_at = timezone.now()



        self.save(

            update_fields=[

                'status',

                'published_at',

                'updated_at',

            ]

        )



    @property

    def active_registrations_count(self):

        return self.registrations.filter(

            status=ActivityRegistration.Status.REGISTERED

        ).count()



    @property

    def available_spots(self):

        return max(self.capacity - self.active_registrations_count, 0)



    @property

    def is_full(self):

        return self.available_spots <= 0



    def __str__(self):

        return self.title





class ActivityRegistration(models.Model):



    class Status(models.TextChoices):

        REGISTERED = 'registered', 'Inscrito'

        CANCELLED = 'cancelled', 'Cancelado'

        ATTENDED = 'attended', 'Asistió'

        NO_SHOW = 'no_show', 'No asistió'



    activity = models.ForeignKey(

        Activity,

        on_delete=models.PROTECT,

        related_name='registrations',

        verbose_name='Actividad'

    )



    member = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.PROTECT,

        related_name='activity_registrations',

        verbose_name='Miembro'

    )



    status = models.CharField(

        max_length=20,

        choices=Status.choices,

        default=Status.REGISTERED,

        verbose_name='Estado'

    )



    registered_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha de inscripción'

    )



    updated_at = models.DateTimeField(

        auto_now=True,

        verbose_name='Última actualización'

    )



    class Meta:

        verbose_name = 'Inscripción a actividad'

        verbose_name_plural = 'Inscripciones a actividades'

        ordering = ['-registered_at']

        constraints = [

            models.UniqueConstraint(

                fields=['activity', 'member'],

                name='unique_activity_registration_per_member'

            )

        ]



    def clean(self):

        errors = {}



        if self.activity_id and self.member_id:

            if self.activity.organizer_id == self.member_id:

                errors['member'] = (

                    'El organizador no necesita inscribirse en su propia actividad.'

                )



        if errors:

            raise ValidationError(errors)



    def __str__(self):

        return f'{self.member} - {self.activity}'