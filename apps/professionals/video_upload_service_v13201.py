"""
V132.06.5A: subida profesional local o privada en Supabase Storage.

Destino:
apps/professionals/video_upload_service_v13201.py

Conserva:
- Validación con FFprobe.
- Límites de suscripción.
- Confirmación de derechos.
- Bloqueo transaccional de cuotas.
- Compatibilidad con almacenamiento local.
- Subida privada a Supabase Storage.

El modo remoto reserva la cuota en PROCESSING,
sube fuera de la transacción y deja PENDING_REVIEW
después de verificar el objeto.

V132.06.5A:
Si falla una subida remota, registra una tarea duradera
de limpieza antes de liberar la reserva.

La eliminación del objeto remoto se intenta únicamente
después de confirmar la transacción de la base de datos.
"""

import logging
import os
import tempfile

from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import transaction
from django.db.models import Q, Sum

from .models import ProfessionalProfile

from .professional_video_quota_v13200 import (
    get_professional_video_quota,
    validate_professional_video_upload,
)

from .video_models_v13200 import ProfessionalPortfolioVideo

from .video_probe_v13201 import (
    SUPPORTED_VIDEO_EXTENSIONS,
    probe_local_video,
)

from .video_storage_config_v13206 import (
    get_professional_video_storage_config,
)

from .video_storage_cleanup_models_v132065 import (
    ProfessionalVideoStorageCleanup,
)

from .video_storage_cleanup_service_v132065 import (
    queue_remote_video_cleanup,
    run_remote_video_cleanup,
)

from .video_supabase_s3_adapter_v13206 import (
    SupabaseVideoS3Adapter,
)


logger = logging.getLogger(__name__)


_CONTENT_TYPES = {
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
}


def _cleanup_failed_upload_after_commit(task_id):
    """
    Intenta limpiar una subida fallida después del commit.

    Si Supabase no está disponible, el servicio conserva
    automáticamente la tarea pendiente.

    Un error inesperado tampoco debe borrar la tarea.
    """

    try:
        completed = run_remote_video_cleanup(task_id)

        if not completed:
            logger.warning(
                'Quedó pendiente la limpieza de subida %s.',
                task_id,
            )

    except Exception:
        logger.exception(
            'No se pudo procesar la limpieza de subida %s.',
            task_id,
        )


def _locked_profile_with_available_quota(
    user,
    *,
    duration_seconds,
    file_size_bytes,
):
    """
    Obtiene el perfil profesional con bloqueo transaccional.

    Debe ejecutarse exclusivamente dentro de transaction.atomic().
    """

    try:
        profile = (
            ProfessionalProfile.objects
            .select_for_update()
            .get(
                user=user,
                verification_status=(
                    ProfessionalProfile
                    .VerificationStatus.VERIFIED
                ),
            )
        )

    except ProfessionalProfile.DoesNotExist as exc:
        raise ValidationError(
            'Necesitas un perfil profesional verificado.'
        ) from exc

    # Los objetos externos en PROCESSING también reservan cuota.
    stored = (
        ProfessionalPortfolioVideo.objects
        .filter(
            professional_profile=profile,
        )
        .filter(
            ~Q(video_file='') | ~Q(external_asset_id=''),
        )
    )

    usage = stored.aggregate(
        total_seconds=Sum('duration_seconds'),
    )

    validate_professional_video_upload(
        user,
        duration_seconds=duration_seconds,
        file_size_bytes=file_size_bytes,
        existing_count=stored.count(),
        existing_total_seconds=(
            usage['total_seconds'] or 0
        ),
    )

    return profile


def _save_local_video(
    user,
    *,
    temporary_path,
    extension,
    metadata,
    real_size,
    details,
):
    """
    Conserva el almacenamiento local privado.

    No utiliza Supabase ni genera tareas de limpieza remota.
    """

    with transaction.atomic():

        profile = _locked_profile_with_available_quota(
            user,
            duration_seconds=metadata.duration_seconds,
            file_size_bytes=real_size,
        )

        instance = ProfessionalPortfolioVideo(
            professional_profile=profile,
            status=(
                ProfessionalPortfolioVideo.Status.PENDING_REVIEW
            ),
            storage_backend=(
                ProfessionalPortfolioVideo.StorageBackend.LOCAL
            ),
            duration_seconds=metadata.duration_seconds,
            file_size_bytes=real_size,
            **details,
        )

        saved_name = None

        try:
            with open(temporary_path, 'rb') as source:

                instance.video_file.save(
                    f'video{extension}',
                    File(source),
                    save=False,
                )

            saved_name = instance.video_file.name

            instance.full_clean()
            instance.save()

        except Exception:

            if saved_name:
                instance.video_file.storage.delete(
                    saved_name
                )

            raise

    return instance


