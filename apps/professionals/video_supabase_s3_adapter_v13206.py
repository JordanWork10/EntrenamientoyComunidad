"""V132.06.2: adaptador S3 preparado para Supabase Storage.

Destino: apps/professionals/video_supabase_s3_adapter_v13206.py

No modifica modelos, rutas ni almacenamiento activo.
Las vistas deben autorizar al usuario antes de utilizar
el adaptador en V132.06.3.
"""

import re
from uuid import uuid4

from django.core.exceptions import ImproperlyConfigured

from .video_storage_config_v13206 import (
    get_professional_video_storage_config,
)


_KEY_PATTERN = re.compile(
    r'professional_videos/([1-9][0-9]*)/[0-9a-f]{32}\.(mp4|webm)'
)

_CONTENT_TYPES = {
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
}


class SupabaseVideoS3Adapter:
    """Operaciones limitadas a objetos individuales del portafolio.

    No expone una URL pública ni decide permisos de usuarios Django.
    Las claves administrativas S3 deben permanecer en el servidor.
    """

    def __init__(self, *, client, bucket):
        bucket = str(bucket or '').strip()

        if not re.fullmatch(
            r'[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]',
            bucket,
        ):
            raise ValueError('Nombre de bucket inválido.')

        if client is None:
            raise ValueError(
                'Es obligatorio proporcionar un cliente S3.'
            )

        self.client = client
        self.bucket = bucket

    @classmethod
    def from_settings(cls):
        """Crear cliente real solo cuando se active el backend remoto."""

        config = get_professional_video_storage_config()

        if config.mode != 'supabase':
            raise ImproperlyConfigured(
                'Activa primero '
                'PROFESSIONAL_VIDEO_STORAGE_MODE=supabase.'
            )

        try:
            import boto3
            from botocore.config import Config

        except ImportError as exc:
            raise ImproperlyConfigured(
                'Se requiere boto3 para conectar con '
                'Supabase Storage S3.'
            ) from exc

        client = boto3.client(
            's3',
            endpoint_url=config.supabase_endpoint,
            region_name=config.supabase_region,
            aws_access_key_id=config.supabase_access_key,
            aws_secret_access_key=config.supabase_secret_key,
            config=Config(
                signature_version='s3v4',
                s3={
                    'addressing_style': 'path',
                },
            ),
        )

        return cls(
            client=client,
            bucket=config.supabase_bucket,
        )

    @staticmethod
    def new_key(*, professional_profile_id, extension):
        """Genera una clave privada y única para cada video."""

        if (
            type(professional_profile_id) is not int
            or professional_profile_id <= 0
        ):
            raise ValueError(
                'Identificador profesional inválido.'
            )

        extension = str(extension or '').lower()

        if extension not in _CONTENT_TYPES:
            raise ValueError(
                'Solo se admiten archivos MP4 o WebM.'
            )

        return (
            f'professional_videos/{professional_profile_id}/'
            f'{uuid4().hex}{extension}'
        )

    @staticmethod
    def _validate_key(key, professional_profile_id):
        """Comprueba que el objeto pertenece al profesional indicado."""

        if (
            type(professional_profile_id) is not int
            or professional_profile_id <= 0
        ):
            raise ValueError(
                'Identificador profesional inválido.'
            )

        match = _KEY_PATTERN.fullmatch(str(key or ''))

        if (
            not match
            or int(match.group(1)) != professional_profile_id
        ):
            raise ValueError(
                'El objeto no pertenece al portafolio indicado.'
            )

        return f'.{match.group(2)}'

    def upload(self, *, key, professional_profile_id, fileobj):
        """Subir archivo ya validado por FFprobe y las cuotas."""

        extension = self._validate_key(
            key,
            professional_profile_id,
        )

        if not hasattr(fileobj, 'read'):
            raise ValueError(
                'Se requiere un archivo binario abierto.'
            )

        if hasattr(fileobj, 'seek'):
            fileobj.seek(0)

        self.client.upload_fileobj(
            fileobj,
            self.bucket,
            key,
            ExtraArgs={
                'ContentType': _CONTENT_TYPES[extension],
                'ContentDisposition': 'inline',
                'CacheControl': 'private, no-store',
            },
        )

        return key

    def head(self, *, key, professional_profile_id):
        """Consultar metadatos remotos para validar una subida."""

        self._validate_key(
            key,
            professional_profile_id,
        )

        response = self.client.head_object(
            Bucket=self.bucket,
            Key=key,
        )

        size = int(response.get('ContentLength', 0))

        if size <= 0:
            raise ValueError(
                'El objeto remoto no tiene tamaño válido.'
            )

        return {
            'size_bytes': size,
            'content_type': response.get(
                'ContentType',
                '',
            ),
        }

    def get(
        self,
        *,
        key,
        professional_profile_id,
        byte_range=None,
    ):
        """Obtener stream remoto; quien lo consuma debe cerrar Body.

        No transmite bytes al navegador ni concede acceso
        por sí mismo.
        """

        self._validate_key(
            key,
            professional_profile_id,
        )

        arguments = {
            'Bucket': self.bucket,
            'Key': key,
        }

        if byte_range is not None:
            match = re.fullmatch(
                r'bytes=([0-9]*)-([0-9]*)',
                byte_range,
            )

            if not match or (
                not match.group(1)
                and not match.group(2)
            ):
                raise ValueError(
                    'Rango de bytes inválido.'
                )

            if (
                match.group(1)
                and match.group(2)
                and int(match.group(1)) > int(match.group(2))
            ):
                raise ValueError(
                    'Rango de bytes inválido.'
                )

            arguments['Range'] = byte_range

        return self.client.get_object(**arguments)

    def delete(self, *, key, professional_profile_id):
        """Eliminar únicamente el objeto privado indicado."""

        self._validate_key(
            key,
            professional_profile_id,
        )

        return self.client.delete_object(
            Bucket=self.bucket,
            Key=key,
        )