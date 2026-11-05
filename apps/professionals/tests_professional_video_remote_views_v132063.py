"""
V132.06.5A - Pruebas de vistas de Supabase con S3 simulado.

Destino:
apps/professionals/tests_professional_video_remote_views_v132063.py

Verifica:
- Privacidad del streaming.
- Acceso autorizado.
- Reproducción parcial mediante Range.
- Aprobación administrativa.
- Eliminación segura con tareas persistentes.
- Compatibilidad con videos locales.

No utiliza credenciales reales ni accede a Supabase.
"""

import os
import tempfile

from io import BytesIO
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalSpecialty,
    ProfessionalVideoStorageCleanup,
)

from .video_models_v13200 import ProfessionalPortfolioVideo
from .video_storage_v13201 import PrivatePortfolioStorage


FAKE_S3_ENV = {
    'SUPABASE_VIDEO_S3_BUCKET': 'portafolio-privado',
    'SUPABASE_VIDEO_S3_ENDPOINT': (
        'https://ejemplo.storage.supabase.co/storage/v1/s3'
    ),
    'SUPABASE_VIDEO_S3_REGION': 'us-east-1',
    'SUPABASE_VIDEO_S3_ACCESS_KEY': 'clave-falsa',
    'SUPABASE_VIDEO_S3_SECRET_KEY': 'secreto-falso',
}

DATA = b'1234567890abcde'


