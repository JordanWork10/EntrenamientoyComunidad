from datetime import datetime, timedelta



from django.conf import settings

from django.core.exceptions import ValidationError

from django.core.validators import (

    FileExtensionValidator,

    MinValueValidator,

)

from django.db import models

from django.utils import timezone



from apps.accounts.models import normalize_rut, validate_rut

from apps.locations.models import Commune





class SpaceProviderProfile(models.Model):

    """

    Perfil de Proveedor de Espacios asociado a una

    Cuenta Única Universal.



    Este perfil representa a la persona u organización

    que administra espacios. Los datos específicos de

    cada recinto se almacenarán posteriormente en el

    módulo de espacios.

    """



    class ProviderType(models.TextChoices):

        INDIVIDUAL = (

            'individual',

            'Persona natural'

        )



        ORGANIZATION = (

            'organization',

            'Organización o negocio'

        )



    class VerificationStatus(models.TextChoices):

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



        SUSPENDED = (

            'suspended',

            'Suspendido'

        )



    INFRASTRUCTURE_TYPE_CHOICES = (

        (

            'gyms',

            'Gimnasios'

        ),

        (

            'sports_halls',

            'Salas deportivas'

        ),

        (

            'studios',

            'Estudios'

        ),

        (

            'courts',

            'Canchas'

        ),

        (

            'multipurpose_rooms',

            'Salas multipropósito'

        ),

        (

            'academies',

            'Academias'

        ),

        (

            'wellness_rooms',

            'Salas de bienestar'

        ),

        (

            'other',

            'Otro'

        ),

    )



    user = models.OneToOneField(

        settings.AUTH_USER_MODEL,

        on_delete=models.CASCADE,

        related_name='space_provider_profile',

        verbose_name='Usuario'

    )



    provider_type = models.CharField(

        max_length=20,

        choices=ProviderType.choices,

        default=ProviderType.INDIVIDUAL,

        verbose_name='Tipo de proveedor'

    )



    public_name = models.CharField(

        max_length=180,

        blank=True,

        verbose_name='Nombre público o comercial'

    )



    business_legal_name = models.CharField(

        max_length=200,

        blank=True,

        verbose_name='Razón social'

    )



    business_rut = models.CharField(

        max_length=12,

        blank=True,

        validators=[validate_rut],

        verbose_name='RUT de la organización'

    )



    base_commune = models.ForeignKey(

        Commune,

        on_delete=models.PROTECT,

        related_name='space_provider_profiles',

        null=True,

        blank=True,

        verbose_name='Comuna base'

    )



    base_address = models.CharField(

        max_length=255,

        blank=True,

        verbose_name='Dirección base o comercial'

    )



    description = models.TextField(

        max_length=1800,

        blank=True,

        verbose_name='Descripción del proveedor'

    )



    managed_infrastructure_types = models.JSONField(

        default=list,

        blank=True,

        verbose_name='Tipos de infraestructura administrada'

    )



    provider_image = models.ImageField(

        upload_to='space_providers/',

        blank=True,

        null=True,

        validators=[

            FileExtensionValidator(

                allowed_extensions=[

                    'jpg',

                    'jpeg',

                    'png',

                    'webp',

                ]

            )

        ],

        verbose_name='Logo o imagen del proveedor'

    )



    website = models.URLField(

        max_length=255,

        blank=True,

        verbose_name='Sitio web'

    )



    information_declaration_accepted = models.BooleanField(

        default=False,

        verbose_name='Declaración de información aceptada'

    )



    information_declaration_accepted_at = models.DateTimeField(

        null=True,

        blank=True,

        verbose_name='Fecha de aceptación de declaración'

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



    created_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha de creación'

    )



    updated_at = models.DateTimeField(

        auto_now=True,

        verbose_name='Última actualización'

    )



    class Meta:

        verbose_name = 'Perfil de proveedor de espacios'

        verbose_name_plural = 'Perfiles de proveedores de espacios'

        ordering = [

            '-requested_at',

        ]



    def save(self, *args, **kwargs):



        if self.business_rut:

            self.business_rut = normalize_rut(

                self.business_rut

            )



        super().save(*args, **kwargs)



    @property

    def display_name(self):

        """

        Nombre visible del proveedor.

        """



        if self.public_name:

            return self.public_name



        full_name = self.user.get_full_name()



        if full_name:

            return full_name



        return self.user.email



    @property

    def application_complete(self):

        """

        Indica si la solicitud contiene la información

        mínima necesaria para ser revisada.

        """



        required_data = [

            self.provider_type,

            self.base_commune_id,

            self.base_address,

            self.description,

            bool(self.managed_infrastructure_types),

            self.information_declaration_accepted,

        ]



        if (

            self.provider_type

            == self.ProviderType.ORGANIZATION

        ):

            required_data.extend([

                self.public_name,

                self.business_legal_name,

                self.business_rut,

            ])



        return all(required_data)



    def get_managed_infrastructure_labels(self):

        """

        Devuelve los nombres legibles de los tipos

        de infraestructura seleccionados.

        """



        choices = dict(

            self.INFRASTRUCTURE_TYPE_CHOICES

        )



        return [

            choices.get(

                value,

                value

            )

            for value

            in self.managed_infrastructure_types

        ]



    def audit_snapshot(self):

        """

        Representación serializable del estado relevante

        del Perfil Proveedor para trazabilidad.

        """



        return {

            'provider_type': self.provider_type,

            'public_name': self.public_name,

            'business_legal_name': (

                self.business_legal_name

            ),

            'business_rut': self.business_rut,

            'base_commune_id': (

                self.base_commune_id

            ),

            'base_address': self.base_address,

            'description': self.description,

            'managed_infrastructure_types': (

                self.managed_infrastructure_types

            ),

            'provider_image': (

                self.provider_image.name

                if self.provider_image

                else ''

            ),

            'website': self.website,

            'information_declaration_accepted': (

                self.information_declaration_accepted

            ),

            'verification_status': (

                self.verification_status

            ),

            'rejection_reason': (

                self.rejection_reason

            ),

            'is_public': self.is_public,

        }



    def __str__(self):

        return self.display_name





