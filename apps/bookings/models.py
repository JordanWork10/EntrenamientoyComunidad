from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.utils import timezone

from apps.professionals.models import (
    ProfessionalProfile,
    ProfessionalService,
)


class Booking(models.Model):
    """
    Reserva concreta realizada sobre una sesión de un servicio
    profesional.

    La disponibilidad recurrente NO se copia como múltiples registros.
    Solo se crea una Booking cuando un usuario reserva una sesión real.

    La reserva conserva una fotografía de los datos comerciales y
    operacionales relevantes para mantener trazabilidad histórica,
    aunque el servicio sea modificado posteriormente.
    """

    class Status(models.TextChoices):
        PENDING = (
            'pending',
            'Pendiente',
        )

        CONFIRMED = (
            'confirmed',
            'Confirmada',
        )

        CANCELLED = (
            'cancelled',
            'Cancelada',
        )

        COMPLETED = (
            'completed',
            'Completada',
        )

        EXPIRED = (
            'expired',
            'Vencida',
        )

    # =====================================================
    # RELACIONES
    # =====================================================

    booked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='bookings',
        verbose_name='Usuario que reserva',
    )

    service = models.ForeignKey(
        ProfessionalService,
        on_delete=models.PROTECT,
        related_name='bookings',
        verbose_name='Servicio profesional',
    )

    professional_profile = models.ForeignKey(
        ProfessionalProfile,
        on_delete=models.PROTECT,
        related_name='bookings',
        verbose_name='Perfil profesional',
    )

    # =====================================================
    # SESIÓN CONCRETA
    # =====================================================

    session_date = models.DateField(
        verbose_name='Fecha de la sesión',
    )

    start_time = models.TimeField(
        verbose_name='Hora de inicio',
    )

    end_time = models.TimeField(
        verbose_name='Hora de término',
    )

    duration_minutes = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(15),
            MaxValueValidator(480),
        ],
        verbose_name='Duración registrada (minutos)',
    )

    # =====================================================
    # FOTOGRAFÍA DEL SERVICIO AL RESERVAR
    # =====================================================

    price_clp = models.PositiveIntegerField(
        verbose_name='Precio registrado (CLP)',
    )

    service_name_snapshot = models.CharField(
        max_length=180,
        verbose_name='Nombre del servicio al reservar',
    )

    mode_snapshot = models.CharField(
        max_length=20,
        choices=ProfessionalService.ServiceMode.choices,
        verbose_name='Modalidad al reservar',
    )

    location_type_snapshot = models.CharField(
        max_length=30,
        blank=True,
        choices=ProfessionalService.InPersonLocationType.choices,
        verbose_name='Tipo de lugar al reservar',
    )

    location_name_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name='Nombre del lugar al reservar',
    )

    location_address_snapshot = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Dirección registrada al reservar',
    )

    location_commune_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name='Comuna registrada al reservar',
    )

    # =====================================================
    # ESTADO
    # =====================================================

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Estado',
    )

    cancellation_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Motivo de cancelación',
    )

    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de confirmación',
    )

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de cancelación',
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de finalización',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización',
    )

    class Meta:
        verbose_name = 'Reserva'
        verbose_name_plural = 'Reservas'

        ordering = [
            '-session_date',
            '-start_time',
        ]

        indexes = [
            models.Index(
                fields=[
                    'professional_profile',
                    'session_date',
                    'status',
                ],
                name='booking_prof_date_status_idx',
            ),
            models.Index(
                fields=[
                    'booked_by',
                    'session_date',
                ],
                name='booking_user_date_idx',
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    end_time__gt=models.F('start_time')
                ),
                name='booking_end_after_start',
            ),
        ]

    # =====================================================
    # VALIDACIONES
    # =====================================================

    def clean(self):
        """
        Valida coherencia, pertenencia y conflictos horarios.

        La comprobación de disponibilidad original se realiza al crear
        la reserva. Después, la reserva queda históricamente estable
        aunque el Profesional cambie su disponibilidad futura.
        """

        super().clean()

        if not self.service_id:
            return

        # -------------------------------------------------
        # PROFESIONAL DEL SERVICIO
        # -------------------------------------------------

        if (
            self.professional_profile_id
            and self.professional_profile_id
            != self.service.professional_profile_id
        ):
            raise ValidationError(
                {
                    'professional_profile': (
                        'El Profesional de la reserva no coincide '
                        'con el propietario del servicio.'
                    )
                }
            )

        # -------------------------------------------------
        # COHERENCIA HORARIA
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

        if (
            self.session_date
            and self.start_time
            and self.end_time
            and self.duration_minutes
        ):

            start_datetime = datetime.combine(
                self.session_date,
                self.start_time,
            )

            end_datetime = datetime.combine(
                self.session_date,
                self.end_time,
            )

            calculated_minutes = int(
                (
                    end_datetime
                    - start_datetime
                ).total_seconds()
                // 60
            )

            if (
                calculated_minutes
                != self.duration_minutes
            ):
                raise ValidationError(
                    {
                        'duration_minutes': (
                            'La duración registrada debe coincidir '
                            'exactamente con el bloque horario reservado.'
                        )
                    }
                )

        # -------------------------------------------------
        # REGLAS SOLO AL CREAR
        # -------------------------------------------------

        if self._state.adding:

            if (
                self.service.publication_status
                != ProfessionalService
                .PublicationStatus
                .PUBLISHED
            ):
                raise ValidationError(
                    {
                        'service': (
                            'Solo se pueden reservar servicios '
                            'publicados.'
                        )
                    }
                )

            if (
                self.session_date
                and self.start_time
            ):

                local_timezone = (
                    timezone.get_current_timezone()
                )

                session_start = (
                    timezone.make_aware(
                        datetime.combine(
                            self.session_date,
                            self.start_time,
                        ),
                        local_timezone,
                    )
                )

                if (
                    session_start
                    <= timezone.now()
                ):
                    raise ValidationError(
                        {
                            'session_date': (
                                'La sesión debe comenzar en una '
                                'fecha y hora futuras.'
                            )
                        }
                    )

            # La sesión concreta debe existir dentro de los
            # bloques que el servicio puede generar para esa fecha.
            if (
                self.session_date
                and self.start_time
                and self.end_time
            ):

                generated_slots = (
                    self.service
                    .generate_reservable_slots_for_date(
                        self.session_date
                    )
                )

                slot_exists = any(
                    (
                        slot['start_time']
                        == self.start_time
                    )
                    and (
                        slot['end_time']
                        == self.end_time
                    )
                    for slot in generated_slots
                )

                if not slot_exists:
                    raise ValidationError(
                        {
                            'start_time': (
                                'El bloque seleccionado no corresponde '
                                'a una sesión reservable vigente.'
                            )
                        }
                    )

        # -------------------------------------------------
        # EVITAR DOBLE RESERVA DEL PROFESIONAL
        # -------------------------------------------------

        blocking_statuses = [
            self.Status.PENDING,
            self.Status.CONFIRMED,
        ]

        if (
            self.professional_profile_id
            and self.session_date
            and self.start_time
            and self.end_time
            and self.status in blocking_statuses
        ):

            overlapping_booking = (
                Booking.objects
                .filter(
                    professional_profile_id=(
                        self.professional_profile_id
                    ),
                    session_date=self.session_date,
                    status__in=blocking_statuses,
                    start_time__lt=self.end_time,
                    end_time__gt=self.start_time,
                )
                .exclude(
                    pk=self.pk
                )
                .exists()
            )

            if overlapping_booking:
                raise ValidationError(
                    {
                        'start_time': (
                            'El Profesional ya posee una reserva '
                            'que se superpone con este horario.'
                        )
                    }
                )

    # =====================================================
    # SNAPSHOT / TRAZABILIDAD
    # =====================================================

    def apply_service_snapshot(self):
        """
        Copia a la reserva los datos relevantes del servicio
        existentes en el momento de reservar.
        """

        service = self.service

        self.professional_profile = (
            service.professional_profile
        )

        self.duration_minutes = (
            service.duration_minutes
        )

        self.price_clp = (
            service.price
        )

        self.service_name_snapshot = (
            service.name
        )

        self.mode_snapshot = (
            service.mode
        )

        self.location_type_snapshot = (
            service.in_person_location_type
            or ''
        )

        self.location_name_snapshot = (
            service.location_name
            or ''
        )

        self.location_address_snapshot = (
            service.location_address
            or ''
        )

        if service.location_commune:

            self.location_commune_snapshot = (
                f'{service.location_commune.name} - '
                f'{service.location_commune.region.name}'
            )

        else:

            self.location_commune_snapshot = ''

    def audit_snapshot(self):
        """
        Fotografía serializable del estado actual de la reserva.
        """

        return {
            'status': self.status,
            'status_display': (
                self.get_status_display()
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
            'price_clp': (
                self.price_clp
            ),
            'service_name': (
                self.service_name_snapshot
            ),
            'mode': (
                self.mode_snapshot
            ),
            'cancellation_reason': (
                self.cancellation_reason
            ),
        }

    def save(
        self,
        *args,
        **kwargs
    ):
        """
        Al crear, congela los datos comerciales del servicio.
        Después ejecuta todas las validaciones antes de guardar.
        """

        if self._state.adding:
            self.apply_service_snapshot()

        self.full_clean()

        return super().save(
            *args,
            **kwargs
        )

    def __str__(self):
        return (
            f'{self.service_name_snapshot} - '
            f'{self.session_date:%d/%m/%Y} '
            f'{self.start_time:%H:%M}'
        )


class BookingHistory(models.Model):
    """
    Historial de acciones realizadas sobre una reserva.

    Permite conservar la secuencia de estados sin eliminar
    información operacional.
    """

    class Action(models.TextChoices):
        CREATED = (
            'created',
            'Creada',
        )

        CONFIRMED = (
            'confirmed',
            'Confirmada',
        )

        CANCELLED = (
            'cancelled',
            'Cancelada',
        )

        COMPLETED = (
            'completed',
            'Completada',
        )

        EXPIRED = (
            'expired',
            'Vencida',
        )

        UPDATED = (
            'updated',
            'Actualizada',
        )

    booking = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        related_name='history',
        verbose_name='Reserva',
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        verbose_name='Acción',
    )

    previous_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Estado anterior',
    )

    new_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Estado nuevo',
    )

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='booking_changes',
        verbose_name='Modificado por',
    )

    reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Motivo',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha del cambio',
    )

    class Meta:
        verbose_name = 'Historial de reserva'
        verbose_name_plural = 'Historiales de reservas'

        ordering = [
            '-created_at',
        ]

    def __str__(self):
        return (
            f'{self.booking} - '
            f'{self.get_action_display()}'
        )
