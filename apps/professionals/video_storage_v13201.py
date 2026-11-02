"""V132.01: almacenamiento LOCAL PRIVADO para videos demostrativos.

Destino: apps/professionals/video_storage_v13201.py

Nunca exponer esta carpeta desde nginx, Apache, WhiteNoise ni MEDIA_URL.
La entrega de bytes se hará mediante una vista que compruebe permisos.
"""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivatePortfolioStorage(FileSystemStorage):
    """Aísla los videos del MEDIA_ROOT normalmente publicado."""

    def __init__(self):
        project_root = Path(settings.BASE_DIR).resolve()
        configured_root = getattr(
            settings,
            'PROFESSIONAL_VIDEO_PRIVATE_ROOT',
            project_root / '_private_professional_videos',
        )
        private_root = Path(configured_root).resolve()

        media_value = getattr(settings, 'MEDIA_ROOT', None)
        if media_value:
            media_root = Path(media_value).resolve()
            if private_root == media_root or media_root in private_root.parents:
                raise ImproperlyConfigured(
                    'PROFESSIONAL_VIDEO_PRIVATE_ROOT debe quedar fuera de MEDIA_ROOT.'
                )

        super().__init__(
            location=str(private_root),
            base_url=None,
            file_permissions_mode=0o600,
            directory_permissions_mode=0o700,
        )

    def url(self, name):
        raise ValueError(
            'Los videos privados no tienen URL directa. Usa la vista autorizada.'
        )