class SpaceProviderProfileHistory(models.Model):

    """

    Historial de cambios del Perfil de Proveedor

    de Espacios.



    Conserva solicitudes, actualizaciones y decisiones

    administrativas sin eliminar la trazabilidad.

    """



    class Action(models.TextChoices):

        REQUESTED = (

            'requested',

            'Solicitud creada'

        )



        UPDATED = (

            'updated',

            'Solicitud actualizada'

        )



        RESUBMITTED = (

            'resubmitted',

            'Solicitud reenviada'

        )



        VERIFIED = (

            'verified',

            'Perfil verificado'

        )



        REJECTED = (

            'rejected',

            'Perfil rechazado'

        )



        SUSPENDED = (

            'suspended',

            'Perfil suspendido'

        )



        REACTIVATED = (

            'reactivated',

            'Perfil reactivado'

        )



    provider_profile = models.ForeignKey(

        SpaceProviderProfile,

        on_delete=models.PROTECT,

        related_name='history',

        verbose_name='Perfil proveedor'

    )



    action = models.CharField(

        max_length=20,

        choices=Action.choices,

        verbose_name='Acción'

    )



    previous_data = models.JSONField(

        default=dict,

        blank=True,

        verbose_name='Datos anteriores'

    )



    new_data = models.JSONField(

        default=dict,

        blank=True,

        verbose_name='Datos nuevos'

    )



    changed_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

        related_name='space_provider_profile_changes',

        verbose_name='Responsable'

    )



    reason = models.CharField(

        max_length=500,

        blank=True,

        verbose_name='Motivo o registro'

    )



    created_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha del cambio'

    )



    class Meta:

        verbose_name = 'Historial de perfil proveedor'

        verbose_name_plural = 'Historial de perfiles proveedores'

        ordering = [

            '-created_at',

            '-id',

        ]



    def __str__(self):

        return (

            f'{self.provider_profile} - '

            f'{self.get_action_display()}'

        )





class SpaceType(models.Model):

    """

    Catálogo de tipos de espacios publicables.



    Ejemplos futuros:

    sala de danza, gimnasio, cancha, estudio,

    sala multipropósito, academia, etc.

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

        verbose_name='Activo'

    )



    created_at = models.DateTimeField(

        auto_now_add=True

    )



    updated_at = models.DateTimeField(

        auto_now=True

    )



    class Meta:

        verbose_name = 'Tipo de espacio'

        verbose_name_plural = 'Tipos de espacios'

        ordering = [

            'display_order',

            'name',

        ]



    def __str__(self):

        return self.name





class SpaceEquipment(models.Model):

    """

    Catálogo de equipamiento disponible en los espacios.

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

        verbose_name='Activo'

    )



    recommended_space_types = models.ManyToManyField(

        SpaceType,

        blank=True,

        related_name='recommended_equipments',

        verbose_name='Recomendado para tipos de espacio'

    )



    created_at = models.DateTimeField(

        auto_now_add=True

    )



    updated_at = models.DateTimeField(

        auto_now=True

    )



    class Meta:

        verbose_name = 'Equipamiento de espacio'

        verbose_name_plural = 'Equipamientos de espacios'

        ordering = [

            'display_order',

            'name',

        ]



    def __str__(self):

        return self.name





