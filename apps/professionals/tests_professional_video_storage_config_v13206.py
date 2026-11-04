"""Destino: apps/professionals/tests_professional_video_storage_config_v13206.py

Ejecutar:
python manage.py test apps.professionals.tests_professional_video_storage_config_v13206 --verbosity 2
"""

import os
import tempfile

from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from .video_storage_config_v13206 import (
    get_professional_video_storage_config,
)

from .video_storage_v13201 import (
    PrivatePortfolioStorage,
)


SUPABASE_TEST_ENV = {
    'SUPABASE_VIDEO_S3_BUCKET': 'portafolio-privado',
    'SUPABASE_VIDEO_S3_ENDPOINT': (
        'https://ejemplo.storage.supabase.co/storage/v1/s3'
    ),
    'SUPABASE_VIDEO_S3_REGION': 'us-east-1',
    'SUPABASE_VIDEO_S3_ACCESS_KEY': 'clave-prueba-falsa',
    'SUPABASE_VIDEO_S3_SECRET_KEY': 'secreto-prueba-falso',
}


class VideoStorageConfigTests(SimpleTestCase):

    def setUp(self):
        self.private_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.private_directory.cleanup)

    def test_local_mode_uses_isolated_private_root(self):
        with override_settings(
            DEBUG=True,
            PROFESSIONAL_VIDEO_STORAGE_MODE='local',
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=self.private_directory.name,
        ):
            config = get_professional_video_storage_config()
            storage = PrivatePortfolioStorage()

            self.assertEqual(config.mode, 'local')

            self.assertEqual(
                config.local_root,
                Path(self.private_directory.name).resolve(),
            )

            self.assertEqual(
                Path(storage.location),
                config.local_root,
            )

    def test_local_mode_never_generates_public_file_url(self):
        with override_settings(
            DEBUG=True,
            PROFESSIONAL_VIDEO_STORAGE_MODE='local',
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=self.private_directory.name,
        ):
            storage = PrivatePortfolioStorage()

            with self.assertRaisesRegex(
                ValueError,
                'URL directa',
            ):
                storage.url('ejemplo.mp4')

    def test_private_root_inside_media_is_rejected(self):
        with override_settings(
            DEBUG=True,
            PROFESSIONAL_VIDEO_STORAGE_MODE='local',
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=(
                Path(settings.MEDIA_ROOT) / 'portafolio'
            ),
        ):
            with self.assertRaisesRegex(
                ImproperlyConfigured,
                'fuera de MEDIA_ROOT',
            ):
                PrivatePortfolioStorage()

    def test_invalid_storage_mode_is_rejected(self):
        with override_settings(
            PROFESSIONAL_VIDEO_STORAGE_MODE='publico',
        ):
            with self.assertRaisesRegex(
                ImproperlyConfigured,
                'local o supabase',
            ):
                get_professional_video_storage_config()

    def test_production_local_requires_explicit_private_root(self):
        with override_settings(
            DEBUG=False,
            PROFESSIONAL_VIDEO_STORAGE_MODE='local',
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=None,
        ):
            with patch.dict(
                os.environ,
                {
                    'DJANGO_DEBUG': 'False',
                    'PROFESSIONAL_VIDEO_PRIVATE_ROOT': '',
                },
            ):
                with self.assertRaisesRegex(
                    ImproperlyConfigured,
                    'ruta persistente',
                ):
                    PrivatePortfolioStorage()

    def test_test_runner_debug_false_is_not_mistaken_for_production(self):
        with override_settings(
            DEBUG=False,
            PROFESSIONAL_VIDEO_STORAGE_MODE='local',
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=None,
        ):
            with patch.dict(
                os.environ,
                {
                    'DJANGO_DEBUG': 'True',
                    'PROFESSIONAL_VIDEO_PRIVATE_ROOT': '',
                },
            ):
                storage = PrivatePortfolioStorage()

                self.assertTrue(
                    str(storage.location).endswith(
                        '_private_professional_videos'
                    )
                )

    def test_supabase_requires_full_configuration(self):
        blank = {
            key: ''
            for key in SUPABASE_TEST_ENV
        }

        with override_settings(
            PROFESSIONAL_VIDEO_STORAGE_MODE='supabase',
        ):
            with patch.dict(os.environ, blank):
                with self.assertRaisesRegex(
                    ImproperlyConfigured,
                    'Faltan variables',
                ):
                    get_professional_video_storage_config()

    def test_supabase_rejects_untrusted_http_endpoint(self):
        env = {
            **SUPABASE_TEST_ENV,
            'SUPABASE_VIDEO_S3_ENDPOINT': (
                'http://ejemplo.storage.supabase.co/storage/v1/s3'
            ),
        }

        with override_settings(
            PROFESSIONAL_VIDEO_STORAGE_MODE='supabase',
        ):
            with patch.dict(os.environ, env):
                with self.assertRaisesRegex(
                    ImproperlyConfigured,
                    'URL HTTPS S3',
                ):
                    get_professional_video_storage_config()

    def test_supabase_mode_keeps_local_field_available_for_legacy_videos(self):
        with override_settings(
            PROFESSIONAL_VIDEO_STORAGE_MODE='supabase',
        ):
            with patch.dict(
                os.environ,
                SUPABASE_TEST_ENV,
            ):
                config = get_professional_video_storage_config()

                self.assertEqual(
                    config.mode,
                    'supabase',
                )

                self.assertEqual(
                    config.supabase_bucket,
                    'portafolio-privado',
                )

                self.assertNotIn(
                    'secreto-prueba-falso',
                    repr(config),
                )

                storage = PrivatePortfolioStorage()

                self.assertEqual(
                    Path(storage.location),
                    config.local_root,
                )

                with self.assertRaisesRegex(
                    ValueError,
                    'URL directa',
                ):
                    storage.url('video-viejo.mp4')