from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.utils import timezone

from apps.locations.models import Commune


class ProfessionalCategory(models.Model):
    """
    Categoría general de un profesional.

    Ejemplos:
    Entrenamiento, Kinesiología, Yoga y Movilidad, etc.
    """

    name = models.CharField(
        max_length=120,
        unique=True,
        verbose_name='Nombre'
    )

    slug = models.SlugField(
        max_length=140,
        unique=True,
        verbose_name='Identificador'
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Descripción'
    )

    display_order = models.PositiveIntegerField(
        default=0,
        verbose_name='Orden'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Activa'
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
        verbose_name = 'Categoría profesional'
        verbose_name_plural = 'Categorías profesionales'
        ordering = [
            'display_order',
            'name',
        ]

    def __str__(self):
        return self.name


class ProfessionalSpecialty(models.Model):
    """
    Especialidad perteneciente a una categoría profesional.
    """

    category = models.ForeignKey(
        ProfessionalCategory,
        on_delete=models.PROTECT,
        related_name='specialties',
        verbose_name='Categoría'
    )

    name = models.CharField(
        max_length=150,
        verbose_name='Nombre'
    )

    slug = models.SlugField(
        max_length=170,
        unique=True,
        verbose_name='Identificador'
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Descripción'
    )

    display_order = models.PositiveIntegerField(
        default=0,
        verbose_name='Orden'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Activa'
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
        verbose_name = 'Especialidad profesional'
        verbose_name_plural = 'Especialidades profesionales'

        ordering = [
            'category__display_order',
            'display_order',
            'name',
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'category',
                    'name',
                ],
                name='unique_specialty_per_category'
            )
        ]

    def __str__(self):
        return f'{self.name} - {self.category.name}'


class ProfessionalProfile(models.Model):
    """
    Perfil profesional asociado a una Cuenta Única Universal.
    """

    class VerificationStatus(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        VERIFIED = 'verified', 'Verificado'
        REJECTED = 'rejected', 'Rechazado'
        SUSPENDED = 'suspended', 'Suspendido'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='professional_profile',
        verbose_name='Usuario'
    )

    category = models.ForeignKey(
        ProfessionalCategory,
        on_delete=models.PROTECT,
        related_name='professionals',
        verbose_name='Categoría profesional'
    )

    specialty = models.ForeignKey(
        ProfessionalSpecialty,
        on_delete=models.PROTECT,
        related_name='professionals',
        verbose_name='Especialidad principal'
    )

    professional_title = models.CharField(
        max_length=180,
        blank=True,
        verbose_name='Título profesional o denominación'
    )

    years_experience = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Años de experiencia'
    )

    bio = models.TextField(
        max_length=1500,
        verbose_name='Descripción profesional'
    )

    offers_in_person = models.BooleanField(
        default=False,
        verbose_name='Atención presencial'
    )

    offers_online = models.BooleanField(
        default=False,
        verbose_name='Atención online'
    )

    coverage_communes = models.ManyToManyField(
        Commune,
        blank=True,
        related_name='covered_by_professionals',
        verbose_name='Comunas de cobertura'
    )

    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        verbose_name='Estado de verificación'
    )

    rejection_reason = models.TextField(
        blank=True,
        verbose_name='Motivo de rechazo'
    )

    is_public = models.BooleanField(
        default=False,
        verbose_name='Perfil público'
    )

    requested_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de solicitud'
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de revisión'
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_professional_profiles',
        verbose_name='Revisado por'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización'
    )

    class Meta:
        verbose_name = 'Perfil profesional'
        verbose_name_plural = 'Perfiles profesionales'

    def __str__(self):
        return (
            f'{self.user} - '
            f'{self.get_verification_status_display()}'
        )


