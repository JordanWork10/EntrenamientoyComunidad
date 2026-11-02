"""V132.00, etapa 2: registro del portafolio audiovisual profesional.

Destino: apps/professionals/video_models_v13200.py

Solo material demostrativo público. NO es una ficha clínica ni habilita
almacenamiento de videos de pacientes; ese módulo requerirá otros permisos.
"""

from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q

from .video_storage_v13201 import PrivatePortfolioStorage


def professional_portfolio_upload_path(instance, filename):
    """No conservar nombres originales de archivos en URLs de medios."""
    extension = Path(filename).suffix.lower()
    if extension not in {'.mp4', '.mov', '.webm'}:
        extension = '.bin'
    return (
        f'professional_videos/{instance.professional_profile_id}/'
        f'{uuid4().hex}{extension}'
    )


class ProfessionalPortfolioVideo(models.Model):
    """Metadatos del video; la reproducción se implementará aparte.

    El estado aprobado se reserva para archivos revisados y con metadatos
    verificados POR EL SERVIDOR. No confiar en duración/tamaño enviados
    por formularios del navegador. El almacenamiento final puede ser local
    (solo sandbox) o un proveedor especializado externo.
    """

    class Category(models.TextChoices):
        PRESENTATION = 'presentation', 'Presentación profesional'
        TECHNIQUE = 'technique', 'Demostración técnica'
        EXERCISES = 'exercises', 'Ejercicios y movilidad'
        EDUCATIONAL = 'educational', 'Contenido educativo'
        OTHER = 'other', 'Otro contenido'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Borrador'
        PROCESSING = 'processing', 'Procesando'
        PENDING_REVIEW = 'pending_review', 'Pendiente de revisión'
        APPROVED = 'approved', 'Publicado'
        REJECTED = 'rejected', 'Rechazado'
        HIDDEN = 'hidden', 'Oculto'

    class StorageBackend(models.TextChoices):
        LOCAL = 'local', 'Almacenamiento de desarrollo'
        EXTERNAL = 'external', 'Proveedor de video externo'

    public_id = models.UUIDField(
        default=uuid4, unique=True, editable=False, db_index=True,
    )
    professional_profile = models.ForeignKey(
        'professionals.ProfessionalProfile',
        on_delete=models.CASCADE,
        related_name='portfolio_videos',
    )
    title = models.CharField(max_length=140)
    description = models.TextField(blank=True, max_length=600)
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.PRESENTATION,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT,
    )

    # Subir/reproducir archivos sigue deshabilitado hasta integrar la vista
    # con validación real de formatos, duración, cuotas y permisos.
    video_file = models.FileField(
        upload_to=professional_portfolio_upload_path,
        storage=PrivatePortfolioStorage(),
        validators=[FileExtensionValidator(['mp4', 'mov', 'webm'])],
        blank=True,
        max_length=400,
    )
    storage_backend = models.CharField(
        max_length=20,
        choices=StorageBackend.choices,
        default=StorageBackend.LOCAL,
    )
    external_asset_id = models.CharField(max_length=160, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    file_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    rights_confirmed = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)
    review_notes = models.TextField(blank=True, max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Video de portafolio profesional'
        verbose_name_plural = 'Videos de portafolio profesional'
        ordering = ['display_order', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['professional_profile'],
                condition=Q(is_featured=True, status='approved'),
                name='one_featured_approved_professional_video',
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status='approved') | (
                        Q(duration_seconds__gt=0)
                        & Q(file_size_bytes__gt=0)
                        & Q(rights_confirmed=True)
                    )
                ),
                name='approved_professional_video_has_metadata',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.APPROVED:
            if not (self.video_file or self.external_asset_id):
                errors['status'] = (
                    'No se puede publicar un video sin un archivo válido.'
                )
            if not self.rights_confirmed:
                errors['rights_confirmed'] = (
                    'Debes confirmar que cuentas con los derechos de publicación.'
                )
            if not self.duration_seconds or not self.file_size_bytes:
                errors['status'] = (
                    'Faltan los metadatos verificados del video.'
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.title} · {self.professional_profile_id}'
