"""V132.06.1: configuración del portafolio audiovisual.

Destino: apps/professionals/video_storage_config_v13206.py

Valida la configuración local y prepara el futuro modo Supabase.
No establece conexiones externas.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True)
class ProfessionalVideoStorageConfig:
    mode: str
    local_root: Path
    supabase_bucket: str = ''
    supabase_endpoint: str = ''
    supabase_region: str = ''
    supabase_access_key: str = field(default='', repr=False)
    supabase_secret_key: str = field(default='', repr=False)


def get_professional_video_storage_config():
    """Valida el almacenamiento privado y la futura configuración S3."""

    mode = str(
        getattr(
            settings,
            'PROFESSIONAL_VIDEO_STORAGE_MODE',
            os.getenv('PROFESSIONAL_VIDEO_STORAGE_MODE', 'local'),
        )
    ).strip().lower()

    if mode not in {'local', 'supabase'}:
        raise ImproperlyConfigured(
            'PROFESSIONAL_VIDEO_STORAGE_MODE debe ser local o supabase.'
        )

    project_root = Path(settings.BASE_DIR).resolve()

    explicit_root = getattr(
        settings,
        'PROFESSIONAL_VIDEO_PRIVATE_ROOT',
        None,
    )

    if explicit_root is None:
        explicit_root = os.getenv(
            'PROFESSIONAL_VIDEO_PRIVATE_ROOT',
            '',
        ).strip()

    # V132.06.1 - CORRECCIÓN:
    #
    # Django ejecuta los tests con settings.DEBUG=False.
    # Eso NO significa que el proyecto esté en producción.
    #
    # Nuestro settings.py obtiene DEBUG desde DJANGO_DEBUG.
    # Usamos ese valor para comprobar el entorno real.
    #
    # En producción deberá configurarse DJANGO_DEBUG=False.

    project_debug = os.getenv(
        'DJANGO_DEBUG',
        'True',
    ).strip().lower() in {
        'true',
        '1',
        'yes',
        'on',
    }

    if mode == 'local' and not project_debug and not explicit_root:
        raise ImproperlyConfigured(
            'En producción, el almacenamiento local requiere una ruta '
            'persistente configurada en PROFESSIONAL_VIDEO_PRIVATE_ROOT.'
        )

    local_root = Path(
        explicit_root or project_root / '_private_professional_videos'
    ).resolve()

    media_value = getattr(settings, 'MEDIA_ROOT', None)

    if media_value:
        media_root = Path(media_value).resolve()

        if (
            local_root == media_root
            or media_root in local_root.parents
        ):
            raise ImproperlyConfigured(
                'Los videos privados deben estar fuera de MEDIA_ROOT.'
            )

    if mode == 'local':
        return ProfessionalVideoStorageConfig(
            mode=mode,
            local_root=local_root,
        )

    names = {
        'SUPABASE_VIDEO_S3_BUCKET': 'supabase_bucket',
        'SUPABASE_VIDEO_S3_ENDPOINT': 'supabase_endpoint',
        'SUPABASE_VIDEO_S3_REGION': 'supabase_region',
        'SUPABASE_VIDEO_S3_ACCESS_KEY': 'supabase_access_key',
        'SUPABASE_VIDEO_S3_SECRET_KEY': 'supabase_secret_key',
    }

    values = {
        key: os.getenv(env_name, '').strip()
        for env_name, key in names.items()
    }

    missing = [
        env_name
        for env_name, key in names.items()
        if not values[key]
    ]

    if missing:
        raise ImproperlyConfigured(
            'Faltan variables de configuración de Supabase: '
            + ', '.join(missing)
        )

    endpoint = urlsplit(values['supabase_endpoint'])

    if (
        endpoint.scheme != 'https'
        or not (endpoint.hostname or '').endswith('.storage.supabase.co')
        or endpoint.path.rstrip('/') != '/storage/v1/s3'
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.query
        or endpoint.fragment
    ):
        raise ImproperlyConfigured(
            'SUPABASE_VIDEO_S3_ENDPOINT debe ser la URL HTTPS S3 oficial '
            'del proyecto, terminada en /storage/v1/s3.'
        )

    return ProfessionalVideoStorageConfig(
        mode=mode,
        local_root=local_root,
        **values,
    )