class ProfessionalCredential(models.Model):
    """
    Documento o acreditación presentada por un profesional
    como respaldo de su formación, certificación o experiencia.

    Un perfil profesional puede tener múltiples acreditaciones.
    """

    class CredentialType(models.TextChoices):
        PROFESSIONAL_DEGREE = (
            'professional_degree',
            'Título profesional'
        )

        TECHNICAL_DEGREE = (
            'technical_degree',
            'Título técnico'
        )

        CERTIFICATION = (
            'certification',
            'Certificación'
        )

        LICENSE = (
            'license',
            'Licencia o credencial'
        )

        SPECIALIZATION = (
            'specialization',
            'Curso de especialización'
        )

        OTHER = (
            'other',
            'Otro respaldo'
        )

    class ReviewStatus(models.TextChoices):
        PENDING = (
            'pending',
            'Pendiente'
        )

        VERIFIED = (
            'verified',
            'Verificado'
        )

        REJECTED = (
            'rejected',
            'Rechazado'
        )

    professional_profile = models.ForeignKey(
        ProfessionalProfile,
        on_delete=models.CASCADE,
        related_name='credentials',
        verbose_name='Perfil profesional'
    )

    credential_type = models.CharField(
        max_length=30,
        choices=CredentialType.choices,
        verbose_name='Tipo de acreditación'
    )

    name = models.CharField(
        max_length=180,
        verbose_name='Nombre de la acreditación'
    )

    issuing_institution = models.CharField(
        max_length=180,
        verbose_name='Institución emisora'
    )

    issue_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='Fecha de emisión'
    )

    expiration_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='Fecha de vencimiento'
    )

    document = models.FileField(
        upload_to='professional_credentials/',
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    'pdf',
                    'jpg',
                    'jpeg',
                    'png',
                ]
            )
        ],
        verbose_name='Documento'
    )

    review_status = models.CharField(
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        verbose_name='Estado de revisión'
    )

    rejection_reason = models.TextField(
        blank=True,
        verbose_name='Motivo de rechazo'
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de revisión'
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_professional_credentials',
        verbose_name='Revisado por'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de carga'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización'
    )

    class Meta:
        verbose_name = 'Acreditación profesional'
        verbose_name_plural = 'Acreditaciones profesionales'

        ordering = [
            '-created_at',
        ]

    def __str__(self):
        return (
            f'{self.name} - '
            f'{self.professional_profile.user}'
        )


