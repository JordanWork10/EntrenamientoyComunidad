"""V132.01: subida segura y transaccional de portafolios profesionales.

Destino: apps/professionals/video_upload_service_v13201.py

Este servicio es invocado desde las vistas que implementaremos en V132.02.
No genera enlace público ni aprueba videos automáticamente.
"""

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


def create_professional_portfolio_video(
    user,
    *,
    uploaded_file,
    title,
    category,
    description='',
    rights_confirmed=False,
):
    """Procesa un único video para revisión administrativa.

    El perfil se bloquea al confirmar cuotas para evitar dos publicaciones
    simultáneas que superen los máximos del plan.
    """
    if rights_confirmed is not True:
        raise ValidationError(
            'Confirma que tienes derechos sobre el material y que no contiene '
            'información identificable de pacientes.'
        )

    title = str(title or '').strip()
    description = str(description or '').strip()
    if not title or len(title) > 140:
        raise ValidationError('El título debe tener entre 1 y 140 caracteres.')
    if len(description) > 600:
        raise ValidationError('La descripción supera los 600 caracteres.')
    valid_categories = {
        choice for choice, _ in ProfessionalPortfolioVideo.Category.choices
    }
    if category not in valid_categories:
        raise ValidationError('Selecciona una categoría válida.')

    quota = get_professional_video_quota(user)
    if quota.max_videos == 0:
        raise ValidationError('Necesitas un perfil profesional verificado.')

    if not uploaded_file or not hasattr(uploaded_file, 'chunks'):
        raise ValidationError('Selecciona un archivo de video válido.')
    extension = Path(str(uploaded_file.name)).suffix.lower()
    if extension not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ValidationError('Por ahora solo se permiten videos MP4 o WebM.')
    if getattr(uploaded_file, 'size', 0) <= 0:
        raise ValidationError('El archivo de video está vacío.')
    if uploaded_file.size > quota.max_file_bytes:
        raise ValidationError('El archivo supera el tamaño permitido por tu plan.')

    temporary_path = None
    try:
        # Windows exige cerrar el archivo antes de que ffprobe lo abra.
        with tempfile.NamedTemporaryFile(
            prefix='portfolio_v13201_', suffix=extension, delete=False,
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
            raise ValidationError('El archivo de video está vacío.')

        verified = probe_local_video(temporary_path, extension)

        with transaction.atomic():
            # Bloquea el propietario: el contador se calcula tras adquirirlo.
            try:
                profile = ProfessionalProfile.objects.select_for_update().get(
                    user=user,
                    verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
                )
            except ProfessionalProfile.DoesNotExist as exc:
                raise ValidationError(
                    'Necesitas un perfil profesional verificado.'
                ) from exc

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
                duration_seconds=verified.duration_seconds,
                file_size_bytes=real_size,
                existing_count=stored.count(),
                existing_total_seconds=usage['total_seconds'] or 0,
            )

            instance = ProfessionalPortfolioVideo(
                professional_profile=profile,
                title=title,
                description=description,
                category=category,
                rights_confirmed=True,
                status=ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
                storage_backend=ProfessionalPortfolioVideo.StorageBackend.LOCAL,
                duration_seconds=verified.duration_seconds,
                file_size_bytes=real_size,
            )

            saved_name = None
            try:
                with open(temporary_path, 'rb') as source:
                    instance.video_file.save(
                        f'video{extension}', File(source), save=False,
                    )
                saved_name = instance.video_file.name
                instance.full_clean()
                instance.save()
            except Exception:
                if saved_name:
                    instance.video_file.storage.delete(saved_name)
                raise

        return instance
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
