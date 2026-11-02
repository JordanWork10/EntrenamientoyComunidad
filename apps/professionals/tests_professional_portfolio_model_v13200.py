"""V132.00 — destino: apps/professionals/tests_professional_portfolio_model_v13200.py.

python manage.py test apps.professionals.tests_professional_portfolio_model_v13200 --verbosity 2
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import ProfessionalCategory, ProfessionalProfile, ProfessionalSpecialty
from .video_models_v13200 import ProfessionalPortfolioVideo


class ProfessionalPortfolioVideoModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        user = User.objects.create_user(
            username='portfolio_owner_13200',
            email='portfolio_owner_13200@example.test',
            password='test-pass',
        )
        category = ProfessionalCategory.objects.create(
            name='Portafolio V13200', slug='portafolio-v13200',
        )
        specialty = ProfessionalSpecialty.objects.create(
            category=category,
            name='Portafolio profesional',
            slug='portafolio-profesional-v13200',
        )
        cls.profile = ProfessionalProfile.objects.create(
            user=user,
            category=category,
            specialty=specialty,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            bio='Prueba del portafolio de videos.',
        )

    def _approved_video(self, **overrides):
        values = {
            'professional_profile': self.profile,
            'title': 'Rutina demostrativa',
            'status': ProfessionalPortfolioVideo.Status.APPROVED,
            'storage_backend': ProfessionalPortfolioVideo.StorageBackend.EXTERNAL,
            'external_asset_id': 'video-demo-test-13200',
            'duration_seconds': 70,
            'file_size_bytes': 5000000,
            'rights_confirmed': True,
        }
        values.update(overrides)
        video = ProfessionalPortfolioVideo(**values)
        video.full_clean()
        video.save()
        return video

    def test_new_video_is_draft_and_not_public(self):
        video = ProfessionalPortfolioVideo.objects.create(
            professional_profile=self.profile,
            title='Mi presentación',
        )
        self.assertEqual(video.status, ProfessionalPortfolioVideo.Status.DRAFT)
        self.assertFalse(video.rights_confirmed)
        self.assertFalse(video.is_featured)

    def test_approved_video_requires_real_media(self):
        with self.assertRaises(ValidationError):
            self._approved_video(external_asset_id='', video_file='')

    def test_approved_video_requires_publication_rights(self):
        with self.assertRaises(ValidationError):
            self._approved_video(rights_confirmed=False)

    def test_approved_video_requires_verified_metadata(self):
        with self.assertRaises(ValidationError):
            self._approved_video(duration_seconds=None)

    def test_valid_approved_video_is_accessible_on_profile_relation(self):
        video = self._approved_video()
        self.assertIn(video, self.profile.portfolio_videos.all())
        self.assertEqual(
            ProfessionalPortfolioVideo.objects.filter(
                status=ProfessionalPortfolioVideo.Status.APPROVED,
            ).count(), 1,
        )

    def test_only_one_approved_featured_video_per_professional(self):
        self._approved_video(is_featured=True)
        # full_clean puede detectar el conflicto antes de llegar a la BD;
        # si no, PostgreSQL lo bloquea mediante la restricción única.
        with self.assertRaises((ValidationError, IntegrityError)):
            with transaction.atomic():
                self._approved_video(
                    title='Segundo destacado',
                    external_asset_id='otro-asset',
                    is_featured=True,
                )

    def test_multiple_draft_videos_can_be_featured_before_review(self):
        for number in range(2):
            ProfessionalPortfolioVideo.objects.create(
                professional_profile=self.profile,
                title=f'Borrador {number}',
                is_featured=True,
            )
        self.assertEqual(self.profile.portfolio_videos.count(), 2)
