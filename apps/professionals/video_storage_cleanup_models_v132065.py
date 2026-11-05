"""
V132.06.5A - Registro persistente de limpieza de videos.

Destino:
apps/professionals/video_storage_cleanup_models_v132065.py

Permite conservar tareas pendientes cuando un archivo de Supabase
Storage necesita eliminarse.

No almacena credenciales ni concede acceso público a los archivos.
"""

from django.db import models


class ProfessionalVideoStorageCleanup(models.Model):
    """
    Registro persistente de objetos remotos que deben eliminarse.

    La referencia se conserva aunque desaparezca el registro
    original del video.

    El identificador profesional se guarda como número para
    evitar que una eliminación en cascada borre esta tarea.
    """

    class Reason(models.TextChoices):
        FAILED_UPLOAD = (
            'failed_upload',
            'Limpieza después de una subida fallida',
        )

        USER_DELETE = (
            'user_delete',
            'Eliminación solicitada por el profesional',
        )

    class Status(models.TextChoices):
        PENDING = (
            'pending',
            'Pendiente',
        )

        COMPLETED = (
            'completed',
            'Completada',
        )

    professional_profile_id_snapshot = models.PositiveBigIntegerField(
        db_index=True,
        verbose_name='Identificador profesional original',
    )

    remote_key = models.CharField(
        max_length=160,
        verbose_name='Clave del archivo remoto',
    )

    bucket_name = models.CharField(
        max_length=63,
        verbose_name='Bucket de origen',
    )

    storage_endpoint = models.URLField(
        max_length=500,
        verbose_name='Endpoint de almacenamiento',
    )

    reason = models.CharField(
        max_length=24,
        choices=Reason.choices,
        verbose_name='Motivo de limpieza',
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name='Estado',
    )

    attempts = models.PositiveIntegerField(
        default=0,
        verbose_name='Intentos de eliminación',
    )

    last_error = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Último error',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Creada',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Actualizada',
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Completada el',
    )

    class Meta:
        app_label = 'professionals'

        verbose_name = 'Limpieza de almacenamiento de video'
        verbose_name_plural = 'Limpiezas de almacenamiento de videos'

        ordering = [
            'created_at',
            'pk',
        ]

        indexes = [
            models.Index(
                fields=['status', 'created_at'],
                name='pro_video_cleanup_state_idx',
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'professional_profile_id_snapshot',
                    'remote_key',
                ],
                name='pro_video_cleanup_key_uniq',
            ),
        ]

    def __str__(self):
        return (
            f'Limpieza #{self.pk} - '
            f'{self.get_status_display()}'
        )