def _save_remote_video(
    user,
    *,
    temporary_path,
    extension,
    metadata,
    real_size,
    details,
):
    """
    Sube un video privado mediante Supabase Storage S3.

    La cuota se reserva antes de subir el archivo.

    Si falla el proceso, se registra una tarea persistente
    de limpieza y se libera la reserva de forma transaccional.
    """

    adapter = SupabaseVideoS3Adapter.from_settings()

    # ---------------------------------------------------------
    # PASO 1: RESERVAR LA CUOTA
    # ---------------------------------------------------------

    with transaction.atomic():

        profile = _locked_profile_with_available_quota(
            user,
            duration_seconds=metadata.duration_seconds,
            file_size_bytes=real_size,
        )

        key = adapter.new_key(
            professional_profile_id=profile.pk,
            extension=extension,
        )

        instance = ProfessionalPortfolioVideo(
            professional_profile=profile,
            status=(
                ProfessionalPortfolioVideo.Status.PROCESSING
            ),
            storage_backend=(
                ProfessionalPortfolioVideo.StorageBackend.EXTERNAL
            ),
            external_asset_id=key,
            duration_seconds=metadata.duration_seconds,
            file_size_bytes=real_size,
            **details,
        )

        instance.full_clean()
        instance.save()

    # ---------------------------------------------------------
    # PASO 2: SUBIR A SUPABASE FUERA DE LA TRANSACCIÓN
    # ---------------------------------------------------------

    try:

        with open(temporary_path, 'rb') as source:

            adapter.upload(
                key=key,
                professional_profile_id=profile.pk,
                fileobj=source,
            )

        # -----------------------------------------------------
        # PASO 3: COMPROBAR EL OBJETO REMOTO
        # -----------------------------------------------------

        remote = adapter.head(
            key=key,
            professional_profile_id=profile.pk,
        )

        if remote['size_bytes'] != real_size:
            raise ValidationError(
                'El tamaño remoto no coincide con el video validado.'
            )

        if (
            remote['content_type']
            != _CONTENT_TYPES[extension]
        ):
            raise ValidationError(
                'El formato remoto no coincide con el video validado.'
            )

        # -----------------------------------------------------
        # PASO 4: CAMBIAR EL ESTADO A PENDIENTE DE REVISIÓN
        # -----------------------------------------------------

        with transaction.atomic():

            ProfessionalProfile.objects.select_for_update().get(
                pk=profile.pk,
            )

            current = (
                ProfessionalPortfolioVideo.objects
                .select_for_update()
                .filter(
                    pk=instance.pk,
                    status=(
                        ProfessionalPortfolioVideo.Status.PROCESSING
                    ),
                    professional_profile=profile,
                )
                .first()
            )

            if current is None:
                raise ValidationError(
                    'La carga del video fue cancelada.'
                )

            current.status = (
                ProfessionalPortfolioVideo.Status.PENDING_REVIEW
            )

            current.full_clean()

            current.save(
                update_fields=[
                    'status',
                    'updated_at',
                ],
            )

        return current

    # ---------------------------------------------------------
    # PASO 5: MANEJAR UNA SUBIDA FALLIDA
    # ---------------------------------------------------------

    except Exception as exc:

        # Primero conservamos una referencia recuperable del archivo.
        #
        # La creación de la tarea y la liberación de la reserva
        # se realizan dentro de una misma transacción.
        #
        # Si no se consigue registrar la tarea, el registro
        # PROCESSING no se elimina, para evitar perder
        # la referencia al objeto remoto.

        try:

            with transaction.atomic():

                task = queue_remote_video_cleanup(
                    professional_profile_id=profile.pk,
                    remote_key=key,
                    reason=(
                        ProfessionalVideoStorageCleanup
                        .Reason.FAILED_UPLOAD
                    ),
                )

                # Liberar la cuota del video cuya subida falló.
                ProfessionalPortfolioVideo.objects.filter(
                    pk=instance.pk,
                    status=(
                        ProfessionalPortfolioVideo.Status.PROCESSING
                    ),
                ).delete()

                # Nunca eliminar el objeto antes de confirmar
                # que la tarea quedó registrada en la base de datos.
                transaction.on_commit(
                    lambda task_id=task.pk: (
                        _cleanup_failed_upload_after_commit(
                            task_id
                        )
                    )
                )

        except Exception as cleanup_exc:

            logger.exception(
                'No se pudo registrar la limpieza pendiente '
                'del video %s.',
                instance.pk,
            )

            raise ValidationError(
                'La carga falló y no se pudo registrar su limpieza. '
                'Contacta al administrador antes de reintentar.'
            ) from cleanup_exc

        # Conservar los mensajes de validación esperados.
        if isinstance(exc, ValidationError):
            raise

        logger.exception(
            'Fallo de almacenamiento remoto del video %s.',
            instance.pk,
        )

        raise ValidationError(
            'No se pudo almacenar el video. '
            'Inténtalo nuevamente más tarde.'
        ) from exc


