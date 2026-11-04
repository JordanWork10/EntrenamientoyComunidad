"""Pruebas V132.01: aislamiento, FFprobe y carga con límites de suscripción.

Destino: apps/professionals/tests_professional_video_upload_v13201.py

V132.06.4B:
Las pruebas de subida local fuerzan el almacenamiento local.
Todos los archivos generados se guardan en un directorio temporal,
sin utilizar el bucket real de Supabase.

Comando:
python manage.py test apps.professionals.tests_professional_video_upload_v13201 --verbosity 2
"""

import json
import tempfile

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from .models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalSpecialty,
)
from .video_models_v13200 import ProfessionalPortfolioVideo
from .video_probe_v13201 import (
    VideoProbeResult,
    probe_local_video,
)
from .video_storage_v13201 import PrivatePortfolioStorage
from .video_upload_service_v13201 import (
    create_professional_portfolio_video,
)


def fake_mp4():
    return SimpleUploadedFile(
        'mi_video.mp4',
        b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00' + b'0' * 100,
        content_type='video/mp4',
    )


class VideoProbeTests(SimpleTestCase):

    def test_mp4_must_have_correct_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalido.mp4'
            path.write_bytes(b'NO_ES_MP4')

            with self.assertRaisesRegex(
                ValidationError,
                'encabezado MP4',
            ):
                probe_local_video(
                    path,
                    '.mp4',
                )

    def test_only_mp4_or_webm_allowed(self):
        with self.assertRaisesRegex(
            ValidationError,
            'MP4 o WebM',
        ):
            probe_local_video(
                'cualquier.mov',
                '.mov',
            )

    @patch(
        'apps.professionals.video_probe_v13201.subprocess.run'
    )
    @patch(
        'apps.professionals.video_probe_v13201.shutil.which',
        return_value='ffprobe',
    )
    def test_duration_is_rounded_up(self, _which, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                'format': {
                    'duration': '120.1',
                    'format_name': 'mov,mp4,m4a',
                },
                'streams': [
                    {
                        'codec_type': 'video',
                        'codec_name': 'h264',
                    }
                ],
            }),
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.mp4'

            path.write_bytes(
                b'\x00\x00\x00\x18ftypisom' + b'0' * 100
            )

            metadata = probe_local_video(
                path,
                '.mp4',
            )

        self.assertEqual(
            metadata.duration_seconds,
            121,
        )

    @patch(
        'apps.professionals.video_probe_v13201.subprocess.run'
    )
    @patch(
        'apps.professionals.video_probe_v13201.shutil.which',
        return_value='ffprobe',
    )
    def test_audio_only_file_is_rejected(self, _which, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                'format': {
                    'duration': '30',
                    'format_name': 'mov,mp4,m4a',
                },
                'streams': [
                    {
                        'codec_type': 'audio',
                        'codec_name': 'aac',
                    }
                ],
            }),
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audio.mp4'

            path.write_bytes(
                b'\x00\x00\x00\x18ftypisom' + b'0' * 100
            )

            with self.assertRaisesRegex(
                ValidationError,
                'Códec no compatible',
            ):
                probe_local_video(
                    path,
                    '.mp4',
                )


