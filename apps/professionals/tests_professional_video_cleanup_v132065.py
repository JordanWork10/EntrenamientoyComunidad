"""
V132.06.5A - Pruebas de limpieza segura de videos.

Destino:
apps/professionals/tests_professional_video_cleanup_v132065.py

Todas las operaciones S3 se simulan.

NO utiliza credenciales reales.
NO sube archivos a Supabase.
NO elimina archivos del bucket real.

Comando:
python manage.py test apps.professionals.tests_professional_video_cleanup_v132065 --verbosity 2
"""

import os

from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalSpecialty,
    ProfessionalVideoStorageCleanup,
)

from .video_models_v13200 import ProfessionalPortfolioVideo

from .video_storage_cleanup_service_v132065 import (
    queue_remote_video_cleanup,
    run_pending_remote_video_cleanups,
    run_remote_video_cleanup,
)


FAKE_S3_ENV = {
    'SUPABASE_VIDEO_S3_BUCKET': 'portafolio-privado',
    'SUPABASE_VIDEO_S3_ENDPOINT': (
        'https://ejemplo.storage.supabase.co/storage/v1/s3'
    ),
    'SUPABASE_VIDEO_S3_REGION': 'sa-east-1',
    'SUPABASE_VIDEO_S3_ACCESS_KEY': 'clave-falsa',
    'SUPABASE_VIDEO_S3_SECRET_KEY': 'secreto-falso',
}