@override_settings(
    PROFESSIONAL_VIDEO_STORAGE_MODE='supabase'
)
class ProfessionalVideoRemoteViewsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.owner = User.objects.create_user(
            username='video_remote_views_owner_132063',
            email='video_remote_views_owner@example.test',
            password='test-pass',
        )

        cls.member = User.objects.create_user(
            username='video_remote_views_member_132063',
            email='video_remote_views_member@example.test',
            password='test-pass',
        )

        cls.admin = User.objects.create_user(
            username='video_remote_views_admin_132063',
            email='video_remote_views_admin@example.test',
            password='test-pass',
            is_staff=True,
        )

        category = ProfessionalCategory.objects.create(
            name='Vistas remotas V132063',
            slug='vistas-remotas-v132063',
        )

        specialty = ProfessionalSpecialty.objects.create(
            category=category,
            name='Video remoto',
            slug='video-remoto-v132063',
        )

        cls.profile = ProfessionalProfile.objects.create(
            user=cls.owner,
            category=category,
            specialty=specialty,
            bio='Perfil remoto de prueba',
            verification_status=(
                ProfessionalProfile.VerificationStatus.VERIFIED
            ),
            is_public=True,
        )

    def setUp(self):
        self.env = patch.dict(
            os.environ,
            FAKE_S3_ENV,
        )

        self.env.start()
        self.addCleanup(self.env.stop)

        # Adaptador S3 completamente simulado.
        self.adapter_patch = patch(
            'apps.professionals.video_views_v13202.'
            'SupabaseVideoS3Adapter.from_settings'
        )

        self.adapter_factory = self.adapter_patch.start()
        self.addCleanup(self.adapter_patch.stop)

        self.adapter = Mock()

        # El nuevo servicio de limpieza verifica el bucket.
        self.adapter.bucket = (
            FAKE_S3_ENV['SUPABASE_VIDEO_S3_BUCKET']
        )

        self.adapter_factory.return_value = self.adapter

        self.adapter.head.return_value = {
            'size_bytes': len(DATA),
            'content_type': 'video/mp4',
        }

        def get_object(**kwargs):
            requested = kwargs.get('byte_range')

            if requested:
                numbers = (
                    requested.removeprefix('bytes=').split('-')
                )

                start = int(numbers[0])
                end = int(numbers[1])

                return {
                    'Body': BytesIO(
                        DATA[start:end + 1]
                    ),
                    'ContentLength': end - start + 1,
                    'ContentRange': (
                        f'bytes {start}-{end}/{len(DATA)}'
                    ),
                }

            return {
                'Body': BytesIO(DATA),
                'ContentLength': len(DATA),
            }

        self.adapter.get.side_effect = get_object

    def _video(
        self,
        status=ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
    ):
        video = ProfessionalPortfolioVideo(
            professional_profile=self.profile,
            title='Video remoto de prueba',
            category=(
                ProfessionalPortfolioVideo.Category.EXERCISES
            ),
            status=status,
            storage_backend=(
                ProfessionalPortfolioVideo.StorageBackend.EXTERNAL
            ),
            external_asset_id=(
                f'professional_videos/{self.profile.pk}/'
                + 'a' * 32
                + '.mp4'
            ),
            duration_seconds=30,
            file_size_bytes=len(DATA),
            rights_confirmed=True,
        )

        video.full_clean()
        video.save()

        return video

    def _stream_url(self, video):
        return reverse(
            'professionals:portfolio_stream',
            args=[video.public_id],
        )

    def test_pending_video_is_private_but_owner_can_stream(self):
        video = self._video()
        url = self._stream_url(video)

        self.assertEqual(
            self.client.get(url).status_code,
            404,
        )

        self.adapter.head.assert_not_called()

        self.client.force_login(self.owner)

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            b''.join(response.streaming_content),
            DATA,
        )

        self.assertEqual(
            response['Cache-Control'],
            'private, no-store',
        )

    def test_published_video_can_stream_without_public_storage_url(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        response = self.client.get(
            self._stream_url(video)
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            b''.join(response.streaming_content),
            DATA,
        )

        self.assertEqual(
            response['Content-Length'],
            str(len(DATA)),
        )

        self.assertNotIn(
            'storage.supabase.co',
            str(response.headers),
        )

    def test_hidden_professional_blocks_public_stream(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        self.profile.is_public = False

        self.profile.save(
            update_fields=['is_public']
        )

        self.assertEqual(
            self.client.get(
                self._stream_url(video)
            ).status_code,
            404,
        )

        self.adapter.head.assert_not_called()

    def test_range_stream_uses_s3_range_and_returns_206(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        response = self.client.get(
            self._stream_url(video),
            HTTP_RANGE='bytes=2-5',
        )

        self.assertEqual(
            response.status_code,
            206,
        )

        self.assertEqual(
            response['Content-Range'],
            'bytes 2-5/15',
        )

        self.assertEqual(
            b''.join(response.streaming_content),
            b'3456',
        )

        self.adapter.get.assert_called_once_with(
            key=video.external_asset_id,
            professional_profile_id=self.profile.pk,
            byte_range='bytes=2-5',
        )

    def test_invalid_range_does_not_download_s3_object(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        response = self.client.get(
            self._stream_url(video),
            HTTP_RANGE='bytes=99-100',
        )

        self.assertEqual(
            response.status_code,
            416,
        )

        self.assertEqual(
            response['Content-Range'],
            'bytes */15',
        )

        self.adapter.get.assert_not_called()

    def test_admin_can_approve_verified_remote_video(self):
        video = self._video()

        self.client.force_login(self.admin)

        response = self.client.post(
            reverse(
                'professionals:portfolio_review_decide',
                args=[video.public_id],
            ),
            {
                'decision': 'approve',
                'notes': '',
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.APPROVED,
        )

        self.assertIsNotNone(
            video.published_at
        )

        self.adapter.head.assert_called_once()

    def test_admin_cannot_approve_remote_video_with_changed_size(self):
        video = self._video()

        self.adapter.head.return_value = {
            'size_bytes': len(DATA) + 1,
            'content_type': 'video/mp4',
        }

        self.client.force_login(self.admin)

        self.client.post(
            reverse(
                'professionals:portfolio_review_decide',
                args=[video.public_id],
            ),
            {
                'decision': 'approve',
                'notes': '',
            },
        )

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
        )

    def test_admin_reject_does_not_require_remote_access(self):
        video = self._video()

        self.client.force_login(self.admin)

        self.client.post(
            reverse(
                'professionals:portfolio_review_decide',
                args=[video.public_id],
            ),
            {
                'decision': 'reject',
                'notes': 'Material no autorizado.',
            },
        )

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.REJECTED,
        )

        self.adapter.head.assert_not_called()

    def test_owner_delete_creates_completed_remote_cleanup_task(self):
        """
        Una eliminación correcta debe dejar una tarea completada.
        """
        video = self._video()

        self.client.force_login(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse(
                    'professionals:portfolio_delete',
                    args=[video.public_id],
                )
            )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

        task = ProfessionalVideoStorageCleanup.objects.get()

        self.assertEqual(
            task.remote_key,
            video.external_asset_id,
        )

        self.assertEqual(
            task.status,
            ProfessionalVideoStorageCleanup.Status.COMPLETED,
        )

        self.assertEqual(
            task.attempts,
            1,
        )

        self.adapter.delete.assert_called_once_with(
            key=video.external_asset_id,
            professional_profile_id=self.profile.pk,
        )

    def test_other_member_cannot_delete_remote_video(self):
        video = self._video()

        self.client.force_login(self.member)

        response = self.client.post(
            reverse(
                'professionals:portfolio_delete',
                args=[video.public_id],
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertTrue(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

        self.assertFalse(
            ProfessionalVideoStorageCleanup.objects.exists()
        )

        self.adapter.delete.assert_not_called()

    def test_remote_delete_keeps_cleanup_task_when_storage_is_unavailable(
        self,
    ):
        """
        Si Supabase falla, el registro del video puede retirarse,
        pero la tarea de limpieza debe permanecer pendiente.
        """
        video = self._video()

        self.adapter_factory.side_effect = ImproperlyConfigured(
            'S3 desconectado'
        )

        self.client.force_login(self.owner)

        with patch(
            'apps.professionals.'
            'video_storage_cleanup_service_v132065.logger'
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse(
                        'professionals:portfolio_delete',
                        args=[video.public_id],
                    )
                )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

        task = ProfessionalVideoStorageCleanup.objects.get()

        self.assertEqual(
            task.status,
            ProfessionalVideoStorageCleanup.Status.PENDING,
        )

        self.assertEqual(
            task.reason,
            ProfessionalVideoStorageCleanup.Reason.USER_DELETE,
        )

        self.assertEqual(
            task.attempts,
            1,
        )

        self.adapter.delete.assert_not_called()

    def test_wrong_s3_content_range_is_rejected_and_stream_closed(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        body = BytesIO(b'3456')

        self.adapter.get.side_effect = None

        self.adapter.get.return_value = {
            'Body': body,
            'ContentLength': 4,
            'ContentRange': 'bytes 0-3/15',
        }

        with patch(
            'apps.professionals.video_views_v13202.logger'
        ):
            response = self.client.get(
                self._stream_url(video),
                HTTP_RANGE='bytes=2-5',
            )

        self.assertEqual(
            response.status_code,
            404,
        )

        self.assertTrue(body.closed)

    def test_s3_read_failure_never_exposes_internal_exception(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        self.adapter.get.side_effect = RuntimeError(
            'S3 privado secreto'
        )

        with patch(
            'apps.professionals.video_views_v13202.logger'
        ):
            response = self.client.get(
                self._stream_url(video)
            )

        self.assertEqual(
            response.status_code,
            404,
        )

        self.assertNotIn(
            'S3 privado secreto',
            response.content.decode(),
        )

    def test_legacy_local_video_still_streams_when_remote_mode_is_configured(
        self,
    ):
        """
        Comprueba que los videos locales antiguos sigan accesibles
        aunque el modo activo sea Supabase.
        """
        with tempfile.TemporaryDirectory() as directory:

            with override_settings(
                PROFESSIONAL_VIDEO_PRIVATE_ROOT=directory
            ):

                field = (
                    ProfessionalPortfolioVideo
                    ._meta
                    .get_field('video_file')
                )

                old_storage = field.storage
                field.storage = PrivatePortfolioStorage()

                try:
                    video = ProfessionalPortfolioVideo(
                        professional_profile=self.profile,
                        title='Video anterior local',
                        category=(
                            ProfessionalPortfolioVideo.Category.EXERCISES
                        ),
                        status=(
                            ProfessionalPortfolioVideo.Status.APPROVED
                        ),
                        storage_backend=(
                            ProfessionalPortfolioVideo.StorageBackend.LOCAL
                        ),
                        duration_seconds=30,
                        file_size_bytes=len(DATA),
                        rights_confirmed=True,
                    )

                    video.video_file.save(
                        'local.mp4',
                        ContentFile(DATA),
                        save=False,
                    )

                    video.full_clean()
                    video.save()

                    response = self.client.get(
                        self._stream_url(video)
                    )

                    self.assertEqual(
                        response.status_code,
                        200,
                    )

                    self.assertEqual(
                        b''.join(response.streaming_content),
                        DATA,
                    )

                    self.adapter_factory.assert_not_called()

                finally:
                    field.storage = old_storage