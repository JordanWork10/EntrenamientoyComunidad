import re
from datetime import date

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.locations.models import Commune


def validate_adult(value):
    """
    Valida que la persona tenga al menos 18 años.
    """

    today = date.today()

    age = (
        today.year
        - value.year
        - (
            (today.month, today.day)
            < (value.month, value.day)
        )
    )

    if age < 18:
        raise ValidationError(
            'Debes tener al menos 18 años para registrarte.'
        )


def normalize_rut(value):
    """
    Normaliza un RUT chileno al formato 12345678-5.
    """

    if not value:
        return value

    clean_rut = re.sub(
        r'[^0-9kK]',
        '',
        value
    ).upper()

    if len(clean_rut) < 2:
        return value

    return f'{clean_rut[:-1]}-{clean_rut[-1]}'


def validate_rut(value):
    """
    Valida el dígito verificador de un RUT chileno.
    """

    if not value:
        return

    clean_rut = re.sub(
        r'[^0-9kK]',
        '',
        value
    ).upper()

    if len(clean_rut) < 2:
        raise ValidationError(
            'El RUT ingresado no es válido.'
        )

    body = clean_rut[:-1]
    verifier = clean_rut[-1]

    if not body.isdigit():
        raise ValidationError(
            'El RUT ingresado no es válido.'
        )

    total = 0
    multiplier = 2

    for digit in reversed(body):
        total += int(digit) * multiplier

        multiplier += 1

        if multiplier > 7:
            multiplier = 2

    result = 11 - (total % 11)

    if result == 11:
        expected = '0'

    elif result == 10:
        expected = 'K'

    else:
        expected = str(result)

    if verifier != expected:
        raise ValidationError(
            'El RUT ingresado no es válido.'
        )


class PlatformInterest(models.Model):
    """
    Intereses que un miembro puede seleccionar
    durante su registro.
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

    is_active = models.BooleanField(
        default=True,
        verbose_name='Activo'
    )

    display_order = models.PositiveIntegerField(
        default=0,
        verbose_name='Orden'
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = 'Interés de plataforma'
        verbose_name_plural = 'Intereses de plataforma'
        ordering = [
            'display_order',
            'name',
        ]

    def __str__(self):
        return self.name


class User(AbstractUser):
    """
    Cuenta Única Universal de EntrenamientoyComunidad.

    Una misma cuenta podrá habilitar posteriormente
    perfiles de Profesional y Proveedor de Espacios.
    """

    class Gender(models.TextChoices):
        MAN = (
            'man',
            'Hombre'
        )

        WOMAN = (
            'woman',
            'Mujer'
        )

        OTHER = (
            'other',
            'No binario / Otra identidad'
        )

        PREFER_NOT_TO_SAY = (
            'prefer_not_to_say',
            'Prefiero no indicarlo'
        )

    rut = models.CharField(
        max_length=12,
        unique=True,
        null=True,
        blank=True,
        validators=[validate_rut],
        verbose_name='RUT'
    )

    email = models.EmailField(
        unique=True,
        verbose_name='Correo electrónico'
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Teléfono'
    )

    birth_date = models.DateField(
        null=True,
        blank=True,
        validators=[validate_adult],
        verbose_name='Fecha de nacimiento'
    )

    gender = models.CharField(
        max_length=30,
        choices=Gender.choices,
        blank=True,
        verbose_name='Género'
    )

    commune = models.ForeignKey(
        Commune,
        on_delete=models.PROTECT,
        related_name='users',
        null=True,
        blank=True,
        verbose_name='Comuna'
    )

    profile_image = models.ImageField(
        upload_to='profiles/',
        blank=True,
        null=True,
        verbose_name='Imagen de perfil'
    )

    terms_accepted = models.BooleanField(
        default=False,
        verbose_name='Acepta términos y condiciones'
    )

    privacy_accepted = models.BooleanField(
        default=False,
        verbose_name='Acepta política de privacidad'
    )

    terms_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de aceptación de términos'
    )

    privacy_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de aceptación de privacidad'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización'
    )

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'

    def save(self, *args, **kwargs):

        if self.rut:
            self.rut = normalize_rut(self.rut)

        super().save(*args, **kwargs)

    def __str__(self):

        full_name = self.get_full_name()

        if full_name:
            return full_name

        return self.email


class MemberProfile(models.Model):
    """
    Perfil Miembro Base.

    Todo usuario registrado mediante la plataforma
    contará con este perfil.
    """

    class ActivityLevel(models.TextChoices):
        LOW = 'low', 'Actividad baja'
        MODERATE = 'moderate', 'Actividad moderada'
        ACTIVE = 'active', 'Persona activa'
        HIGH = 'high', 'Actividad alta'
        PERFORMANCE = (
            'performance',
            'Alto rendimiento'
        )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='member_profile',
        verbose_name='Usuario'
    )

    activity_level = models.CharField(
        max_length=20,
        choices=ActivityLevel.choices,
        blank=True,
        verbose_name='Nivel de actividad física'
    )

    interests = models.ManyToManyField(
        PlatformInterest,
        blank=True,
        related_name='members',
        verbose_name='Intereses'
    )

    emergency_contact_name = models.CharField(
        max_length=150,
        blank=True,
        verbose_name='Nombre contacto de emergencia'
    )

    emergency_contact_relationship = models.CharField(
        max_length=80,
        blank=True,
        verbose_name='Relación o parentesco'
    )

    emergency_contact_phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Teléfono de emergencia'
    )

    fitness_declaration_accepted = models.BooleanField(
        default=False,
        verbose_name='Declaración de aptitud física aceptada'
    )

    fitness_declaration_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha declaración de aptitud'
    )

    protected_payment_accepted = models.BooleanField(
        default=False,
        verbose_name='Condiciones de pago protegido aceptadas'
    )

    protected_payment_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha aceptación pago protegido'
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
        verbose_name = 'Perfil de miembro'
        verbose_name_plural = 'Perfiles de miembros'

    def __str__(self):
        return f'Miembro - {self.user}'


# =====================================================
# V128 - ESTADO DE LECTURA DE NOVEDADES
# =====================================================

class NotificationReadState(models.Model):
    """
    Registra las novedades que un usuario ha revisado.

    Las novedades originales siguen obteniéndose desde
    reservas, actividades, espacios e incidencias.

    Este modelo solamente almacena:
    - quién revisó la novedad;
    - en qué panel la revisó;
    - la clave única de la novedad;
    - cuándo quedó revisada.

    Esto permite conservar el estado entre dispositivos,
    sin modificar los historiales originales.
    """

    class Scope(models.TextChoices):

        MEMBER = (
            'member',
            'Miembro'
        )

        PROFESSIONAL = (
            'professional',
            'Profesional'
        )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_read_states',
        verbose_name='Usuario'
    )

    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        verbose_name='Panel'
    )

    notification_key = models.CharField(
        max_length=255,
        verbose_name='Clave de la novedad'
    )

    read_at = models.DateTimeField(
        default=timezone.now,
        verbose_name='Fecha de revisión'
    )

    class Meta:

        verbose_name = 'Novedad revisada'
        verbose_name_plural = 'Novedades revisadas'

        ordering = [
            '-read_at',
            '-id',
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'user',
                    'scope',
                    'notification_key',
                ],
                name='unique_notification_read_state'
            )
        ]

    def __str__(self):

        return (
            f'{self.user} | '
            f'{self.get_scope_display()} | '
            f'{self.notification_key}'
        )