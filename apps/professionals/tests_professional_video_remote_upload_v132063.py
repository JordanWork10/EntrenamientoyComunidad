"""V132.06.3B: pruebas de subida a Supabase con S3 simulado.

Destino:
apps/professionals/tests_professional_video_remote_upload_v132063.py

No utiliza Supabase ni sus credenciales reales.
"""

import os

from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalSpecialty,
)

from .video_models_v13200 import ProfessionalPortfolioVideo
from .video_probe_v13201 import VideoProbeResult
from .video_upload_service_v13201 import (
    create_professional_portfolio_video,
)


FAKE_S3_ENV = {
    'SUPABASE_VIDEO_S3_BUCKET': 'portafolio-privado',
    'SUPABASE_VIDEO_S3_ENDPOINT': (
        'https://ejemplo.storage.supabase.co/storage/v1/s3'
    ),
    'SUPABASE_VIDEO_S3_REGION': 'us-east-1',
    'SUPABASE_VIDEO_S3_ACCESS_KEY': 'clave-prueba',
    'SUPABASE_VIDEO_S3_SECRET_KEY': 'secreto-prueba',
}


def sample_mp4():
    return SimpleUploadedFile(
        'prueba.mp4',
        b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00' + b'0' * 100,
        content_type='video/mp4',
    )


@override_settings(
    PROFESSIONAL_VIDEO_STORAGE_MODE='supabase'
)
class ProfessionalVideoRemoteUploadTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.owner = user_model.objects.create_user(
            username='video_remote_owner_v132063',
            email='video_remote_owner_v132063@example.test',
            password='test-pass',
        )

        category = ProfessionalCategory.objects.create(
            name='Videos S3 V132063',
            slug='videos-s3-v132063',
        )

        specialty = ProfessionalSpecialty.objects.create(
            category=category,
            name='Videos profesionales S3',
            slug='videos-prof-s3-v132063',
        )

        cls.profile = ProfessionalProfile.objects.create(
            user=cls.owner,
            category=category,
            specialty=specialty,
            bio='Perfil para pruebas remotas',
            verification_status=(
                ProfessionalProfile.VerificationStatus.VERIFIED
            ),
        )

    def setUp(self):
        self.env = patch.dict(
            os.environ,
            FAKE_S3_ENV,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

        self.factory_patch = patch(
            'apps.professionals.video_upload_service_v13201.'
            'SupabaseVideoS3Adapter.from_settings'
        )

        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)

        self.probe_patch = patch(
            'apps.professionals.video_upload_service_v13201.'
            'probe_local_video'
        )

        self.probe = self.probe_patch.start()
        self.addCleanup(self.probe_patch.stop)

        self.probe.return_value = VideoProbeResult(
            30,
            'h264',
            '.mp4',
        )

        self.adapter = Mock()
        self.factory.return_value = self.adapter

        self.adapter.new_key.side_effect = lambda **kw: (
            f'professional_videos/{kw["professional_profile_id"]}/'
            f'{uuid4().hex}{kw["extension"]}'
        )

        self.adapter.head.return_value = {
            'size_bytes': sample_mp4().size,
            'content_type': 'video/mp4',
        }

    def _upload(self, *, title='Demostración remota'):
        return create_professional_portfolio_video(
            self.owner,
            uploaded_file=sample_mp4(),
            title=title,
            description='Material sin pacientes identificables',
            category=(
                ProfessionalPortfolioVideo.Category.EXERCISES
            ),
            rights_confirmed=True,
        )

    def test_remote_upload_reserves_processing_quota_and_finishes_pending(self):
        observed = []

        def observe_upload(
            *,
            key,
            professional_profile_id,
            fileobj,
        ):
            video = ProfessionalPortfolioVideo.objects.get(
                external_asset_id=key,
            )

            observed.append(video.status)

            self.assertEqual(
                professional_profile_id,
                self.profile.pk,
            )

            self.assertTrue(
                fileobj.read(4),
            )

        self.adapter.upload.side_effect = observe_upload

        video = self._upload()

        self.assertEqual(
            observed,
            [ProfessionalPortfolioVideo.Status.PROCESSING],
        )

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
        )

        self.assertEqual(
            video.storage_backend,
            ProfessionalPortfolioVideo.StorageBackend.EXTERNAL,
        )

        self.assertFalse(video.video_file)
        self.assertEqual(video.duration_seconds, 30)
        self.assertEqual(video.file_size_bytes, sample_mp4().size)

        self.assertRegex(
            video.external_asset_id,
            (
                rf'^professional_videos/{self.profile.pk}/'
                rf'[0-9a-f]{{32}}\.mp4$'
            ),
        )

        self.adapter.head.assert_called_once()
        self.adapter.delete.assert_not_called()

    def test_failed_remote_upload_cleans_up_reservation_and_object(self):
        self.adapter.upload.side_effect = RuntimeError(
            'error S3 simulado',
        )

        with patch(
            'apps.professionals.video_upload_service_v13201.logger'
        ):
            with self.assertRaisesRegex(
                ValidationError,
                'No se pudo almacenar',
            ):
                self._upload()

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.exists(),
        )

        self.adapter.delete.assert_called_once()

    def test_remote_size_mismatch_cleans_up(self):
        self.adapter.head.return_value = {
            'size_bytes': 1,
            'content_type': 'video/mp4',
        }

        with self.assertRaisesRegex(
            ValidationError,
            'tamaño remoto',
        ):
            self._upload()

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.exists(),
        )

        self.adapter.delete.assert_called_once()

    def test_remote_content_type_mismatch_cleans_up(self):
        self.adapter.head.return_value = {
            'size_bytes': sample_mp4().size,
            'content_type': 'application/octet-stream',
        }

        with self.assertRaisesRegex(
            ValidationError,
            'formato remoto',
        ):
            self._upload()

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.exists(),
        )

        self.adapter.delete.assert_called_once()

    def test_quota_rejects_fourth_video_without_remote_transfer(self):
        for index in range(3):
            self._upload(
                title=f'Video remoto {index}',
            )

        with self.assertRaisesRegex(
            ValidationError,
            'máximo de 3',
        ):
            self._upload(
                title='Cuarto video remoto',
            )

        self.assertEqual(
            ProfessionalPortfolioVideo.objects.count(),
            3,
        )

        self.assertEqual(
            self.adapter.upload.call_count,
            3,
        )

    def test_duration_over_plan_quota_rejects_before_remote_transfer(self):
        self.probe.return_value = VideoProbeResult(
            121,
            'h264',
            '.mp4',
        )

        with self.assertRaisesRegex(
            ValidationError,
            'duración individual',
        ):
            self._upload()

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.exists(),
        )

        self.adapter.upload.assert_not_called()

    def test_deleted_processing_reservation_does_not_publish_video(self):

        def cancel_while_uploading(
            *,
            key,
            professional_profile_id,
            fileobj,
        ):
            ProfessionalPortfolioVideo.objects.filter(
                external_asset_id=key,
            ).delete()

        self.adapter.upload.side_effect = (
            cancel_while_uploading
        )

        with self.assertRaisesRegex(
            ValidationError,
            'cancelada',
        ):
            self._upload()

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.exists(),
        )

        self.adapter.delete.assert_called_once()