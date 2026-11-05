"""
V132.06.5A - Servicio de limpieza de videos en Supabase Storage.

Destino:
apps/professionals/video_storage_cleanup_service_v132065.py

Responsabilidades:
- Registrar trabajos pendientes de limpieza.
- Validar que la clave S3 corresponda al profesional.
- Eliminar objetos remotos mediante el adaptador privado.
- Conservar los trabajos fallidos para reintentos.
- Evitar utilizar accidentalmente otro bucket o endpoint.

No almacena credenciales.
No genera URLs públicas.
No elimina archivos sin una tarea registrada.
"""

import logging

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from .models import ProfessionalVideoStorageCleanup
from .video_storage_config_v13206 import (
    get_professional_video_storage_config,
)
from .video_supabase_s3_adapter_v13206 import (
    SupabaseVideoS3Adapter,
)


logger = logging.getLogger(__name__)


def _normalized_endpoint(value):
    """
    Normaliza el endpoint exclusivamente para comparaciones.

    No modifica la configuración de conexión utilizada por boto3.
    """
    return str(value or '').strip().rstrip('/')


def _current_remote_configuration():
    """
    Obtiene la configuración activa del almacenamiento remoto.

    No permite procesar eliminaciones mientras el backend
    activo sea local.
    """
    config = get_professional_video_storage_config()

    if config.mode != 'supabase':
        raise ImproperlyConfigured(
            'La limpieza remota requiere el modo Supabase activo.'
        )

    return config


def queue_remote_video_cleanup(
    *,
    professional_profile_id,
    remote_key,
    reason,
):
    """
    Registra una tarea persistente de limpieza.

    Esta función no elimina el archivo.
    Únicamente conserva la información necesaria para
    ejecutar la eliminación posteriormente.

    La restricción única de la base de datos evita crear
    tareas duplicadas para el mismo objeto remoto.
    """
    config = _current_remote_configuration()

    # Impide registrar rutas arbitrarias o pertenecientes
    # a otro profesional.
    SupabaseVideoS3Adapter._validate_key(
        remote_key,
        professional_profile_id,
    )

    valid_reasons = {
        ProfessionalVideoStorageCleanup.Reason.FAILED_UPLOAD,
        ProfessionalVideoStorageCleanup.Reason.USER_DELETE,
    }

    if reason not in valid_reasons:
        raise ValueError(
            'Motivo de limpieza de video no válido.'
        )

    bucket_name = str(config.supabase_bucket).strip()
    storage_endpoint = _normalized_endpoint(
        config.supabase_endpoint
    )

    with transaction.atomic():
        task, created = (
            ProfessionalVideoStorageCleanup.objects.get_or_create(
                professional_profile_id_snapshot=professional_profile_id,
                remote_key=remote_key,
                defaults={
                    'bucket_name': bucket_name,
                    'storage_endpoint': storage_endpoint,
                    'reason': reason,
                    'status': (
                        ProfessionalVideoStorageCleanup.Status.PENDING
                    ),
                },
            )
        )

        if not created:
            if (
                task.bucket_name != bucket_name
                or _normalized_endpoint(task.storage_endpoint)
                != storage_endpoint
            ):
                raise ValueError(
                    'Ya existe una tarea de limpieza para este '
                    'archivo con otra configuración de almacenamiento.'
                )

    return task


def _record_cleanup_failure(task_id, error):
    """
    Registra un intento fallido sin perder la tarea.

    Se guarda únicamente el tipo de error para evitar
    almacenar accidentalmente información sensible.
    """
    with transaction.atomic():
        task = (
            ProfessionalVideoStorageCleanup.objects
            .select_for_update()
            .get(pk=task_id)
        )

        if (
            task.status
            == ProfessionalVideoStorageCleanup.Status.COMPLETED
        ):
            return

        task.attempts += 1
        task.last_error = type(error).__name__[:500]

        task.save(
            update_fields=[
                'attempts',
                'last_error',
                'updated_at',
            ]
        )


def _record_cleanup_success(task_id):
    """
    Marca una tarea como completada.

    La tarea se conserva para contar con un registro
    auditable de la operación.
    """
    with transaction.atomic():
        task = (
            ProfessionalVideoStorageCleanup.objects
            .select_for_update()
            .get(pk=task_id)
        )

        if (
            task.status
            == ProfessionalVideoStorageCleanup.Status.COMPLETED
        ):
            return

        task.attempts += 1
        task.status = (
            ProfessionalVideoStorageCleanup.Status.COMPLETED
        )
        task.last_error = ''
        task.completed_at = timezone.now()

        task.save(
            update_fields=[
                'attempts',
                'status',
                'last_error',
                'completed_at',
                'updated_at',
            ]
        )


def run_remote_video_cleanup(task_id):
    """
    Intenta ejecutar una tarea de limpieza registrada.

    Devuelve:
        True: el objeto se eliminó y la tarea quedó completada.
        False: la eliminación falló y la tarea continúa pendiente.

    Nunca elimina el registro de la tarea si falla Supabase.
    """
    task = ProfessionalVideoStorageCleanup.objects.get(
        pk=task_id
    )

    if (
        task.status
        == ProfessionalVideoStorageCleanup.Status.COMPLETED
    ):
        return True

    try:
        config = _current_remote_configuration()

        # Evita ejecutar un trabajo antiguo contra un proyecto
        # o bucket diferente del original.
        if (
            task.bucket_name != config.supabase_bucket
            or _normalized_endpoint(task.storage_endpoint)
            != _normalized_endpoint(config.supabase_endpoint)
        ):
            raise ImproperlyConfigured(
                'El destino de almacenamiento actual no coincide '
                'con el registrado para la limpieza.'
            )

        # Validar nuevamente la propiedad del objeto.
        SupabaseVideoS3Adapter._validate_key(
            task.remote_key,
            task.professional_profile_id_snapshot,
        )

        adapter = SupabaseVideoS3Adapter.from_settings()

        if adapter.bucket != task.bucket_name:
            raise ImproperlyConfigured(
                'El cliente remoto utiliza un bucket diferente.'
            )

        adapter.delete(
            key=task.remote_key,
            professional_profile_id=(
                task.professional_profile_id_snapshot
            ),
        )

    except Exception as exc:
        logger.exception(
            'Falló la limpieza remota de la tarea %s.',
            task_id,
        )

        _record_cleanup_failure(
            task_id,
            exc,
        )

        return False

    _record_cleanup_success(task_id)

    logger.info(
        'Limpieza remota completada para la tarea %s.',
        task_id,
    )

    return True


def run_pending_remote_video_cleanups(*, limit=100):
    """
    Reintenta tareas pendientes en orden de creación.

    El límite evita procesar un volumen ilimitado de
    operaciones en una sola ejecución.

    Cada tarea se procesa independientemente.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError(
            'El límite debe ser un entero entre 1 y 1000.'
        )

    pending_ids = list(
        ProfessionalVideoStorageCleanup.objects.filter(
            status=ProfessionalVideoStorageCleanup.Status.PENDING,
        )
        .order_by('created_at', 'pk')
        .values_list('pk', flat=True)[:limit]
    )

    completed = 0
    failed = 0

    for task_id in pending_ids:
        if run_remote_video_cleanup(task_id):
            completed += 1
        else:
            failed += 1

    return {
        'processed': len(pending_ids),
        'completed': completed,
        'failed': failed,
    }