class SpaceAmenity(models.Model):

    """

    Catálogo de comodidades y servicios de un espacio.

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

        verbose_name='Activo'

    )



    recommended_space_types = models.ManyToManyField(

        SpaceType,

        blank=True,

        related_name='recommended_amenities',

        verbose_name='Recomendado para tipos de espacio'

    )



    created_at = models.DateTimeField(

        auto_now_add=True

    )



    updated_at = models.DateTimeField(

        auto_now=True

    )



    class Meta:

        verbose_name = 'Comodidad de espacio'

        verbose_name_plural = 'Comodidades de espacios'

        ordering = [

            'display_order',

            'name',

        ]



    def __str__(self):

        return self.name





class Space(models.Model):

    """

    Recinto administrado por un Perfil Proveedor.



    El espacio conserva su propia ubicación, capacidad,

    superficie, precio, equipamiento, comodidades y

    estado de publicación.

    """



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




    class Environment(models.TextChoices):

        INTERIOR = (

            'interior',

            'Interior'

        )



        EXTERIOR = (

            'exterior',

            'Exterior'

        )



        MIXED = (

            'mixed',

            'Mixto'

        )



    provider_profile = models.ForeignKey(

        SpaceProviderProfile,

        on_delete=models.PROTECT,

        related_name='spaces',

        verbose_name='Proveedor'

    )



    space_type = models.ForeignKey(

        SpaceType,

        on_delete=models.PROTECT,

        related_name='spaces',

        verbose_name='Tipo de espacio'

    )



    name = models.CharField(

        max_length=180,

        verbose_name='Nombre del espacio'

    )



    description = models.TextField(

        max_length=2000,

        verbose_name='Descripción'

    )



    commune = models.ForeignKey(

        Commune,

        on_delete=models.PROTECT,

        related_name='spaces',

        verbose_name='Comuna'

    )



    address = models.CharField(

        max_length=255,

        verbose_name='Dirección'

    )



    location_reference = models.CharField(

        max_length=255,

        blank=True,

        verbose_name='Referencia de ubicación'

    )



    capacity = models.PositiveIntegerField(

        validators=[

            MinValueValidator(1)

        ],

        verbose_name='Capacidad de personas'

    )



    surface_m2 = models.DecimalField(

        max_digits=8,

        decimal_places=2,

        validators=[

            MinValueValidator(1)

        ],

        null=True,

        blank=True,

        verbose_name='Superficie aproximada en m²'

    )



    environment = models.CharField(

        max_length=20,

        choices=Environment.choices,

        blank=True,

        default='',

        verbose_name='Entorno'

    )



    surface_type = models.CharField(

        max_length=120,

        blank=True,

        verbose_name='Tipo de superficie'

    )



    allowed_uses = models.TextField(

        max_length=1000,

        blank=True,

        verbose_name='Usos o actividades permitidas'

    )



    hourly_price_clp = models.PositiveIntegerField(

        validators=[

            MinValueValidator(1)

        ],

        verbose_name='Precio por hora CLP'

    )



    equipments = models.ManyToManyField(

        SpaceEquipment,

        blank=True,

        related_name='spaces',

        verbose_name='Equipamiento'

    )



    amenities = models.ManyToManyField(

        SpaceAmenity,

        blank=True,

        related_name='spaces',

        verbose_name='Comodidades'

    )



    rules = models.TextField(

        max_length=2000,

        blank=True,

        verbose_name='Reglas de uso'

    )



    access_instructions = models.TextField(

        max_length=1200,

        blank=True,

        verbose_name='Indicaciones de acceso'

    )



    additional_features = models.TextField(

        max_length=1200,

        blank=True,

        verbose_name='Características adicionales'

    )



    publication_status = models.CharField(

        max_length=20,

        choices=PublicationStatus.choices,

        default=PublicationStatus.DRAFT,

        verbose_name='Estado de publicación'

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

        verbose_name = 'Espacio'

        verbose_name_plural = 'Espacios'

        ordering = [

            '-created_at',

        ]



        indexes = [

            models.Index(

                fields=[

                    'publication_status',

                    'commune',

                ],

                name='space_status_commune_idx',

            ),

            models.Index(

                fields=[

                    'provider_profile',

                    'publication_status',

                ],

                name='space_provider_status_idx',

            ),

        ]



    def clean(self):



        super().clean()



        if (

            self.publication_status

            == self.PublicationStatus.PUBLISHED

        ):



            if (

                self.provider_profile.verification_status

                != SpaceProviderProfile

                .VerificationStatus

                .VERIFIED

                or not self.provider_profile.is_public

            ):



                raise ValidationError(

                    (

                        'Solo un Proveedor de Espacios '

                        'verificado y activo puede publicar '

                        'recintos.'

                    )

                )



    def save(self, *args, **kwargs):



        if (

            self.publication_status

            == self.PublicationStatus.PUBLISHED

            and self.published_at is None

        ):

            self.published_at = timezone.now()



        super().save(*args, **kwargs)



    def audit_snapshot(self):



        data = {

            'provider_profile_id': (

                self.provider_profile_id

            ),

            'space_type_id': self.space_type_id,

            'name': self.name,

            'description': self.description,

            'commune_id': self.commune_id,

            'address': self.address,

            'location_reference': (

                self.location_reference

            ),

            'capacity': self.capacity,

            'surface_m2': (

                str(self.surface_m2)

                if self.surface_m2 is not None

                else None

            ),

            'environment': self.environment,

            'surface_type': self.surface_type,

            'allowed_uses': self.allowed_uses,

            'hourly_price_clp': (

                self.hourly_price_clp

            ),

            'rules': self.rules,

            'access_instructions': (

                self.access_instructions

            ),

            'additional_features': (

                self.additional_features

            ),

            'publication_status': (

                self.publication_status

            ),

            'published_at': (

                self.published_at.isoformat()

                if self.published_at

                else None

            ),

        }



        if self.pk:



            data['equipment_ids'] = list(

                self.equipments.values_list(

                    'id',

                    flat=True,

                )

            )



            data['amenity_ids'] = list(

                self.amenities.values_list(

                    'id',

                    flat=True,

                )

            )



        return data



    def generate_reservable_slots_for_date(

        self,

        target_date,

        slot_minutes=60,

    ):

        """

        Genera bloques consecutivos para una fecha.



        Una excepción activa tiene prioridad sobre la

        disponibilidad semanal recurrente:

        - blocked: no genera bloques.

        - special_hours: utiliza solo el horario especial.

        """



        today = timezone.localdate()



        if target_date < today:

            return []



        exception = (

            self.availability_exceptions

            .filter(

                date=target_date,

                is_active=True,

            )

            .order_by(

                '-created_at',

                '-id',

            )

            .first()

        )



        if (

            exception

            and exception.exception_type

            == SpaceAvailabilityException

            .ExceptionType

            .BLOCKED

        ):

            return []



        if (

            exception

            and exception.exception_type

            == SpaceAvailabilityException

            .ExceptionType

            .SPECIAL_HOURS

        ):

            window_ranges = [

                (

                    exception.start_time,

                    exception.end_time,

                )

            ]



        else:



            weekday = target_date.weekday()



            windows = (

                self.availability_windows

                .filter(

                    weekday=weekday,

                    is_active=True,

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



            window_ranges = [

                (

                    window.start_time,

                    window.end_time,

                )

                for window in windows

            ]



        blocking_bookings = list(

            self.bookings

            .filter(

                session_date=target_date,

                status__in=[

                    'pending',

                    'confirmed',

                ],

            )

            .values(

                'start_time',

                'end_time',

            )

        )



        slots = []



        current_timezone = (

            timezone.get_current_timezone()

        )



        now = timezone.localtime()



        for start_time, end_time in window_ranges:



            start_dt = datetime.combine(

                target_date,

                start_time,

            )



            end_dt = datetime.combine(

                target_date,

                end_time,

            )



            current_start = start_dt



            while (

                current_start

                + timedelta(

                    minutes=slot_minutes

                )

                <= end_dt

            ):

                current_end = (

                    current_start

                    + timedelta(

                        minutes=slot_minutes

                    )

                )



                aware_start = timezone.make_aware(

                    current_start,

                    current_timezone,

                )



                if aware_start <= now:

                    current_start = current_end

                    continue



                candidate_start = (

                    current_start.time()

                )



                candidate_end = (

                    current_end.time()

                )



                overlaps_booking = any(

                    booking['start_time']

                    < candidate_end

                    and booking['end_time']

                    > candidate_start

                    for booking in blocking_bookings

                )



                if not overlaps_booking:

                    slots.append(

                        {

                            'start_time': (

                                candidate_start

                            ),

                            'end_time': (

                                candidate_end

                            ),

                            'duration_minutes': (

                                slot_minutes

                            ),

                        }

                    )



                current_start = current_end



        return slots



    def __str__(self):

        return self.name





class SpaceImage(models.Model):

    """

    Fotografías asociadas a un espacio.



    Una imagen puede marcarse como portada y las demás

    se conservan como galería del recinto.

    """



    space = models.ForeignKey(

        Space,

        on_delete=models.PROTECT,

        related_name='images',

        verbose_name='Espacio'

    )



    image = models.ImageField(

        upload_to='spaces/',

        validators=[

            FileExtensionValidator(

                allowed_extensions=[

                    'jpg',

                    'jpeg',

                    'png',

                    'webp',

                ]

            )

        ],

        verbose_name='Imagen'

    )



    caption = models.CharField(

        max_length=180,

        blank=True,

        verbose_name='Descripción de imagen'

    )



    is_cover = models.BooleanField(

        default=False,

        verbose_name='Imagen de portada'

    )



    display_order = models.PositiveIntegerField(

        default=0,

        verbose_name='Orden'

    )



    created_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha de carga'

    )



    class Meta:

        verbose_name = 'Imagen de espacio'

        verbose_name_plural = 'Imágenes de espacios'

        ordering = [

            'display_order',

            'id',

        ]



    def __str__(self):

        return (

            f'Imagen de {self.space.name}'

        )





class SpaceHistory(models.Model):

    """

    Historial de cambios relevantes de cada espacio.

    """



    class Action(models.TextChoices):

        CREATED = (

            'created',

            'Espacio creado'

        )



        UPDATED = (

            'updated',

            'Espacio actualizado'

        )



        PUBLISHED = (

            'published',

            'Espacio publicado'

        )



        PAUSED = (

            'paused',

            'Espacio pausado'

        )



        REACTIVATED = (

            'reactivated',

            'Espacio reactivado'

        )



    space = models.ForeignKey(

        Space,

        on_delete=models.PROTECT,

        related_name='history',

        verbose_name='Espacio'

    )



    action = models.CharField(

        max_length=20,

        choices=Action.choices,

        verbose_name='Acción'

    )



    previous_data = models.JSONField(

        default=dict,

        blank=True,

        verbose_name='Datos anteriores'

    )



    new_data = models.JSONField(

        default=dict,

        blank=True,

        verbose_name='Datos nuevos'

    )



    changed_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

        related_name='space_changes',

        verbose_name='Responsable'

    )



    reason = models.CharField(

        max_length=500,

        blank=True,

        verbose_name='Motivo o registro'

    )



    created_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha del cambio'

    )



    class Meta:

        verbose_name = 'Historial de espacio'

        verbose_name_plural = 'Historial de espacios'

        ordering = [

            '-created_at',

            '-id',

        ]



    def __str__(self):

        return (

            f'{self.space.name} - '

            f'{self.get_action_display()}'

        )





class SpaceAvailability(models.Model):

    """

    Ventana semanal recurrente en la que un espacio

    puede ofrecer arriendo por hora.



    Las reservas se implementarán posteriormente

    utilizando estas ventanas como base.

    """



    class Weekday(models.IntegerChoices):

        MONDAY = 0, 'Lunes'

        TUESDAY = 1, 'Martes'

        WEDNESDAY = 2, 'Miércoles'

        THURSDAY = 3, 'Jueves'

        FRIDAY = 4, 'Viernes'

        SATURDAY = 5, 'Sábado'

        SUNDAY = 6, 'Domingo'



    space = models.ForeignKey(

        Space,

        on_delete=models.PROTECT,

        related_name='availability_windows',

        verbose_name='Espacio'

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

        default=timezone.localdate,

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

        verbose_name = 'Disponibilidad de espacio'

        verbose_name_plural = 'Disponibilidades de espacios'

        ordering = [

            'weekday',

            'start_time',

            'valid_from',

        ]



        indexes = [

            models.Index(

                fields=[

                    'space',

                    'weekday',

                    'is_active',

                ],

                name='space_avail_lookup_idx',

            ),

        ]



        constraints = [

            models.CheckConstraint(

                condition=models.Q(

                    start_time__lt=models.F(

                        'end_time'

                    )

                ),

                name='space_avail_time_order',

            ),

        ]



    def clean(self):



        super().clean()



        # La primera fecha disponible es la fuente de verdad.
        # Python usa lunes=0 ... domingo=6, igual que Weekday.
        if self.valid_from:
            self.weekday = self.valid_from.weekday()




        if (

            self.start_time

            and self.end_time

            and self.start_time >= self.end_time

        ):

            raise ValidationError(

                'La hora de término debe ser posterior a la hora de inicio.'

            )



        if (

            self.valid_from

            and self.valid_until

            and self.valid_until < self.valid_from

        ):

            raise ValidationError(

                'La fecha final no puede ser anterior a la fecha inicial.'

            )



        if (

            self.start_time

            and self.end_time

        ):

            start_dt = datetime.combine(

                timezone.localdate(),

                self.start_time,

            )



            end_dt = datetime.combine(

                timezone.localdate(),

                self.end_time,

            )



            if (

                end_dt - start_dt

                < timedelta(hours=1)

            ):

                raise ValidationError(

                    (

                        'La ventana de disponibilidad debe '

                        'tener una duración mínima de 60 minutos.'

                    )

                )



        if (

            self.space_id

            and self.is_active

            and self.start_time

            and self.end_time

            and self.valid_from

        ):



            overlaps = (

                SpaceAvailability.objects

                .filter(

                    space_id=self.space_id,

                    weekday=self.weekday,

                    is_active=True,

                    start_time__lt=self.end_time,

                    end_time__gt=self.start_time,

                )

                .exclude(

                    pk=self.pk

                )

                .filter(

                    models.Q(

                        valid_until__isnull=True

                    )

                    | models.Q(

                        valid_until__gte=self.valid_from

                    )

                )

            )



            if self.valid_until:

                overlaps = overlaps.filter(

                    valid_from__lte=self.valid_until

                )



            if overlaps.exists():

                raise ValidationError(

                    (

                        'Esta disponibilidad se superpone con '

                        'otra ventana activa del mismo día.'

                    )

                )



    def audit_snapshot(self):



        return {

            'space_id': self.space_id,

            'weekday': self.weekday,

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

            f'{self.space.name} · '

            f'{self.get_weekday_display()} '

            f'{self.start_time:%H:%M}–'

            f'{self.end_time:%H:%M}'

        )





class SpaceAvailabilityException(models.Model):

    """

    Excepción para una fecha concreta del calendario.



    Puede bloquear por completo una fecha o reemplazar

    el horario semanal por un horario especial.

    """



    class ExceptionType(models.TextChoices):

        BLOCKED = (

            'blocked',

            'No disponible'

        )



        SPECIAL_HOURS = (

            'special_hours',

            'Horario especial'

        )



    space = models.ForeignKey(

        Space,

        on_delete=models.PROTECT,

        related_name='availability_exceptions',

        verbose_name='Espacio'

    )



    date = models.DateField(

        verbose_name='Fecha'

    )



    exception_type = models.CharField(

        max_length=20,

        choices=ExceptionType.choices,

        verbose_name='Tipo de excepción'

    )



    start_time = models.TimeField(

        null=True,

        blank=True,

        verbose_name='Hora especial de inicio'

    )



    end_time = models.TimeField(

        null=True,

        blank=True,

        verbose_name='Hora especial de término'

    )



    reason = models.CharField(

        max_length=300,

        blank=True,

        verbose_name='Motivo'

    )



    is_active = models.BooleanField(

        default=True,

        verbose_name='Excepción activa'

    )



    created_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

        related_name='space_availability_exceptions_created',

        verbose_name='Creada por'

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

        verbose_name = 'Excepción de disponibilidad'

        verbose_name_plural = 'Excepciones de disponibilidad'

        ordering = [

            'date',

            'id',

        ]



        indexes = [

            models.Index(

                fields=[

                    'space',

                    'date',

                    'is_active',

                ],

                name='space_exc_lookup_idx',

            ),

        ]



        constraints = [

            models.UniqueConstraint(

                fields=[

                    'space',

                    'date',

                ],

                condition=models.Q(

                    is_active=True

                ),

                name='space_exc_one_active_date',

            ),

        ]



    def clean(self):



        super().clean()



        if (

            self.exception_type

            == self.ExceptionType.BLOCKED

        ):

            self.start_time = None

            self.end_time = None



        if (

            self.exception_type

            == self.ExceptionType.SPECIAL_HOURS

        ):

            if not self.start_time or not self.end_time:

                raise ValidationError(

                    (

                        'Debes indicar hora de inicio y término '

                        'para un horario especial.'

                    )

                )



            if self.start_time >= self.end_time:

                raise ValidationError(

                    'La hora de término debe ser posterior a la hora de inicio.'

                )



            start_dt = datetime.combine(

                self.date,

                self.start_time,

            )



            end_dt = datetime.combine(

                self.date,

                self.end_time,

            )



            if (

                end_dt - start_dt

                < timedelta(hours=1)

            ):

                raise ValidationError(

                    'El horario especial debe durar al menos 60 minutos.'

                )



        if (

            self.space_id

            and self.date

            and self.is_active

        ):

            duplicated = (

                SpaceAvailabilityException.objects

                .filter(

                    space_id=self.space_id,

                    date=self.date,

                    is_active=True,

                )

                .exclude(

                    pk=self.pk

                )

            )



            if duplicated.exists():

                raise ValidationError(

                    'Ya existe una excepción activa para esta fecha.'

                )



            blocking_bookings = (

                self.space.bookings

                .filter(

                    session_date=self.date,

                    status__in=[

                        'pending',

                        'confirmed',

                    ],

                )

            )



            if (

                self.exception_type

                == self.ExceptionType.BLOCKED

                and blocking_bookings.exists()

            ):

                raise ValidationError(

                    (

                        'No puedes bloquear esta fecha porque '

                        'tiene reservas pendientes o confirmadas.'

                    )

                )



            if (

                self.exception_type

                == self.ExceptionType.SPECIAL_HOURS

                and self.start_time

                and self.end_time

            ):

                incompatible_booking = (

                    blocking_bookings

                    .exclude(

                        start_time__gte=self.start_time,

                        end_time__lte=self.end_time,

                    )

                )



                if incompatible_booking.exists():

                    raise ValidationError(

                        (

                            'Existe una reserva fuera del nuevo horario especial. '

                            'Gestiona primero esa reserva.'

                        )

                    )



    def audit_snapshot(self):



        return {

            'space_id': self.space_id,

            'date': (

                self.date.isoformat()

                if self.date

                else None

            ),

            'exception_type': self.exception_type,

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

            'reason': self.reason,

            'is_active': self.is_active,

        }



    def __str__(self):



        if (

            self.exception_type

            == self.ExceptionType.SPECIAL_HOURS

            and self.start_time

            and self.end_time

        ):

            detail = (

                f'{self.start_time:%H:%M}–'

                f'{self.end_time:%H:%M}'

            )



        else:

            detail = self.get_exception_type_display()



        return (

            f'{self.space.name} · '

            f'{self.date:%d/%m/%Y} · '

            f'{detail}'

        )





class SpaceAvailabilityExceptionHistory(models.Model):

    """

    Trazabilidad de excepciones de disponibilidad.

    """



    class Action(models.TextChoices):

        CREATED = (

            'created',

            'Excepción creada'

        )



        ACTIVATED = (

            'activated',

            'Excepción reactivada'

        )



        DEACTIVATED = (

            'deactivated',

            'Excepción desactivada'

        )



    exception = models.ForeignKey(

        SpaceAvailabilityException,

        on_delete=models.PROTECT,

        related_name='history',

        verbose_name='Excepción'

    )



    action = models.CharField(

        max_length=20,

        choices=Action.choices,

        verbose_name='Acción'

    )



    previous_data = models.JSONField(

        default=dict,

        blank=True,

        verbose_name='Datos anteriores'

    )



    new_data = models.JSONField(

        default=dict,

        blank=True,

        verbose_name='Datos nuevos'

    )



    changed_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

        related_name='space_availability_exception_changes',

        verbose_name='Responsable'

    )



    reason = models.CharField(

        max_length=500,

        blank=True,

        verbose_name='Motivo o registro'

    )



    created_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha del cambio'

    )



    class Meta:

        verbose_name = 'Historial de excepción de disponibilidad'

        verbose_name_plural = 'Historial de excepciones de disponibilidad'

        ordering = [

            '-created_at',

            '-id',

        ]



    def __str__(self):

        return (

            f'{self.exception} · '

            f'{self.get_action_display()}'

        )





class SpaceAvailabilityHistory(models.Model):

    """

    Trazabilidad de los cambios de disponibilidad

    de cada espacio.

    """



    class Action(models.TextChoices):

        CREATED = (

            'created',

            'Disponibilidad creada'

        )



        UPDATED = (

            'updated',

            'Disponibilidad actualizada'

        )



        ACTIVATED = (

            'activated',

            'Disponibilidad activada'

        )



        DEACTIVATED = (

            'deactivated',

            'Disponibilidad desactivada'

        )



    availability = models.ForeignKey(

        SpaceAvailability,

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

        verbose_name='Datos anteriores'

    )



    new_data = models.JSONField(

        default=dict,

        blank=True,

        verbose_name='Datos nuevos'

    )



    changed_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

        related_name='space_availability_changes',

        verbose_name='Responsable'

    )



    reason = models.CharField(

        max_length=500,

        blank=True,

        verbose_name='Motivo o registro'

    )



    created_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha del cambio'

    )



    class Meta:

        verbose_name = 'Historial de disponibilidad de espacio'

        verbose_name_plural = 'Historial de disponibilidades de espacios'

        ordering = [

            '-created_at',

            '-id',

        ]



    def __str__(self):

        return (

            f'{self.availability} · '

            f'{self.get_action_display()}'

        )





class SpaceBooking(models.Model):

    """

    Reserva de un bloque de 60 minutos de un espacio.



    Conserva snapshots para que cambios posteriores

    del recinto no alteren la reserva registrada.

    """



    class Status(models.TextChoices):

        PENDING = (

            'pending',

            'Pendiente'

        )



        CONFIRMED = (

            'confirmed',

            'Confirmada'

        )



        CANCELLED = (

            'cancelled',

            'Cancelada'

        )



        COMPLETED = (

            'completed',

            'Completada'

        )



    booked_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.PROTECT,

        related_name='space_bookings',

        verbose_name='Reservado por'

    )



    space = models.ForeignKey(

        Space,

        on_delete=models.PROTECT,

        related_name='bookings',

        verbose_name='Espacio'

    )



    provider_profile = models.ForeignKey(

        SpaceProviderProfile,

        on_delete=models.PROTECT,

        related_name='space_bookings',

        verbose_name='Proveedor'

    )



    session_date = models.DateField(

        verbose_name='Fecha reservada'

    )



    start_time = models.TimeField(

        verbose_name='Hora de inicio'

    )



    end_time = models.TimeField(

        verbose_name='Hora de término'

    )



    duration_minutes = models.PositiveIntegerField(

        default=60,

        validators=[

            MinValueValidator(60)

        ],

        verbose_name='Duración en minutos'

    )



    price_clp = models.PositiveIntegerField(

        validators=[

            MinValueValidator(1)

        ],

        verbose_name='Precio registrado CLP'

    )



    space_name_snapshot = models.CharField(

        max_length=180,

        verbose_name='Nombre del espacio registrado'

    )



    space_type_snapshot = models.CharField(

        max_length=120,

        verbose_name='Tipo de espacio registrado'

    )



    provider_name_snapshot = models.CharField(

        max_length=180,

        verbose_name='Proveedor registrado'

    )



    address_snapshot = models.CharField(

        max_length=255,

        verbose_name='Dirección registrada'

    )



    commune_snapshot = models.CharField(

        max_length=180,

        verbose_name='Comuna registrada'

    )



    status = models.CharField(

        max_length=20,

        choices=Status.choices,

        default=Status.PENDING,

        verbose_name='Estado'

    )



    cancellation_reason = models.TextField(

        blank=True,

        verbose_name='Motivo de cancelación'

    )



    confirmed_at = models.DateTimeField(

        null=True,

        blank=True,

        verbose_name='Fecha de confirmación'

    )



    cancelled_at = models.DateTimeField(

        null=True,

        blank=True,

        verbose_name='Fecha de cancelación'

    )



    completed_at = models.DateTimeField(

        null=True,

        blank=True,

        verbose_name='Fecha de finalización'

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

        verbose_name = 'Reserva de espacio'

        verbose_name_plural = 'Reservas de espacios'

        ordering = [

            '-created_at',

        ]



        indexes = [

            models.Index(

                fields=[

                    'space',

                    'session_date',

                    'status',

                ],

                name='space_booking_lookup_idx',

            ),

            models.Index(

                fields=[

                    'booked_by',

                    'session_date',

                ],

                name='space_booking_user_idx',

            ),

        ]



        constraints = [

            models.CheckConstraint(

                condition=models.Q(

                    start_time__lt=models.F(

                        'end_time'

                    )

                ),

                name='space_booking_time_order',

            ),

            models.UniqueConstraint(

                fields=[

                    'space',

                    'session_date',

                    'start_time',

                ],

                condition=models.Q(

                    status__in=[

                        'pending',

                        'confirmed',

                    ]

                ),

                name='space_booking_unique_blocking_start',

            ),

        ]



    def clean(self):



        super().clean()



        if (

            self.space_id

            and self.provider_profile_id

            and self.space.provider_profile_id

            != self.provider_profile_id

        ):

            raise ValidationError(

                'El proveedor no corresponde al espacio reservado.'

            )



        if (

            self.booked_by_id

            and self.space_id

            and self.space.provider_profile.user_id

            == self.booked_by_id

        ):

            raise ValidationError(

                'No puedes reservar un espacio administrado por tu propia cuenta.'

            )



        if (

            self.start_time

            and self.end_time

        ):

            start_dt = datetime.combine(

                self.session_date

                or timezone.localdate(),

                self.start_time,

            )



            end_dt = datetime.combine(

                self.session_date

                or timezone.localdate(),

                self.end_time,

            )



            if end_dt <= start_dt:

                raise ValidationError(

                    'La hora de término debe ser posterior a la hora de inicio.'

                )



            duration = int(

                (

                    end_dt - start_dt

                ).total_seconds()

                // 60

            )



            if duration != 60:

                raise ValidationError(

                    'Las reservas de espacios deben corresponder a bloques de 60 minutos.'

                )



            if (

                self.duration_minutes

                and self.duration_minutes != 60

            ):

                raise ValidationError(

                    'La duración registrada debe ser de 60 minutos.'

                )



        if (

            self._state.adding

            and self.space_id

            and self.session_date

            and self.start_time

            and self.end_time

        ):

            if (

                self.space.publication_status

                != Space.PublicationStatus.PUBLISHED

            ):

                raise ValidationError(

                    'Solo se pueden reservar espacios publicados.'

                )



            current_timezone = (

                timezone.get_current_timezone()

            )



            session_start = timezone.make_aware(

                datetime.combine(

                    self.session_date,

                    self.start_time,

                ),

                current_timezone,

            )



            if session_start <= timezone.localtime():

                raise ValidationError(

                    'La reserva debe corresponder a un horario futuro.'

                )



            available_slots = (

                self.space

                .generate_reservable_slots_for_date(

                    self.session_date

                )

            )



            slot_exists = any(

                slot['start_time']

                == self.start_time

                and slot['end_time']

                == self.end_time

                for slot in available_slots

            )



            if not slot_exists:

                raise ValidationError(

                    'El bloque seleccionado ya no se encuentra disponible.'

                )



            overlapping = (

                SpaceBooking.objects

                .filter(

                    space=self.space,

                    session_date=self.session_date,

                    status__in=[

                        self.Status.PENDING,

                        self.Status.CONFIRMED,

                    ],

                    start_time__lt=self.end_time,

                    end_time__gt=self.start_time,

                )

                .exists()

            )



            if overlapping:

                raise ValidationError(

                    'El horario ya se encuentra ocupado por otra reserva.'

                )



    def apply_snapshot(self):



        self.provider_profile = (

            self.space.provider_profile

        )



        self.duration_minutes = 60



        self.price_clp = (

            self.space.hourly_price_clp

        )



        self.space_name_snapshot = (

            self.space.name

        )



        self.space_type_snapshot = (

            self.space.space_type.name

        )



        self.provider_name_snapshot = (

            self.space.provider_profile

            .display_name

        )



        self.address_snapshot = (

            self.space.address

        )



        self.commune_snapshot = (

            self.space.commune.name

        )



    def audit_snapshot(self):



        return {

            'booking_id': self.pk,

            'booked_by_id': self.booked_by_id,

            'space_id': self.space_id,

            'provider_profile_id': (

                self.provider_profile_id

            ),

            'session_date': (

                self.session_date.isoformat()

                if self.session_date

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

            'duration_minutes': (

                self.duration_minutes

            ),

            'price_clp': self.price_clp,

            'space_name_snapshot': (

                self.space_name_snapshot

            ),

            'space_type_snapshot': (

                self.space_type_snapshot

            ),

            'provider_name_snapshot': (

                self.provider_name_snapshot

            ),

            'address_snapshot': (

                self.address_snapshot

            ),

            'commune_snapshot': (

                self.commune_snapshot

            ),

            'status': self.status,

            'cancellation_reason': (

                self.cancellation_reason

            ),

            'confirmed_at': (

                self.confirmed_at.isoformat()

                if self.confirmed_at

                else None

            ),

            'cancelled_at': (

                self.cancelled_at.isoformat()

                if self.cancelled_at

                else None

            ),

            'completed_at': (

                self.completed_at.isoformat()

                if self.completed_at

                else None

            ),

        }



    def save(self, *args, **kwargs):



        if self._state.adding:

            self.apply_snapshot()

            self.full_clean()



        super().save(*args, **kwargs)



    def __str__(self):

        return (

            f'#{self.pk or "nueva"} · '

            f'{self.space_name_snapshot or self.space.name} · '

            f'{self.session_date} '

            f'{self.start_time:%H:%M}'

        )





class SpaceBookingHistory(models.Model):

    """

    Historial de estados y cambios de cada reserva de espacio.

    """



    class Action(models.TextChoices):

        CREATED = (

            'created',

            'Reserva creada'

        )



        CONFIRMED = (

            'confirmed',

            'Reserva confirmada'

        )



        CANCELLED = (

            'cancelled',

            'Reserva cancelada'

        )



        COMPLETED = (

            'completed',

            'Reserva completada'

        )



        UPDATED = (

            'updated',

            'Reserva actualizada'

        )



    booking = models.ForeignKey(

        SpaceBooking,

        on_delete=models.PROTECT,

        related_name='history',

        verbose_name='Reserva'

    )



    action = models.CharField(

        max_length=20,

        choices=Action.choices,

        verbose_name='Acción'

    )



    previous_data = models.JSONField(

        default=dict,

        blank=True,

        verbose_name='Datos anteriores'

    )



    new_data = models.JSONField(

        default=dict,

        blank=True,

        verbose_name='Datos nuevos'

    )



    changed_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

        related_name='space_booking_changes',

        verbose_name='Responsable'

    )



    reason = models.CharField(

        max_length=500,

        blank=True,

        verbose_name='Motivo o registro'

    )



    created_at = models.DateTimeField(

        auto_now_add=True,

        verbose_name='Fecha del cambio'

    )



    class Meta:

        verbose_name = 'Historial de reserva de espacio'

        verbose_name_plural = 'Historial de reservas de espacios'

        ordering = [

            '-created_at',

            '-id',

        ]



    def __str__(self):

        return (

            f'Reserva #{self.booking_id} · '

            f'{self.get_action_display()}'

        )


