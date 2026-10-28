"""V131.68: pruebas aisladas, no crean base de datos.

Ejecutar:
    python manage.py test apps.payments.tests_space_policy_v13168 --verbosity 2
"""

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.spaces.models import SpaceBooking

from .models import SpaceCancellationRequest
from .services.space_cancellations import _can_automate_member_cancellation
from .services.space_policy import (
    SPACE_POLICY_VERSION,
    calculate_space_member_cancellation,
)


class SpaceCancellationPolicyTests(SimpleTestCase):
    def setUp(self):
        self.start = timezone.make_aware(
            datetime(2026, 11, 9, 9, 0), timezone.get_current_timezone(),
        )

    def decide(self, hours, *, amount=18000, paid_hours_before=None):
        cancelled = self.start - timedelta(hours=hours)
        paid_at = (
            cancelled - timedelta(hours=paid_hours_before)
            if paid_hours_before is not None else None
        )
        return calculate_space_member_cancellation(
            amount,
            self.start,
            cancelled_at=cancelled,
            paid_at=paid_at,
        )

    def test_full_refund_at_exactly_48_hours(self):
        result = self.decide(48)
        self.assertEqual(result.refund_amount_clp, 18000)
        self.assertEqual(result.refund_percent, Decimal('100'))

    def test_just_under_48_hours_is_half_not_full(self):
        result = self.decide(48 - 1 / 3600)
        self.assertEqual(result.refund_amount_clp, 9000)

    def test_exactly_24_hours_is_half(self):
        self.assertEqual(self.decide(24).refund_amount_clp, 9000)

    def test_under_24_hours_is_zero(self):
        result = self.decide(23.99)
        self.assertEqual(result.refund_amount_clp, 0)
        self.assertEqual(result.retained_amount_clp, 18000)

    def test_two_hour_grace_refunds_full_when_service_is_at_least_24h_away(self):
        result = self.decide(36, paid_hours_before=2)
        self.assertEqual(result.bucket, 'grace_after_payment')
        self.assertEqual(result.refund_amount_clp, 18000)

    def test_grace_does_not_apply_to_last_minute_service(self):
        self.assertEqual(
            self.decide(23.5, paid_hours_before=0.1).refund_amount_clp, 0,
        )

    def test_grace_expires_after_two_hours(self):
        self.assertEqual(
            self.decide(36, paid_hours_before=2.01).refund_amount_clp, 9000,
        )

    def test_half_refund_rounds_in_clp(self):
        self.assertEqual(
            self.decide(36, amount=18001).refund_amount_clp, 9001,
        )

    def test_service_started_cannot_be_cancelled_automatically(self):
        with self.assertRaises(ValueError):
            self.decide(0)

    def test_payment_must_have_explicit_snapshot_and_approval(self):
        role = SpaceCancellationRequest.RequestedRole.MEMBER
        payment = SimpleNamespace(
            policy_version=SPACE_POLICY_VERSION,
            policy_accepted_at=None,
            approved_at=timezone.now(),
        )
        self.assertFalse(_can_automate_member_cancellation(role, payment))
        payment.policy_accepted_at = timezone.now()
        self.assertTrue(_can_automate_member_cancellation(role, payment))
        payment.policy_version = 'LEGACY_PRE_POLICY'
        self.assertFalse(_can_automate_member_cancellation(role, payment))

    def test_provider_request_cannot_enter_member_automation(self):
        payment = SimpleNamespace(
            policy_version=SPACE_POLICY_VERSION,
            policy_accepted_at=timezone.now(),
            approved_at=timezone.now(),
        )
        self.assertFalse(_can_automate_member_cancellation(
            SpaceCancellationRequest.RequestedRole.PROVIDER, payment,
        ))


class VoluntaryCancelledSlotTests(SimpleTestCase):
    def test_member_block_uses_same_space_day_and_time_overlap(self):
        with patch('apps.spaces.models.SpaceBooking.objects.filter') as lookup:
            lookup.return_value.filter.return_value.exists.return_value = True
            blocked = SpaceBooking.member_cancelled_overlapping_slot(
                member_id=22,
                space_id=7,
                session_date=datetime(2026, 11, 9).date(),
                start_time=datetime(2026, 11, 9, 9).time(),
                end_time=datetime(2026, 11, 9, 10).time(),
            )
            self.assertTrue(blocked)
            self.assertEqual(lookup.call_args.kwargs['booked_by_id'], 22)
            self.assertEqual(lookup.call_args.kwargs['space_id'], 7)
            self.assertEqual(lookup.call_args.kwargs['start_time__lt'].hour, 10)
            self.assertEqual(lookup.call_args.kwargs['end_time__gt'].hour, 9)

