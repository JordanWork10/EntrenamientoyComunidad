"""
V132.06.5A - Eliminación recuperable de videos profesionales.

Destino:
apps/professionals/video_delete_views_v132065.py

Mantiene la autorización del propietario y la protección CSRF.

Para archivos Supabase:
1. Registra una tarea persistente de limpieza.
2. Elimina el registro del portafolio.
3. Intenta eliminar el archivo remoto después del commit.
4. Si Supabase falla, conserva la tarea pendiente.

Los videos locales mantienen su comportamiento anterior.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    ImproperlyConfigured,
    ValidationError,
)
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import ProfessionalProfile
from .video_models_v13200 import ProfessionalPortfolioVideo
from .video_storage_cleanup_models_v132065 import (
    ProfessionalVideoStorageCleanup,
)
from .video_storage_cleanup_service_v132065 import (
    queue_remote_video_cleanup,
    run_remote_video_cleanup,
)


logger = logging.getLogger(__name__)


def _cleanup_after_commit(task_id):
    """
    Ejecuta la limpieza después de confirmar la transacción.

    Si ocurre un error inesperado, la tarea permanece registrada.
    """
    try:
        run_remote_video_cleanup(task_id)

    except Exception:
        logger.exception(
            'No se pudo procesar la tarea de limpieza %s.',
            task_id,
        )


def _delete_local_after_commit(storage, filename):
    """
    Conserva el comportamiento existente del almacenamiento local.

    Los archivos locales no se envían al servicio S3.
    """
    try:
        storage.delete(filename)

    except Exception:
        logger.exception(
            'No se pudo borrar un video local del portafolio.'
        )


@login_required
@require_POST
def portfolio_delete(request, public_id):
    """
    Elimina un video perteneciente al profesional autenticado.

    La eliminación remota utiliza una tarea persistente para
    evitar perder la referencia del objeto si Supabase falla.
    """

    try:
        profile = request.user.professional_profile

    except (
        AttributeError,
        ProfessionalProfile.DoesNotExist,
    ):
        return HttpResponseForbidden(
            'Se requiere un perfil profesional verificado.'
        )

    if (
        profile.verification_status
        != ProfessionalProfile.VerificationStatus.VERIFIED
    ):
        return HttpResponseForbidden(
            'Se requiere un perfil profesional verificado.'
        )

    remote_delete_requested = False

    try:
        with transaction.atomic():

            # Evita operaciones simultáneas que alteren el mismo
            # portafolio mientras se procesa la eliminación.
            ProfessionalProfile.objects.select_for_update().get(
                pk=profile.pk,
            )

            video = get_object_or_404(
                ProfessionalPortfolioVideo.objects.select_for_update(),
                public_id=public_id,
                professional_profile_id=profile.pk,
            )

            backend = video.storage_backend
            remote_key = video.external_asset_id

            saved_name = (
                video.video_file.name
                if video.video_file
                else None
            )

            storage = video.video_file.storage

            if (
                backend
                == ProfessionalPortfolioVideo.StorageBackend.EXTERNAL
                and remote_key
            ):

                # La tarea se registra ANTES de eliminar
                # el registro del video.
                #
                # Si falla la creación de esta tarea,
                # se revierte toda la transacción.
                task = queue_remote_video_cleanup(
                    professional_profile_id=profile.pk,
                    remote_key=remote_key,
                    reason=(
                        ProfessionalVideoStorageCleanup
                        .Reason.USER_DELETE
                    ),
                )

                # El video deja de estar disponible en el portafolio.
                video.delete()

                # La conexión remota se utiliza únicamente después
                # de confirmar la transacción de la base de datos.
                transaction.on_commit(
                    lambda task_id=task.pk: (
                        _cleanup_after_commit(task_id)
                    )
                )

                remote_delete_requested = True

            else:

                # Los videos locales conservan el procedimiento
                # que ya estaba funcionando.
                video.delete()

                if (
                    backend
                    == ProfessionalPortfolioVideo.StorageBackend.LOCAL
                    and saved_name
                ):
                    transaction.on_commit(
                        lambda store=storage, name=saved_name: (
                            _delete_local_after_commit(
                                store,
                                name,
                            )
                        )
                    )

    except (
        ValidationError,
        ValueError,
        ImproperlyConfigured,
    ):
        logger.exception(
            'No se pudo preparar la eliminación del portafolio.'
        )

        messages.error(
            request,
            'No se pudo preparar la eliminación. '
            'El video no fue modificado.',
        )

        return redirect(
            'professionals:portfolio_manager'
        )

    if remote_delete_requested:
        messages.success(
            request,
            'Video retirado del portafolio. '
            'La limpieza remota quedó registrada.',
        )

    else:
        messages.success(
            request,
            'Video eliminado del portafolio.',
        )

    return redirect(
        'professionals:portfolio_manager'
    )