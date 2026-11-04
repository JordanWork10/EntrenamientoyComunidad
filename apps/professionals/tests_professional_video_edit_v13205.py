"""V132.05: permisos y edición de metadatos de videos pendientes.

Destino: apps/professionals/tests_professional_video_edit_v13205.py

Ejecutar:
python manage.py test apps.professionals.tests_professional_video_edit_v13205 --verbosity 2
"""

import tempfile
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ProfessionalCategory, ProfessionalProfile, ProfessionalSpecialty
from .video_models_v13200 import ProfessionalPortfolioVideo
from .video_storage_v13201 import PrivatePortfolioStorage


class ProfessionalVideoMetadataEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.owner = User.objects.create_user(
            username='edit_video_owner_v13205',
            password='test-pass',
            email='edit_video_owner_v13205@example.test',
        )

        cls.other = User.objects.create_user(
            username='edit_video_other_v13205',
            password='test-pass',
            email='edit_video_other_v13205@example.test',
        )

        cls.member = User.objects.create_user(
            username='edit_video_member_v13205',
            password='test-pass',
            email='edit_video_member_v13205@example.test',
        )

        cls.admin = User.objects.create_user(
            username='edit_video_admin_v13205',
            password='test-pass',
            email='edit_video_admin_v13205@example.test',
            is_staff=True,
        )

        category = ProfessionalCategory.objects.create(
            name='Edición video V13205',
            slug='edicion-video-v13205',
        )

        specialty = ProfessionalSpecialty.objects.create(
            category=category,
            name='Ejercicios V13205',
            slug='ejercicios-v13205',
        )

        cls.profile = ProfessionalProfile.objects.create(
            user=cls.owner,
            category=category,
            specialty=specialty,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
            bio='Profesional de prueba.',
        )

        ProfessionalProfile.objects.create(
            user=cls.other,
            category=category,
            specialty=specialty,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
            bio='Otro profesional de prueba.',
        )

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()

        self.override_storage = override_settings(
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=self.temp_directory.name,
        )
        self.override_storage.enable()

        self.field = ProfessionalPortfolioVideo._meta.get_field('video_file')
        self.original_storage = self.field.storage
        self.field.storage = PrivatePortfolioStorage()

    def tearDown(self):
        self.field.storage = self.original_storage
        self.override_storage.disable()
        self.temp_directory.cleanup()

    def _video(
        self,
        status=ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
    ):
        video = ProfessionalPortfolioVideo(
            professional_profile=self.profile,
            title='Nombre original',
            category=ProfessionalPortfolioVideo.Category.PRESENTATION,
            description='Descripción original',
            status=status,
            duration_seconds=12,
            file_size_bytes=15,
            rights_confirmed=True,
        )

        video.video_file.save(
            'edicion.mp4',
            ContentFile(b'0123456789abcde'),
            save=False,
        )

        video.full_clean()
        video.save()

        return video

    @staticmethod
    def _url(video):
        return reverse(
            'professionals:portfolio_edit',
            args=[video.public_id],
        )

    @staticmethod
    def _valid_data(**overrides):
        values = {
            'title': 'Título actualizado',
            'category': ProfessionalPortfolioVideo.Category.EDUCATIONAL,
            'description': 'Nueva explicación educativa.',
        }

        values.update(overrides)
        return values

    def test_guest_must_sign_in(self):
        video = self._video()

        self.assertEqual(
            self.client.get(self._url(video)).status_code,
            302,
        )

        self.assertEqual(
            self.client.post(
                self._url(video),
                self._valid_data(),
            ).status_code,
            302,
        )

    def test_verified_owner_can_open_edit_form(self):
        video = self._video()
        self.client.force_login(self.owner)

        response = self.client.get(self._url(video))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Editar información del video')
        self.assertContains(response, 'Nombre original')

    def test_edit_updates_only_metadata_and_keeps_video_pending(self):
        video = self._video()

        original_file = video.video_file.name
        original_seconds = video.duration_seconds
        original_size = video.file_size_bytes

        self.client.force_login(self.owner)

        response = self.client.post(
            self._url(video),
            self._valid_data(),
        )

        self.assertRedirects(
            response,
            reverse('professionals:portfolio_manager'),
        )

        video.refresh_from_db()

        self.assertEqual(video.title, 'Título actualizado')

        self.assertEqual(
            video.category,
            ProfessionalPortfolioVideo.Category.EDUCATIONAL,
        )

        self.assertEqual(
            video.description,
            'Nueva explicación educativa.',
        )

        self.assertEqual(
            video.status,
            ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
        )

        self.assertEqual(video.video_file.name, original_file)
        self.assertTrue(video.video_file.storage.exists(original_file))
        self.assertEqual(video.duration_seconds, original_seconds)
        self.assertEqual(video.file_size_bytes, original_size)

    def test_invalid_form_keeps_original_metadata(self):
        video = self._video()
        self.client.force_login(self.owner)

        response = self.client.post(
            self._url(video),
            self._valid_data(
                title='    ',
                category='categoria_inventada',
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'errorlist')

        video.refresh_from_db()

        self.assertEqual(video.title, 'Nombre original')

        self.assertEqual(
            video.category,
            ProfessionalPortfolioVideo.Category.PRESENTATION,
        )

    def test_other_verified_professional_cannot_edit(self):
        video = self._video()
        self.client.force_login(self.other)

        self.assertEqual(
            self.client.get(self._url(video)).status_code,
            404,
        )

        self.assertEqual(
            self.client.post(
                self._url(video),
                self._valid_data(),
            ).status_code,
            404,
        )

        video.refresh_from_db()
        self.assertEqual(video.title, 'Nombre original')

    def test_member_and_staff_without_professional_profile_cannot_edit(self):
        video = self._video()

        for user in (self.member, self.admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)

                self.assertEqual(
                    self.client.get(self._url(video)).status_code,
                    403,
                )

                self.assertEqual(
                    self.client.post(
                        self._url(video),
                        self._valid_data(),
                    ).status_code,
                    403,
                )

    def test_approved_and_rejected_videos_are_immutable(self):
        self.client.force_login(self.owner)

        for status in (
            ProfessionalPortfolioVideo.Status.APPROVED,
            ProfessionalPortfolioVideo.Status.REJECTED,
        ):
            with self.subTest(status=status):
                video = self._video(status)

                self.assertEqual(
                    self.client.get(self._url(video)).status_code,
                    403,
                )

                self.assertEqual(
                    self.client.post(
                        self._url(video),
                        self._valid_data(),
                    ).status_code,
                    403,
                )

                video.refresh_from_db()
                self.assertEqual(video.title, 'Nombre original')

    def test_owner_loses_edit_permission_if_verification_removed(self):
        video = self._video()

        self.profile.verification_status = (
            ProfessionalProfile.VerificationStatus.PENDING
        )

        self.profile.save(
            update_fields=['verification_status']
        )

        self.client.force_login(self.owner)

        self.assertEqual(
            self.client.get(self._url(video)).status_code,
            403,
        )

        self.assertEqual(
            self.client.post(
                self._url(video),
                self._valid_data(),
            ).status_code,
            403,
        )

    def test_forged_or_nonexistent_video_id_is_not_found(self):
        self.client.force_login(self.owner)

        url = reverse(
            'professionals:portfolio_edit',
            args=[uuid4()],
        )

        self.assertEqual(
            self.client.get(url).status_code,
            404,
        )