def create_professional_portfolio_video(
    user,
    *,
    uploaded_file,
    title,
    category,
    description='',
    rights_confirmed=False,
):
    """
    Recibe y valida un video profesional.

    El backend activo determina si el almacenamiento es
    local o Supabase.

    La duración y el formato se validan desde el servidor.
    """

    if rights_confirmed is not True:
        raise ValidationError(
            'Confirma que tienes derechos sobre el material y que no contiene '
            'información identificable de pacientes.'
        )

    title = str(title or '').strip()
    description = str(description or '').strip()

    if not title or len(title) > 140:
        raise ValidationError(
            'El título debe tener entre 1 y 140 caracteres.'
        )

    if len(description) > 600:
        raise ValidationError(
            'La descripción supera los 600 caracteres.'
        )

    valid_categories = {
        choice
        for choice, _ in ProfessionalPortfolioVideo.Category.choices
    }

    if category not in valid_categories:
        raise ValidationError(
            'Selecciona una categoría válida.'
        )

    quota = get_professional_video_quota(user)

    if quota.max_videos == 0:
        raise ValidationError(
            'Necesitas un perfil profesional verificado.'
        )

    if not uploaded_file or not hasattr(uploaded_file, 'chunks'):
        raise ValidationError(
            'Selecciona un archivo de video válido.'
        )

    extension = Path(
        str(uploaded_file.name)
    ).suffix.lower()

    if extension not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ValidationError(
            'Por ahora solo se permiten videos MP4 o WebM.'
        )

    if getattr(uploaded_file, 'size', 0) <= 0:
        raise ValidationError(
            'El archivo de video está vacío.'
        )

    if uploaded_file.size > quota.max_file_bytes:
        raise ValidationError(
            'El archivo supera el tamaño permitido por tu plan.'
        )

    details = {
        'title': title,
        'description': description,
        'category': category,
        'rights_confirmed': True,
    }

    temporary_path = None

    try:

        # Windows exige cerrar el archivo temporal
        # antes de abrirlo con FFprobe.
        with tempfile.NamedTemporaryFile(
            prefix='portfolio_v13201_',
            suffix=extension,
            delete=False,
        ) as temporary_file:

            temporary_path = temporary_file.name
            real_size = 0

            for chunk in uploaded_file.chunks():

                real_size += len(chunk)

                if real_size > quota.max_file_bytes:
                    raise ValidationError(
                        'El archivo supera el tamaño permitido por tu plan.'
                    )

                temporary_file.write(chunk)

        if real_size <= 0:
            raise ValidationError(
                'El archivo de video está vacío.'
            )

        metadata = probe_local_video(
            temporary_path,
            extension,
        )

        mode = (
            get_professional_video_storage_config().mode
        )

        if mode == 'local':

            return _save_local_video(
                user,
                temporary_path=temporary_path,
                extension=extension,
                metadata=metadata,
                real_size=real_size,
                details=details,
            )

        return _save_remote_video(
            user,
            temporary_path=temporary_path,
            extension=extension,
            metadata=metadata,
            real_size=real_size,
            details=details,
        )

    finally:

        if (
            temporary_path
            and os.path.exists(temporary_path)
        ):
            os.unlink(
                temporary_path
            )