@override_settings(
    PROFESSIONAL_VIDEO_STORAGE_MODE='supabase'
)
class ProfessionalVideoCleanupTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.owner = User.objects.create_user(
            username='cleanup_owner_132065',
            email='cleanup_owner@example.test',
            password='test-pass',
        )

        cls.other = User.objects.create_user(
            username='cleanup_other_132065',
            email='cleanup_other@example.test',
            password='test-pass',
        )

        category = ProfessionalCategory.objects.create(
            name='Limpieza V132065',
            slug='limpieza-v132065',
        )

        specialty = ProfessionalSpecialty.objects.create(
            category=category,
            name='Portafolio V132065',
            slug='portafolio-v132065',
        )

        cls.profile = ProfessionalProfile.objects.create(
            user=cls.owner,
            category=category,
            specialty=specialty,
            verification_status=(
                ProfessionalProfile.VerificationStatus.VERIFIED
            ),
            bio='Perfil para pruebas de limpieza privada.',
        )

    def setUp(self):

        # Variables de ejemplo: nunca se utilizan
        # las credenciales reales de Supabase.
        env_patch = patch.dict(
            os.environ,
            FAKE_S3_ENV,
        )

        env_patch.start()
        self.addCleanup(env_patch.stop)

        # Evitamos que los errores simulados llenen
        # la consola con registros innecesarios.
        logger_patch = patch(
            'apps.professionals.'
            'video_storage_cleanup_service_v132065.logger'
        )

        logger_patch.start()
        self.addCleanup(logger_patch.stop)

        # Todas las operaciones del adaptador remoto
        # utilizan un objeto simulado.
        adapter_patch = patch(
            'apps.professionals.'
            'video_storage_cleanup_service_v132065.'
            'SupabaseVideoS3Adapter.from_settings'
        )

        adapter_factory = adapter_patch.start()
        self.addCleanup(adapter_patch.stop)

        self.adapter = Mock()

        self.adapter.bucket = (
            FAKE_S3_ENV['SUPABASE_VIDEO_S3_BUCKET']
        )

        adapter_factory.return_value = self.adapter

    def _video(
        self,
        *,
        backend=ProfessionalPortfolioVideo.StorageBackend.EXTERNAL,
    ):
        """
        Crea un video exclusivamente en la base de pruebas.
        """

        if (
            backend
            == ProfessionalPortfolioVideo.StorageBackend.EXTERNAL
        ):
            external_asset_id = (
                f'professional_videos/{self.profile.pk}/'
                + 'a' * 32
                + '.mp4'
            )
        else:
            external_asset_id = ''

        video = ProfessionalPortfolioVideo(
            professional_profile=self.profile,
            title='Video para eliminar',
            category=(
                ProfessionalPortfolioVideo.Category.PRESENTATION
            ),
            status=(
                ProfessionalPortfolioVideo.Status.PENDING_REVIEW
            ),
            storage_backend=backend,
            external_asset_id=external_asset_id,
            duration_seconds=12,
            file_size_bytes=1024,
            rights_confirmed=True,
        )

        video.full_clean()
        video.save()

        return video

    def _delete(self, video):
        """
        Ejecuta la ruta real de Django con el cliente de pruebas.
        """

        url = reverse(
            'professionals:portfolio_delete',
            args=[video.public_id],
        )

        return self.client.post(url)

    def test_owner_delete_creates_auditable_completed_task(self):
        """
        Una eliminación correcta debe registrar una tarea completada.
        """
        video = self._video()
        key = video.external_asset_id

        self.client.force_login(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._delete(video)

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

        task = ProfessionalVideoStorageCleanup.objects.get(
            remote_key=key
        )

        self.assertEqual(
            task.status,
            ProfessionalVideoStorageCleanup.Status.COMPLETED,
        )

        self.assertEqual(
            task.attempts,
            1,
        )

        self.assertIsNotNone(
            task.completed_at
        )

        self.adapter.delete.assert_called_once_with(
            key=key,
            professional_profile_id=self.profile.pk,
        )

    def test_s3_failure_preserves_task_and_retry_completes_it(self):
        """
        Si Supabase falla, se conserva la tarea.

        Un reintento posterior debe poder completarla.
        """
        video = self._video()

        self.adapter.delete.side_effect = RuntimeError(
            'S3 temporalmente caído'
        )

        self.client.force_login(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._delete(video)

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
            task.attempts,
            1,
        )

        self.assertEqual(
            task.last_error,
            'RuntimeError',
        )

        # Simular que la conexión con Supabase
        # vuelve a funcionar.
        self.adapter.delete.side_effect = None

        self.assertTrue(
            run_remote_video_cleanup(task.pk)
        )

        task.refresh_from_db()

        self.assertEqual(
            task.status,
            ProfessionalVideoStorageCleanup.Status.COMPLETED,
        )

        self.assertEqual(
            task.attempts,
            2,
        )

    def test_unverified_member_cannot_delete_someone_elses_video(self):
        """
        Un miembro sin el perfil correspondiente no puede eliminarlo.
        """
        video = self._video()

        self.client.force_login(self.other)

        response = self._delete(video)

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertTrue(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

        self.assertEqual(
            ProfessionalVideoStorageCleanup.objects.count(),
            0,
        )

        self.adapter.delete.assert_not_called()

    def test_local_video_deletion_does_not_create_remote_task(self):
        """
        Los videos locales no deben generar trabajos S3.
        """
        video = self._video(
            backend=(
                ProfessionalPortfolioVideo.StorageBackend.LOCAL
            )
        )

        self.client.force_login(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._delete(video)

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

        self.assertEqual(
            ProfessionalVideoStorageCleanup.objects.count(),
            0,
        )

    def test_same_key_is_not_enqueued_twice(self):
        """
        No se deben duplicar las tareas para un mismo objeto.
        """
        key = (
            f'professional_videos/{self.profile.pk}/'
            + 'b' * 32
            + '.webm'
        )

        first = queue_remote_video_cleanup(
            professional_profile_id=self.profile.pk,
            remote_key=key,
            reason=(
                ProfessionalVideoStorageCleanup.Reason.USER_DELETE
            ),
        )

        second = queue_remote_video_cleanup(
            professional_profile_id=self.profile.pk,
            remote_key=key,
            reason=(
                ProfessionalVideoStorageCleanup.Reason.USER_DELETE
            ),
        )

        self.assertEqual(
            first.pk,
            second.pk,
        )

        self.assertEqual(
            ProfessionalVideoStorageCleanup.objects.count(),
            1,
        )

    def test_different_bucket_does_not_delete_a_real_object(self):
        """
        Si cambia el bucket configurado, la tarea queda pendiente.
        """
        key = (
            f'professional_videos/{self.profile.pk}/'
            + 'c' * 32
            + '.mp4'
        )

        task = queue_remote_video_cleanup(
            professional_profile_id=self.profile.pk,
            remote_key=key,
            reason=(
                ProfessionalVideoStorageCleanup.Reason.USER_DELETE
            ),
        )

        with patch.dict(
            os.environ,
            {
                'SUPABASE_VIDEO_S3_BUCKET': 'otro-bucket'
            },
        ):
            self.assertFalse(
                run_remote_video_cleanup(task.pk)
            )

        task.refresh_from_db()

        self.assertEqual(
            task.status,
            ProfessionalVideoStorageCleanup.Status.PENDING,
        )

        self.adapter.delete.assert_not_called()

    def test_pending_batch_processes_only_pending_tasks(self):
        """
        El procesamiento por lotes debe completar solamente
        las tareas pendientes.
        """
        key = (
            f'professional_videos/{self.profile.pk}/'
            + 'd' * 32
            + '.mp4'
        )

        task = queue_remote_video_cleanup(
            professional_profile_id=self.profile.pk,
            remote_key=key,
            reason=(
                ProfessionalVideoStorageCleanup.Reason.FAILED_UPLOAD
            ),
        )

        result = run_pending_remote_video_cleanups(
            limit=10
        )

        self.assertEqual(
            result,
            {
                'processed': 1,
                'completed': 1,
                'failed': 0,
            },
        )

        task.refresh_from_db()

        self.assertEqual(
            task.status,
            ProfessionalVideoStorageCleanup.Status.COMPLETED,
        )

        result_again = run_pending_remote_video_cleanups(
            limit=10
        )

        self.assertEqual(
            result_again['processed'],
            0,
        )