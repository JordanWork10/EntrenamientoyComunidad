"""V132.04: pruebas de seguridad del portafolio audiovisual.

Destino: apps/professionals/tests_professional_video_security_v13204.py

Ejecutar:
python manage.py test apps.professionals.tests_professional_video_security_v13204 --verbosity 2
"""

import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ProfessionalCategory, ProfessionalProfile, ProfessionalSpecialty
from .video_models_v13200 import ProfessionalPortfolioVideo
from .video_storage_v13201 import PrivatePortfolioStorage


VIDEO_CONTENT = b'0123456789abcde'


class ProfessionalVideoSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.owner = User.objects.create_user(
            username='security_video_owner_13204',
            password='test-pass',
            email='security_video_owner_13204@example.test',
        )

        cls.other_professional = User.objects.create_user(
            username='security_video_other_13204',
            password='test-pass',
            email='security_video_other_13204@example.test',
        )

        cls.member = User.objects.create_user(
            username='security_video_member_13204',
            password='test-pass',
            email='security_video_member_13204@example.test',
        )

        cls.admin = User.objects.create_user(
            username='security_video_admin_13204',
            password='test-pass',
            email='security_video_admin_13204@example.test',
            is_staff=True,
        )

        category = ProfessionalCategory.objects.create(
            name='Seguridad video V13204',
            slug='seguridad-video-v13204',
        )

        specialty = ProfessionalSpecialty.objects.create(
            category=category,
            name='Video demostrativo seguro',
            slug='video-demostrativo-seguro-v13204',
        )

        cls.profile = ProfessionalProfile.objects.create(
            user=cls.owner,
            category=category,
            specialty=specialty,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
            bio='Perfil usado en pruebas de seguridad.',
        )

        cls.other_profile = ProfessionalProfile.objects.create(
            user=cls.other_professional,
            category=category,
            specialty=specialty,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
            bio='Segundo perfil para verificar aislamiento.',
        )

    def setUp(self):
        self.private_directory = tempfile.TemporaryDirectory()

        self.storage_override = override_settings(
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=self.private_directory.name,
        )
        self.storage_override.enable()

        self.video_field = ProfessionalPortfolioVideo._meta.get_field('video_file')
        self.original_storage = self.video_field.storage
        self.video_field.storage = PrivatePortfolioStorage()

    def tearDown(self):
        self.video_field.storage = self.original_storage
        self.storage_override.disable()
        self.private_directory.cleanup()

    def _video(
        self,
        status=ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
    ):
        video = ProfessionalPortfolioVideo(
            professional_profile=self.profile,
            title='Prueba privada de seguridad',
            category=ProfessionalPortfolioVideo.Category.EXERCISES,
            status=status,
            duration_seconds=15,
            file_size_bytes=len(VIDEO_CONTENT),
            rights_confirmed=True,
        )

        video.video_file.save(
            'seguridad.mp4',
            ContentFile(VIDEO_CONTENT),
            save=False,
        )

        video.full_clean()
        video.save()
        return video

    @staticmethod
    def _stream_url(video):
        return reverse(
            'professionals:portfolio_stream',
            args=[video.public_id],
        )

    @staticmethod
    def _delete_url(video):
        return reverse(
            'professionals:portfolio_delete',
            args=[video.public_id],
        )

    @staticmethod
    def _review_url(video):
        return reverse(
            'professionals:portfolio_review_decide',
            args=[video.public_id],
        )

    def test_anonymous_user_cannot_access_private_management(self):
        video = self._video()

        self.assertEqual(
            self.client.get(
                reverse('professionals:portfolio_manager')
            ).status_code,
            302,
        )

        self.assertEqual(
            self.client.get(
                reverse('professionals:portfolio_review_queue')
            ).status_code,
            302,
        )

        self.assertEqual(
            self.client.post(self._delete_url(video)).status_code,
            302,
        )

        self.assertTrue(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

    def test_member_cannot_manage_or_review_videos(self):
        video = self._video()
        self.client.force_login(self.member)

        self.assertEqual(
            self.client.get(
                reverse('professionals:portfolio_manager')
            ).status_code,
            403,
        )

        self.assertEqual(
            self.client.get(
                reverse('professionals:portfolio_review_queue')
            ).status_code,
            403,
        )

        response = self.client.post(
            self._review_url(video),
            {
                'decision': 'approve',
                'notes': '',
            },
        )

        self.assertEqual(response.status_code, 403)

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
        )

    def test_all_unpublished_states_are_private_to_anonymous_users(self):
        statuses = (
            ProfessionalPortfolioVideo.Status.DRAFT,
            ProfessionalPortfolioVideo.Status.PROCESSING,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
            ProfessionalPortfolioVideo.Status.REJECTED,
            ProfessionalPortfolioVideo.Status.HIDDEN,
        )

        for status in statuses:
            with self.subTest(status=status):
                video = self._video(status)

                self.assertEqual(
                    self.client.get(
                        self._stream_url(video)
                    ).status_code,
                    404,
                )

    def test_non_owner_cannot_preview_pending_video(self):
        video = self._video()
        self.client.force_login(self.other_professional)

        self.assertEqual(
            self.client.get(
                self._stream_url(video)
            ).status_code,
            404,
        )

    def test_other_verified_professional_cannot_delete_video(self):
        video = self._video()
        self.client.force_login(self.other_professional)

        self.assertEqual(
            self.client.post(
                self._delete_url(video)
            ).status_code,
            404,
        )

        self.assertTrue(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

    def test_owner_can_preview_pending_but_cannot_moderate(self):
        video = self._video()
        self.client.force_login(self.owner)

        response = self.client.get(self._stream_url(video))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b''.join(response.streaming_content),
            VIDEO_CONTENT,
        )

        self.assertEqual(
            self.client.post(
                self._review_url(video),
                {
                    'decision': 'approve',
                    'notes': '',
                },
            ).status_code,
            403,
        )

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
        )

    def test_staff_can_preview_pending_but_cannot_delete_as_owner(self):
        video = self._video()
        self.client.force_login(self.admin)

        response = self.client.get(self._stream_url(video))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b''.join(response.streaming_content),
            VIDEO_CONTENT,
        )

        self.assertEqual(
            self.client.post(
                self._delete_url(video)
            ).status_code,
            403,
        )

        self.assertTrue(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

    def test_only_approved_video_from_public_verified_profile_is_public(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        response = self.client.get(self._stream_url(video))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b''.join(response.streaming_content),
            VIDEO_CONTENT,
        )

        self.profile.is_public = False
        self.profile.save(update_fields=['is_public'])

        self.assertEqual(
            self.client.get(
                self._stream_url(video)
            ).status_code,
            404,
        )

        self.profile.is_public = True
        self.profile.verification_status = (
            ProfessionalProfile.VerificationStatus.PENDING
        )

        self.profile.save(
            update_fields=[
                'is_public',
                'verification_status',
            ]
        )

        self.assertEqual(
            self.client.get(
                self._stream_url(video)
            ).status_code,
            404,
        )

    def test_moderator_cannot_approve_unverified_professional(self):
        video = self._video()

        self.profile.verification_status = (
            ProfessionalProfile.VerificationStatus.PENDING
        )

        self.profile.save(
            update_fields=['verification_status']
        )

        self.client.force_login(self.admin)

        response = self.client.post(
            self._review_url(video),
            {
                'decision': 'approve',
                'notes': '',
            },
        )

        self.assertEqual(response.status_code, 302)

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
        )

    def test_reject_requires_reason_and_saves_it(self):
        video = self._video()
        self.client.force_login(self.admin)

        self.client.post(
            self._review_url(video),
            {
                'decision': 'reject',
                'notes': '   ',
            },
        )

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
        )

        self.client.post(
            self._review_url(video),
            {
                'decision': 'reject',
                'notes': 'Se requiere autorización de imagen.',
            },
        )

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.REJECTED,
        )

        self.assertEqual(
            video.review_notes,
            'Se requiere autorización de imagen.',
        )

        self.assertIsNone(video.published_at)

        self.client.logout()

        self.assertEqual(
            self.client.get(
                self._stream_url(video)
            ).status_code,
            404,
        )

    def test_review_cannot_change_a_decision_twice(self):
        video = self._video()
        self.client.force_login(self.admin)

        self.client.post(
            self._review_url(video),
            {
                'decision': 'approve',
                'notes': '',
            },
        )

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.APPROVED,
        )

        self.client.post(
            self._review_url(video),
            {
                'decision': 'reject',
                'notes': 'Cambio posterior indebido.',
            },
        )

        video.refresh_from_db()

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.APPROVED,
        )

    def test_get_requests_cannot_delete_or_moderate(self):
        video = self._video()

        self.client.force_login(self.owner)

        self.assertEqual(
            self.client.get(
                self._delete_url(video)
            ).status_code,
            405,
        )

        self.client.force_login(self.admin)

        self.assertEqual(
            self.client.get(
                self._review_url(video)
            ).status_code,
            405,
        )

        self.assertTrue(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

    def test_deleted_video_removes_record_and_private_file(self):
        video = self._video()

        file_name = video.video_file.name
        storage = video.video_file.storage

        self.assertTrue(storage.exists(file_name))

        self.client.force_login(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self._delete_url(video)
            )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            ProfessionalPortfolioVideo.objects.filter(
                pk=video.pk
            ).exists()
        )

        self.assertFalse(storage.exists(file_name))

    def test_missing_file_is_not_served_even_if_approved(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        video.video_file.storage.delete(
            video.video_file.name
        )

        self.assertEqual(
            self.client.get(
                self._stream_url(video)
            ).status_code,
            404,
        )

    def test_partial_video_requests_obey_valid_range(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        cases = (
            ('bytes=2-5', 'bytes 2-5/15', b'2345'),
            ('bytes=10-', 'bytes 10-14/15', b'abcde'),
            ('bytes=-4', 'bytes 11-14/15', b'bcde'),
        )

        for range_header, expected_range, expected_content in cases:
            with self.subTest(range=range_header):
                response = self.client.get(
                    self._stream_url(video),
                    HTTP_RANGE=range_header,
                )

                self.assertEqual(response.status_code, 206)

                self.assertEqual(
                    response['Content-Range'],
                    expected_range,
                )

                self.assertEqual(
                    b''.join(response.streaming_content),
                    expected_content,
                )

    def test_invalid_video_ranges_are_rejected(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        invalid_ranges = (
            'bytes=100-',
            'bytes=-0',
            'bytes=5-4',
            'bytes=1-2,4-5',
            'invalid',
        )

        for range_header in invalid_ranges:
            with self.subTest(range=range_header):
                response = self.client.get(
                    self._stream_url(video),
                    HTTP_RANGE=range_header,
                )

                self.assertEqual(response.status_code, 416)

                self.assertEqual(
                    response['Content-Range'],
                    'bytes */15',
                )

    def test_stream_response_has_safe_headers(self):
        video = self._video(
            ProfessionalPortfolioVideo.Status.APPROVED
        )

        response = self.client.get(
            self._stream_url(video)
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response['Content-Type'],
            'video/mp4',
        )

        self.assertEqual(
            response['Accept-Ranges'],
            'bytes',
        )

        self.assertEqual(
            response['X-Content-Type-Options'],
            'nosniff',
        )

        self.assertIn(
            'no-store',
            response['Cache-Control'],
        )

        self.assertEqual(
            response['Content-Disposition'],
            'inline',
        )

        self.assertEqual(
            b''.join(response.streaming_content),
            VIDEO_CONTENT,
        )