class ProfessionalService(models.Model):
    """
    Servicio ofrecido por un Profesional verificado
    dentro de EntrenamientoyComunidad.

    Cada Profesional puede administrar múltiples servicios.
    """

    class ServiceMode(models.TextChoices):
        IN_PERSON = (
            'in_person',
            'Presencial'
        )

        ONLINE = (
            'online',
            'Online'
        )

        HYBRID = (
            'hybrid',
            'Presencial y online'
        )

    class InPersonLocationType(models.TextChoices):
        PROFESSIONAL_PLACE = (
            'professional_place',
            'Lugar propio del profesional'
        )

        USER_HOME = (
            'user_home',
            'Domicilio del usuario'
        )

        AGREED_PLACE = (
            'agreed_place',
            'Lugar acordado con el usuario'
        )

    class PublicationStatus(models.TextChoices):
        DRAFT = (
            'draft',
            'Borrador'
        )

        PUBLISHED = (
            'published',
            'Publicado'
        )

        PAUSED = (
            'paused',
            'Pausado'
        )

    professional_profile = models.ForeignKey(
        ProfessionalProfile,
        on_delete=models.CASCADE,
        related_name='services',
        verbose_name='Perfil profesional'
    )

    name = models.CharField(
        max_length=180,
        verbose_name='Nombre del servicio'
    )

    description = models.TextField(
        max_length=2000,
        verbose_name='Descripción'
    )

    mode = models.CharField(
        max_length=20,
        choices=ServiceMode.choices,
        verbose_name='Modalidad'
    )

    duration_minutes = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(15),
            MaxValueValidator(480),
        ],
        verbose_name='Duración en minutos'
    )

    price = models.PositiveIntegerField(
        verbose_name='Precio (CLP)'
    )

    publication_status = models.CharField(
        max_length=20,
        choices=PublicationStatus.choices,
        default=PublicationStatus.DRAFT,
        verbose_name='Estado de publicación'
    )

    in_person_location_type = models.CharField(
        max_length=30,
        choices=InPersonLocationType.choices,
        blank=True,
        verbose_name='Tipo de lugar presencial'
    )

    location_name = models.CharField(
        max_length=180,
        blank=True,
        verbose_name='Nombre o referencia del lugar'
    )

    location_address = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Dirección del lugar'
    )

    location_commune = models.ForeignKey(
        Commune,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='professional_services',
        verbose_name='Comuna del lugar'
    )

    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de primera publicación'
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
        verbose_name = 'Servicio profesional'
        verbose_name_plural = 'Servicios profesionales'

        ordering = [
            '-created_at',
        ]

    def clean(self):
        """
        Valida que el servicio sea compatible con
        el Perfil Profesional asociado.
        """

        super().clean()

        if not self.professional_profile_id:
            return

        professional_profile = (
            self.professional_profile
        )

        # -------------------------------------------------
        # MODALIDAD PRESENCIAL
        # -------------------------------------------------

        if (
            self.mode
            in (
                self.ServiceMode.IN_PERSON,
                self.ServiceMode.HYBRID,
            )
            and not professional_profile.offers_in_person
        ):
            raise ValidationError(
                {
                    'mode': (
                        'El Perfil Profesional no tiene '
                        'habilitada la atención presencial.'
                    )
                }
            )

        # -------------------------------------------------
        # MODALIDAD ONLINE
        # -------------------------------------------------

        if (
            self.mode
            in (
                self.ServiceMode.ONLINE,
                self.ServiceMode.HYBRID,
            )
            and not professional_profile.offers_online
        ):
            raise ValidationError(
                {
                    'mode': (
                        'El Perfil Profesional no tiene '
                        'habilitada la atención online.'
                    )
                }
            )

        # -------------------------------------------------
        # LUGAR DE ATENCIÓN PRESENCIAL
        # -------------------------------------------------

        uses_in_person_mode = (
            self.mode
            in (
                self.ServiceMode.IN_PERSON,
                self.ServiceMode.HYBRID,
            )
        )

        if uses_in_person_mode:

            # Un borrador puede estar incompleto.
            # La ubicación pasa a ser obligatoria
            # cuando el servicio se publica.
            if (
                self.publication_status
                == self.PublicationStatus.PUBLISHED
            ):

                if not self.in_person_location_type:
                    raise ValidationError(
                        {
                            'in_person_location_type': (
                                'Debes indicar cómo se realizará '
                                'la atención presencial antes de '
                                'publicar el servicio.'
                            )
                        }
                    )

                if (
                    self.in_person_location_type
                    == self.InPersonLocationType.PROFESSIONAL_PLACE
                ):

                    if not self.location_name:
                        raise ValidationError(
                            {
                                'location_name': (
                                    'Debes indicar el nombre o una '
                                    'referencia del lugar de atención.'
                                )
                            }
                        )

                    if not self.location_address:
                        raise ValidationError(
                            {
                                'location_address': (
                                    'Debes indicar la dirección del '
                                    'lugar de atención.'
                                )
                            }
                        )

                    if not self.location_commune:
                        raise ValidationError(
                            {
                                'location_commune': (
                                    'Debes indicar la comuna del '
                                    'lugar de atención.'
                                )
                            }
                        )

            if (
                self.in_person_location_type
                == self.InPersonLocationType.USER_HOME
            ):

                self.location_name = ''
                self.location_address = ''
                self.location_commune = None

            elif (
                self.in_person_location_type
                == self.InPersonLocationType.AGREED_PLACE
            ):

                self.location_address = ''
                self.location_commune = None

        else:

            self.in_person_location_type = ''
            self.location_name = ''
            self.location_address = ''
            self.location_commune = None

        # -------------------------------------------------
        # PUBLICACIÓN
        # -------------------------------------------------

        if (
            self.publication_status
            == self.PublicationStatus.PUBLISHED
        ):

            if (
                professional_profile.verification_status
                != ProfessionalProfile
                .VerificationStatus
                .VERIFIED
            ):
                raise ValidationError(
                    {
                        'publication_status': (
                            'Solo los Profesionales verificados '
                            'pueden publicar servicios.'
                        )
                    }
                )

            if not professional_profile.is_public:
                raise ValidationError(
                    {
                        'publication_status': (
                            'El Perfil Profesional debe estar '
                            'habilitado públicamente antes de '
                            'publicar servicios.'
                        )
                    }
                )

    def save(
        self,
        *args,
        **kwargs
    ):
        """
        Ejecuta las validaciones del servicio antes
        de guardar el registro.

        La fecha de primera publicación se registra
        automáticamente la primera vez que el servicio
        pasa al estado Publicado.
        """

        if (
            self.publication_status
            == self.PublicationStatus.PUBLISHED
            and self.published_at is None
        ):
            self.published_at = timezone.now()

            update_fields = kwargs.get(
                'update_fields'
            )

            if update_fields is not None:
                kwargs['update_fields'] = list(
                    set(update_fields) | {
                        'published_at',
                    }
                )

        self.full_clean()

        return super().save(
            *args,
            **kwargs
        )

    def generate_reservable_slots_for_date(
        self,
        target_date
    ):
        """
        Genera dinámicamente los bloques horarios reservables
        de este servicio para una fecha concreta.

        No crea registros en la base de datos.

        Solo genera horarios cuando:
        - el servicio está Publicado;
        - existe disponibilidad activa para ese día;
        - la fecha se encuentra dentro de la vigencia;
        - cada bloque puede completar exactamente la duración
          definida en duration_minutes.

        Ejemplo:
        disponibilidad 18:30 a 21:30
        duración 75 minutos

        Resultado:
        18:30 a 19:45
        19:45 a 21:00

        Los 30 minutos restantes no forman un bloque porque
        no alcanzan para completar los 75 minutos.
        """

        if isinstance(
            target_date,
            datetime
        ):
            target_date = target_date.date()

        if not isinstance(
            target_date,
            date
        ):
            raise ValueError(
                'target_date debe ser una fecha válida.'
            )

        if (
            self.publication_status
            != self.PublicationStatus.PUBLISHED
        ):
            return []

        availabilities = (
            self.availabilities
            .filter(
                is_active=True,
                weekday=target_date.weekday(),
                valid_from__lte=target_date,
            )
            .filter(
                models.Q(
                    valid_until__isnull=True
                )
                | models.Q(
                    valid_until__gte=target_date
                )
            )
            .order_by(
                'start_time'
            )
        )

        slots = []

        for availability in availabilities:

            slots.extend(
                availability
                .generate_time_slots_for_date(
                    target_date
                )
            )

        slots.sort(
            key=lambda slot: (
                slot['start_time']
            )
        )

        return slots

    def __str__(self):
        return (
            f'{self.name} - '
            f'{self.professional_profile.user}'
        )


