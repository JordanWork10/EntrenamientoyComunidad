"""Destino: apps/professionals/video_storage_v13201.py

V132.06.3A: almacenamiento local privado siempre disponible.

El FileField de Django debe poder instanciarse en modo local y Supabase:
su existencia no activa cargas locales cuando el modo remoto está elegido.

Esto permite leer los archivos locales antiguos mientras los nuevos se
registran en external_asset_id mediante el adaptador remoto
(etapa siguiente).
"""

from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible

from .video_storage_config_v13206 import (
    get_professional_video_storage_config,
)


@deconstructible
class PrivatePortfolioStorage(FileSystemStorage):
    """Aísla videos del MEDIA_ROOT y nunca entrega una URL directa."""

    def __init__(self):
        config = get_professional_video_storage_config()

        super().__init__(
            location=str(config.local_root),
            base_url=None,
            file_permissions_mode=0o600,
            directory_permissions_mode=0o700,
        )

    def url(self, name):
        raise ValueError(
            'Los videos privados no tienen URL directa. '
            'Usa la vista autorizada.'
        )