@override_settings(PROFESSIONAL_VIDEO_STORAGE_MODE='local')
class ProfessionalVideoUploadTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.owner = User.objects.create_user(
            username='video_upload_owner_13201',
            email='video_upload_owner_13201@example.test',
            password='test-pass',
        )

        cls.pending_owner = User.objects.create_user(
            username='video_upload_pending_13201',
            email='video_upload_pending_13201@example.test',
            password='test-pass',
        )

        category = ProfessionalCategory.objects.create(
            name='Videos V13201',
            slug='videos-v13201',
        )

        specialty = ProfessionalSpecialty.objects.create(
            category=category,
            name='Técnicas audiovisuales',
            slug='tecnicas-v13201',
        )

        cls.profile = ProfessionalProfile.objects.create(
            user=cls.owner,
            category=category,
            specialty=specialty,
            bio='Perfil de pruebas',
            verification_status=(
                ProfessionalProfile.VerificationStatus.VERIFIED
            ),
        )

        ProfessionalProfile.objects.create(
            user=cls.pending_owner,
            category=category,
            specialty=specialty,
            bio='Perfil pendiente',
            verification_status=(
                ProfessionalProfile.VerificationStatus.PENDING
            ),
        )

    def setUp(self):
        # Cada prueba utiliza almacenamiento privado temporal.
        # No debe escribir en el bucket real de Supabase.
        self.private_directory = tempfile.TemporaryDirectory()

        self.storage_settings = override_settings(
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=(
                self.private_directory.name
            ),
        )

        self.storage_settings.enable()

        self.field = (
            ProfessionalPortfolioVideo
            ._meta
            .get_field('video_file')
        )

        self.original_storage = self.field.storage
        self.field.storage = PrivatePortfolioStorage()

    def tearDown(self):
        self.field.storage = self.original_storage

        self.storage_settings.disable()
        self.private_directory.cleanup()

    def _upload(self, *, user=None, **overrides):
        arguments = {
            'uploaded_file': fake_mp4(),
            'title': 'Ejercicio demostrativo',
            'category': (
                ProfessionalPortfolioVideo.Category.EXERCISES
            ),
            'description': 'Sin datos personales',
            'rights_confirmed': True,
        }

        arguments.update(overrides)

        return create_professional_portfolio_video(
            user or self.owner,
            **arguments,
        )

    def test_private_storage_never_produces_public_url(self):
        with self.assertRaisesRegex(
            ValueError,
            'URL directa',
        ):
            self.field.storage.url(
                'un-video.mp4'
            )

    @patch(
        'apps.professionals.video_upload_service_v13201.probe_local_video'
    )
    def test_valid_video_saved_privately_and_left_pending_review(
        self,
        probe,
    ):
        probe.return_value = VideoProbeResult(
            60,
            'h264',
            '.mp4',
        )

        video = self._upload()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
        )

        self.assertTrue(
            video.rights_confirmed
        )

        self.assertEqual(
            video.duration_seconds,
            60,
        )

        self.assertEqual(
            video.file_size_bytes,
            fake_mp4().size,
        )

        self.assertTrue(
            video.video_file.storage.exists(
                video.video_file.name
            )
        )

        self.assertIn(
            'professional_videos/',
            video.video_file.name,
        )

    def test_rights_must_be_confirmed(self):
        with self.assertRaisesRegex(
            ValidationError,
            'derechos',
        ):
            self._upload(
                rights_confirmed=False
            )

    def test_unverified_professional_cannot_upload(self):
        with self.assertRaisesRegex(
            ValidationError,
            'verificado',
        ):
            self._upload(
                user=self.pending_owner
            )

    def test_mov_file_is_not_supported_yet(self):
        file = SimpleUploadedFile(
            'viejo.mov',
            b'video',
        )

        with self.assertRaisesRegex(
            ValidationError,
            'MP4 o WebM',
        ):
            self._upload(
                uploaded_file=file
            )

    @patch(
        'apps.professionals.video_upload_service_v13201.probe_local_video'
    )
    def test_duration_over_basic_quota_is_rejected_before_file_storage(
        self,
        probe,
    ):
        probe.return_value = VideoProbeResult(
            121,
            'h264',
            '.mp4',
        )

        with self.assertRaisesRegex(
            ValidationError,
            'duración individual',
        ):
            self._upload()

        self.assertEqual(
            ProfessionalPortfolioVideo.objects.count(),
            0,
        )

    @patch(
        'apps.professionals.video_upload_service_v13201.probe_local_video'
    )
    def test_basic_plan_cannot_store_more_than_three_videos(
        self,
        probe,
    ):
        probe.return_value = VideoProbeResult(
            30,
            'h264',
            '.mp4',
        )

        for index in range(3):
            self._upload(
                title=f'Demostración {index}'
            )

        with self.assertRaisesRegex(
            ValidationError,
            'máximo de 3',
        ):
            self._upload(
                title='Cuarto video'
            )

        self.assertEqual(
            ProfessionalPortfolioVideo.objects.count(),
            3,
        )