class ProfessionalServiceAvailability(models.Model):
    """
    Bloque de disponibilidad recurrente asociado a un servicio
    profesional.

    Ejemplo:
    Lunes de 18:00 a 21:00, vigente desde una fecha determinada.

    Este modelo define ventanas de atención. Las horas reservables
    concretas se generarán posteriormente considerando la duración
    del servicio y las reservas existentes.
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Lunes'
        TUESDAY = 1, 'Martes'
        WEDNESDAY = 2, 'Miércoles'
        THURSDAY = 3, 'Jueves'
        FRIDAY = 4, 'Viernes'
        SATURDAY = 5, 'Sábado'
        SUNDAY = 6, 'Domingo'

    service = models.ForeignKey(
        ProfessionalService,
        on_delete=models.CASCADE,
        related_name='availabilities',
        verbose_name='Servicio profesional'
    )

    weekday = models.PositiveSmallIntegerField(
        choices=Weekday.choices,
        verbose_name='Día de la semana'
    )

    start_time = models.TimeField(
        verbose_name='Hora de inicio'
    )

    end_time = models.TimeField(
        verbose_name='Hora de término'
    )

    valid_from = models.DateField(
        verbose_name='Vigente desde'
    )

    valid_until = models.DateField(
        null=True,
        blank=True,
        verbose_name='Vigente hasta'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Disponibilidad activa'
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
        verbose_name = 'Disponibilidad de servicio profesional'
        verbose_name_plural = 'Disponibilidades de servicios profesionales'

        ordering = [
            'weekday',
            'start_time',
            'valid_from',
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    end_time__gt=models.F('start_time')
                ),
                name='professional_availability_end_after_start',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(valid_until__isnull=True)
                    | models.Q(
                        valid_until__gte=models.F('valid_from')
                    )
                ),
                name='professional_availability_valid_date_range',
            ),
        ]

    def clean(self):
        """
        Valida coherencia horaria, vigencia y solapamientos.
        """

        super().clean()

        if not self.service_id:
            return

        # -------------------------------------------------
        # HORARIO
        # -------------------------------------------------

        if (
            self.start_time
            and self.end_time
            and self.end_time <= self.start_time
        ):
            raise ValidationError(
                {
                    'end_time': (
                        'La hora de término debe ser posterior '
                        'a la hora de inicio.'
                    )
                }
            )

        # -------------------------------------------------
        # VIGENCIA
        # -------------------------------------------------

        if (
            self.valid_from
            and self.valid_until
            and self.valid_until < self.valid_from
        ):
            raise ValidationError(
                {
                    'valid_until': (
                        'La fecha de término de vigencia no puede '
                        'ser anterior a la fecha de inicio.'
                    )
                }
            )

        # -------------------------------------------------
        # DURACIÓN MÍNIMA DEL BLOQUE
        # -------------------------------------------------

        if self.start_time and self.end_time:

            start_minutes = (
                self.start_time.hour * 60
                + self.start_time.minute
            )

            end_minutes = (
                self.end_time.hour * 60
                + self.end_time.minute
            )

            available_minutes = (
                end_minutes - start_minutes
            )

            if (
                available_minutes
                < self.service.duration_minutes
            ):
                raise ValidationError(
                    {
                        'end_time': (
                            'El bloque de disponibilidad debe permitir '
                            'al menos una sesión completa de '
                            f'{self.service.duration_minutes} minutos.'
                        )
                    }
                )

        # -------------------------------------------------
        # SOLAPAMIENTOS
        # -------------------------------------------------

        if (
            not self.is_active
            or self.weekday is None
            or not self.start_time
            or not self.end_time
            or not self.valid_from
        ):
            return

        existing_blocks = (
            ProfessionalServiceAvailability.objects
            .filter(
                service_id=self.service_id,
                weekday=self.weekday,
                is_active=True,
            )
            .exclude(pk=self.pk)
        )

        current_valid_until = (
            self.valid_until
            or date.max
        )

        for block in existing_blocks:

            block_valid_until = (
                block.valid_until
                or date.max
            )

            dates_overlap = (
                self.valid_from <= block_valid_until
                and block.valid_from <= current_valid_until
            )

            times_overlap = (
                self.start_time < block.end_time
                and self.end_time > block.start_time
            )

            if dates_overlap and times_overlap:
                raise ValidationError(
                    {
                        'start_time': (
                            'Este horario se superpone con otra '
                            'disponibilidad activa del mismo servicio.'
                        ),
                        'end_time': (
                            'Este horario se superpone con otra '
                            'disponibilidad activa del mismo servicio.'
                        ),
                    }
                )

    def save(
        self,
        *args,
        **kwargs
    ):
        """
        Ejecuta las validaciones antes de guardar.
        """

        self.full_clean()

        return super().save(
            *args,
            **kwargs
        )

    def applies_to_date(
        self,
        target_date
    ):
        """
        Indica si este bloque recurrente aplica a una fecha
        determinada.

        No modifica información en la base de datos.
        """

        if isinstance(
            target_date,
            datetime
        ):
            target_date = target_date.date()

        if not isinstance(
            target_date,
            date
        ):
            raise ValueError(
                'target_date debe ser una fecha válida.'
            )

        if not self.is_active:
            return False

        if (
            target_date.weekday()
            != self.weekday
        ):
            return False

        if (
            target_date
            < self.valid_from
        ):
            return False

        if (
            self.valid_until
            and target_date
            > self.valid_until
        ):
            return False

        return True

    def generate_time_slots_for_date(
        self,
        target_date
    ):
        """
        Divide este bloque de disponibilidad en sesiones
        consecutivas cuya duración coincide exactamente con
        duration_minutes del servicio.

        No guarda horarios futuros en PostgreSQL.

        Un remanente inferior a la duración completa del
        servicio se descarta automáticamente.
        """

        if isinstance(
            target_date,
            datetime
        ):
            target_date = target_date.date()

        if not self.applies_to_date(
            target_date
        ):
            return []

        duration = timedelta(
            minutes=(
                self.service
                .duration_minutes
            )
        )

        current_start = datetime.combine(
            target_date,
            self.start_time,
        )

        availability_end = datetime.combine(
            target_date,
            self.end_time,
        )

        slots = []

        while (
            current_start + duration
            <= availability_end
        ):

            current_end = (
                current_start
                + duration
            )

            slots.append(
                {
                    'availability_id': self.pk,
                    'date': target_date,
                    'start_time': (
                        current_start
                        .time()
                        .replace(
                            second=0,
                            microsecond=0,
                        )
                    ),
                    'end_time': (
                        current_end
                        .time()
                        .replace(
                            second=0,
                            microsecond=0,
                        )
                    ),
                    'start_datetime': (
                        current_start
                    ),
                    'end_datetime': (
                        current_end
                    ),
                    'duration_minutes': (
                        self.service
                        .duration_minutes
                    ),
                }
            )

            current_start = (
                current_end
            )

        return slots

    def audit_snapshot(self):
        """
        Devuelve una fotografía serializable del estado actual
        de la disponibilidad para conservar trazabilidad.
        """

        return {
            'weekday': self.weekday,
            'weekday_display': (
                self.get_weekday_display()
                if self.weekday is not None
                else None
            ),
            'start_time': (
                self.start_time.isoformat()
                if self.start_time
                else None
            ),
            'end_time': (
                self.end_time.isoformat()
                if self.end_time
                else None
            ),
            'valid_from': (
                self.valid_from.isoformat()
                if self.valid_from
                else None
            ),
            'valid_until': (
                self.valid_until.isoformat()
                if self.valid_until
                else None
            ),
            'is_active': self.is_active,
        }

    def __str__(self):
        return (
            f'{self.service.name} - '
            f'{self.get_weekday_display()} '
            f'{self.start_time.strftime("%H:%M")} a '
            f'{self.end_time.strftime("%H:%M")}'
        )


class ProfessionalServiceAvailabilityHistory(models.Model):
    """
    Historial inmutable de cambios realizados sobre una
    disponibilidad profesional.

    No reemplaza a ProfessionalServiceAvailability: conserva
    fotografías antes y después de cada acción relevante.
    """

    class Action(models.TextChoices):
        CREATED = 'created', 'Creada'
        UPDATED = 'updated', 'Editada'
        ACTIVATED = 'activated', 'Activada'
        DEACTIVATED = 'deactivated', 'Desactivada'

    availability = models.ForeignKey(
        ProfessionalServiceAvailability,
        on_delete=models.PROTECT,
        related_name='history',
        verbose_name='Disponibilidad'
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        verbose_name='Acción'
    )

    previous_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Estado anterior'
    )

    new_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Estado nuevo'
    )

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='professional_availability_changes',
        verbose_name='Modificado por'
    )

    reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Motivo'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha del cambio'
    )

    class Meta:
        verbose_name = 'Historial de disponibilidad profesional'
        verbose_name_plural = 'Historiales de disponibilidades profesionales'

        ordering = [
            '-created_at',
        ]

    def __str__(self):
        return (
            f'{self.availability} - '
            f'{self.get_action_display()} - '
            f'{self.created_at:%d/%m/%Y %H:%M}'
        )

