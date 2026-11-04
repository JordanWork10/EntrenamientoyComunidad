"""V132.06.3B: subida profesional local o privada en Supabase Storage.

Destino: apps/professionals/video_upload_service_v13201.py

Conserva FFprobe, límites por plan, confirmación de derechos y bloqueo
transaccional de cuotas. El modo remoto reserva la cuota en PROCESSING,
sube fuera de la transacción y deja PENDING_REVIEW tras verificar el objeto.
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
from .video_probe_v13201 import SUPPORTED_VIDEO_EXTENSIONS, probe_local_video
from .video_storage_config_v13206 import get_professional_video_storage_config
from .video_supabase_s3_adapter_v13206 import SupabaseVideoS3Adapter


logger = logging.getLogger(__name__)

_CONTENT_TYPES = {
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
}


def _locked_profile_with_available_quota(
    user,
    *,
    duration_seconds,
    file_size_bytes,
):
    """Se llama exclusivamente dentro de transaction.atomic()."""

    try:
        profile = ProfessionalProfile.objects.select_for_update().get(
            user=user,
            verification_status=(
                ProfessionalProfile.VerificationStatus.VERIFIED
            ),
        )
    except ProfessionalProfile.DoesNotExist as exc:
        raise ValidationError(
            'Necesitas un perfil profesional verificado.'
        ) from exc

    # Los objetos externos en PROCESSING también reservan cuota.
    stored = ProfessionalPortfolioVideo.objects.filter(
        professional_profile=profile,
    ).filter(
        ~Q(video_file='') | ~Q(external_asset_id=''),
    )

    usage = stored.aggregate(
        total_seconds=Sum('duration_seconds'),
    )

    validate_professional_video_upload(
        user,
        duration_seconds=duration_seconds,
        file_size_bytes=file_size_bytes,
        existing_count=stored.count(),
        existing_total_seconds=usage['total_seconds'] or 0,
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
    """Conserva la ruta de almacenamiento que ya funciona en desarrollo."""

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
                instance.video_file.storage.delete(saved_name)
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
    """Reserva cuota, sube por S3 y marca pendiente tras comprobar tamaño/tipo."""

    adapter = SupabaseVideoS3Adapter.from_settings()

    # Paso 1: reservar la cuota en un estado que no es público.
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

    # Paso 2: subir fuera del bloqueo de PostgreSQL.
    # El video no se hace público automáticamente.
    try:
        with open(temporary_path, 'rb') as source:
            adapter.upload(
                key=key,
                professional_profile_id=profile.pk,
                fileobj=source,
            )

        remote = adapter.head(
            key=key,
            professional_profile_id=profile.pk,
        )

        if remote['size_bytes'] != real_size:
            raise ValidationError(
                'El tamaño remoto no coincide con el video validado.'
            )

        if remote['content_type'] != _CONTENT_TYPES[extension]:
            raise ValidationError(
                'El formato remoto no coincide con el video validado.'
            )

        # Paso 3: pasar a revisión solamente si el objeto está íntegro.
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

    except Exception as exc:
        # Una subida fallida no debe ocupar cuota.
        # Intentamos eliminar los objetos remotos creados parcialmente.
        try:
            adapter.delete(
                key=key,
                professional_profile_id=profile.pk,
            )
        except Exception:
            logger.exception(
                'No se pudo limpiar el objeto remoto del video %s.',
                instance.pk,
            )

        ProfessionalPortfolioVideo.objects.filter(
            pk=instance.pk,
            status=(
                ProfessionalPortfolioVideo.Status.PROCESSING
            ),
        ).delete()

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
    """Recibe y valida un video; el modo local sigue siendo predeterminado."""

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

    extension = Path(str(uploaded_file.name)).suffix.lower()

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
        # Windows exige cerrar el archivo antes de abrirlo con FFprobe.
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

        mode = get_professional_video_storage_config().mode

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
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)