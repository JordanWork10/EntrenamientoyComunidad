"""Destino: apps/professionals/tests_professional_video_views_v13202.py

python manage.py test apps.professionals.tests_professional_video_views_v13202 --verbosity 2

Estas pruebas requieren agregar include('apps.professionals.video_urls_v13202')
en el urlpatterns existente de apps/professionals/urls.py.
"""

import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ProfessionalCategory, ProfessionalProfile, ProfessionalSpecialty
from .video_models_v13200 import ProfessionalPortfolioVideo
from .video_probe_v13201 import VideoProbeResult
from .video_storage_v13201 import PrivatePortfolioStorage


class ProfessionalVideoViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(
            username='video_view_owner_13202',
            email='video_view_owner_13202@example.test',
            password='test-pass',
        )
        cls.other = User.objects.create_user(
            username='video_view_other_13202',
            email='video_view_other_13202@example.test',
            password='test-pass',
        )
        cls.admin = User.objects.create_user(
            username='video_view_admin_13202',
            email='video_view_admin_13202@example.test',
            password='test-pass',
            is_staff=True,
        )
        category = ProfessionalCategory.objects.create(
            name='Portafolio vistas V13202', slug='portafolio-vistas-v13202',
        )
        specialty = ProfessionalSpecialty.objects.create(
            category=category, name='Clases online V13202',
            slug='clases-online-v13202',
        )
        cls.profile = ProfessionalProfile.objects.create(
            user=cls.owner, category=category, specialty=specialty,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
            bio='Prueba de vista de portafolio.',
        )

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.storage_settings = override_settings(
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=self.temp_directory.name,
        )
        self.storage_settings.enable()
        self.field = ProfessionalPortfolioVideo._meta.get_field('video_file')
        self.original_storage = self.field.storage
        self.field.storage = PrivatePortfolioStorage()

    def tearDown(self):
        self.field.storage = self.original_storage
        self.storage_settings.disable()
        self.temp_directory.cleanup()

    def _video(self, status=ProfessionalPortfolioVideo.Status.PENDING_REVIEW):
        video = ProfessionalPortfolioVideo(
            professional_profile=self.profile,
            title='Video de ejemplo',
            category=ProfessionalPortfolioVideo.Category.EXERCISES,
            status=status,
            duration_seconds=30,
            file_size_bytes=15,
            rights_confirmed=True,
        )
        video.video_file.save(
            'ejemplo.mp4',
            ContentFile(b'1234567890abcde'),
            save=False,
        )
        video.full_clean()
        video.save()
        return video

    def test_guest_must_sign_in_to_manager(self):
        response = self.client.get(reverse('professionals:portfolio_manager'))
        self.assertEqual(response.status_code, 302)

    def test_regular_member_cannot_manage_professional_videos(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('professionals:portfolio_manager'))
        self.assertEqual(response.status_code, 403)

    def test_verified_owner_can_open_manager(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('professionals:portfolio_manager'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mis videos profesionales')

    def test_member_cannot_open_admin_review_queue(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('professionals:portfolio_review_queue'))
        self.assertEqual(response.status_code, 403)

    def test_staff_can_open_admin_review_queue(self):
        self._video()
        self.client.force_login(self.admin)
        response = self.client.get(reverse('professionals:portfolio_review_queue'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Video de ejemplo')

    def test_pending_video_is_not_public_but_owner_can_preview(self):
        video = self._video()
        url = reverse('professionals:portfolio_stream', args=[video.public_id])

        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.owner)
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Consumir completamente el stream permite al cliente de pruebas
        # cerrar el archivo sin cerrar la conexión PostgreSQL del TestCase.
        self.assertEqual(
            b''.join(response.streaming_content),
            b'1234567890abcde',
        )

    def test_approved_video_is_public_only_for_public_profile(self):
        video = self._video(status=ProfessionalPortfolioVideo.Status.APPROVED)
        url = reverse('professionals:portfolio_stream', args=[video.public_id])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b''.join(response.streaming_content),
            b'1234567890abcde',
        )

        self.profile.is_public = False
        self.profile.save(update_fields=['is_public'])

        self.assertEqual(self.client.get(url).status_code, 404)

    def test_range_request_returns_partial_video(self):
        video = self._video(status=ProfessionalPortfolioVideo.Status.APPROVED)
        url = reverse('professionals:portfolio_stream', args=[video.public_id])

        response = self.client.get(url, HTTP_RANGE='bytes=2-5')

        # Consumir el generador libera el archivo de video.
        content = b''.join(response.streaming_content)

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response['Content-Range'], 'bytes 2-5/15')
        self.assertEqual(content, b'3456')

    def test_owner_cannot_delete_video_from_another_account(self):
        video = self._video()
        self.client.force_login(self.other)

        url = reverse('professionals:portfolio_delete', args=[video.public_id])

        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(
            ProfessionalPortfolioVideo.objects.filter(pk=video.pk).exists()
        )

    def test_owner_can_delete_video(self):
        video = self._video()
        self.client.force_login(self.owner)

        url = reverse('professionals:portfolio_delete', args=[video.public_id])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ProfessionalPortfolioVideo.objects.filter(pk=video.pk).exists()
        )

    def test_admin_reject_requires_explanation(self):
        video = self._video()
        self.client.force_login(self.admin)

        url = reverse(
            'professionals:portfolio_review_decide',
            args=[video.public_id],
        )
        self.client.post(url, {'decision': 'reject', 'notes': ''})

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
        )

    def test_admin_can_approve_video(self):
        video = self._video()
        self.client.force_login(self.admin)

        url = reverse(
            'professionals:portfolio_review_decide',
            args=[video.public_id],
        )
        response = self.client.post(
            url,
            {'decision': 'approve', 'notes': ''},
        )

        self.assertEqual(response.status_code, 302)

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.APPROVED,
        )
        self.assertIsNotNone(video.published_at)

    @patch('apps.professionals.video_upload_service_v13201.probe_local_video')
    def test_owner_can_submit_video_for_review(self, probe):
        probe.return_value = VideoProbeResult(30, 'h264', '.mp4')

        uploaded = SimpleUploadedFile(
            'muestra.mp4',
            b'\x00\x00\x00\x18ftypisom' + b'0' * 100,
            content_type='video/mp4',
        )

        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('professionals:portfolio_manager'),
            {
                'title': 'Nueva demostración',
                'category': ProfessionalPortfolioVideo.Category.EXERCISES,
                'description': 'Prueba sin personas',
                'video': uploaded,
                'rights_confirmed': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ProfessionalPortfolioVideo.objects.filter(
                title='Nueva demostración',
                status=ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
            ).exists()
        )