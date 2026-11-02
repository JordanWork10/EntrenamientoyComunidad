"""V132.00: regresión de cuotas para videos demostrativos profesionales.

Destino: apps/professionals/tests_professional_video_quota_v13200.py
Comando:
python manage.py test apps.professionals.tests_professional_video_quota_v13200 --verbosity 2
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.subscriptions.models import SubscriptionPlan, UserSubscription

from .models import ProfessionalCategory, ProfessionalProfile, ProfessionalSpecialty
from .professional_video_quota_v13200 import (
    BASIC_QUOTA,
    NO_ACCESS,
    PRO_QUOTA,
    MEGABYTE,
    get_professional_video_quota,
    validate_professional_video_upload,
)


class ProfessionalVideoQuotaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        User = get_user_model()
        cls.owner = User.objects.create_user(
            username='video_owner_13200',
            email='video_owner_13200@example.test',
            password='test-pass',
        )
        cls.pending_owner = User.objects.create_user(
            username='video_pending_13200',
            email='video_pending_13200@example.test',
            password='test-pass',
        )
        category = ProfessionalCategory.objects.create(
            name='Entrenamiento V13200', slug='entrenamiento-v13200',
        )
        specialty = ProfessionalSpecialty.objects.create(
            category=category, name='Entrenamiento guiado', slug='guiado-v13200',
        )
        for user, status in (
            (cls.owner, ProfessionalProfile.VerificationStatus.VERIFIED),
            (cls.pending_owner, ProfessionalProfile.VerificationStatus.PENDING),
        ):
            ProfessionalProfile.objects.create(
                user=user,
                category=category,
                specialty=specialty,
                verification_status=status,
                bio='Prueba de portafolio profesional.',
            )

    def _plan(self, code):
        return SubscriptionPlan.objects.create(
            code=code,
            name=f'Plan {code}',
            monthly_price_clp=14990,
            intro_price_clp=11990,
        )

    def _subscribe(self, code, *, status=UserSubscription.Status.ACTIVE,
                   period_end=None):
        plan = self._plan(code)
        period_end = period_end or (self.now + timedelta(days=20))
        return UserSubscription.objects.create(
            user=self.owner,
            plan=plan,
            status=status,
            started_at=self.now,
            trial_started_at=self.now if status == UserSubscription.Status.TRIAL else None,
            trial_ends_at=period_end if status == UserSubscription.Status.TRIAL else None,
            current_period_start=self.now,
            current_period_end=period_end,
        )

    def test_verified_professional_without_subscription_has_basic_quota(self):
        self.assertEqual(get_professional_video_quota(self.owner), BASIC_QUOTA)

    def test_unverified_professional_cannot_upload(self):
        self.assertEqual(get_professional_video_quota(self.pending_owner), NO_ACCESS)

    def test_professional_pro_gets_pro_quota(self):
        self._subscribe(SubscriptionPlan.Code.PROFESSIONAL_PRO)
        self.assertEqual(get_professional_video_quota(self.owner), PRO_QUOTA)

    def test_integral_gets_pro_quota(self):
        self._subscribe(SubscriptionPlan.Code.PRO_INTEGRAL)
        self.assertEqual(get_professional_video_quota(self.owner), PRO_QUOTA)

    def test_member_plus_does_not_grant_pro_video_capacity(self):
        self._subscribe(SubscriptionPlan.Code.MEMBER_PLUS)
        self.assertEqual(get_professional_video_quota(self.owner), BASIC_QUOTA)

    def test_spaces_pro_does_not_grant_professional_video_capacity(self):
        self._subscribe(SubscriptionPlan.Code.SPACES_PRO)
        self.assertEqual(get_professional_video_quota(self.owner), BASIC_QUOTA)

    def test_trial_pro_grants_pro_quota_until_expiry(self):
        self._subscribe(
            SubscriptionPlan.Code.PROFESSIONAL_PRO,
            status=UserSubscription.Status.TRIAL,
        )
        self.assertEqual(get_professional_video_quota(self.owner), PRO_QUOTA)

    def test_cancel_at_period_end_keeps_benefits_until_period_end(self):
        self._subscribe(
            SubscriptionPlan.Code.PROFESSIONAL_PRO,
            status=UserSubscription.Status.CANCEL_AT_PERIOD_END,
        )
        self.assertEqual(get_professional_video_quota(self.owner), PRO_QUOTA)

    def test_expired_trial_returns_basic_quota(self):
        self._subscribe(
            SubscriptionPlan.Code.PROFESSIONAL_PRO,
            status=UserSubscription.Status.TRIAL,
            period_end=self.now - timedelta(days=1),
        )
        self.assertEqual(get_professional_video_quota(self.owner), BASIC_QUOTA)

    def test_pending_payment_does_not_grant_pro_capacity(self):
        self._subscribe(
            SubscriptionPlan.Code.PROFESSIONAL_PRO,
            status=UserSubscription.Status.PAST_DUE,
        )
        self.assertEqual(get_professional_video_quota(self.owner), BASIC_QUOTA)

    def test_expired_active_subscription_does_not_grant_pro_capacity(self):
        self._subscribe(
            SubscriptionPlan.Code.PROFESSIONAL_PRO,
            period_end=self.now - timedelta(days=1),
        )
        self.assertEqual(get_professional_video_quota(self.owner), BASIC_QUOTA)

    def test_valid_basic_video_can_be_added(self):
        quota = validate_professional_video_upload(
            self.owner, duration_seconds=120, file_size_bytes=50 * MEGABYTE,
            existing_count=2, existing_total_seconds=240,
        )
        self.assertEqual(quota, BASIC_QUOTA)

    def test_pro_can_add_twentieth_video_on_limit(self):
        self._subscribe(SubscriptionPlan.Code.PROFESSIONAL_PRO)
        quota = validate_professional_video_upload(
            self.owner,
            duration_seconds=300,
            file_size_bytes=200 * MEGABYTE,
            existing_count=19,
            existing_total_seconds=5700,
        )
        self.assertEqual(quota, PRO_QUOTA)

    def test_basic_video_count_limit_is_enforced(self):
        with self.assertRaisesRegex(ValidationError, 'máximo de 3'):
            validate_professional_video_upload(
                self.owner, duration_seconds=30, file_size_bytes=MEGABYTE,
                existing_count=3, existing_total_seconds=120,
            )

    def test_basic_video_duration_limit_is_enforced(self):
        with self.assertRaisesRegex(ValidationError, 'duración individual'):
            validate_professional_video_upload(
                self.owner, duration_seconds=121, file_size_bytes=MEGABYTE,
                existing_count=0, existing_total_seconds=0,
            )

    def test_total_duration_limit_is_enforced(self):
        with self.assertRaisesRegex(ValidationError, 'duración total'):
            validate_professional_video_upload(
                self.owner, duration_seconds=120, file_size_bytes=MEGABYTE,
                existing_count=2, existing_total_seconds=300,
            )

    def test_file_size_limit_is_enforced(self):
        with self.assertRaisesRegex(ValidationError, 'tamaño máximo'):
            validate_professional_video_upload(
                self.owner, duration_seconds=60,
                file_size_bytes=101 * MEGABYTE,
                existing_count=0, existing_total_seconds=0,
            )

    def test_unverified_user_is_rejected_on_upload(self):
        with self.assertRaisesRegex(ValidationError, 'perfil profesional verificado'):
            validate_professional_video_upload(
                self.pending_owner, duration_seconds=60,
                file_size_bytes=MEGABYTE,
                existing_count=0, existing_total_seconds=0,
            )

    def test_zero_duration_cannot_be_used_to_evade_limits(self):
        with self.assertRaisesRegex(ValidationError, 'duración'):
            validate_professional_video_upload(
                self.owner, duration_seconds=0,
                file_size_bytes=MEGABYTE,
                existing_count=0, existing_total_seconds=0,
            )
