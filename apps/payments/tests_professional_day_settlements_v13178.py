"""V131.78: seguridad y liquidaciones sandbox de jornadas profesionales.

python manage.py test apps.payments.tests_professional_day_settlements_v13178 --verbosity 2
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import (
    Booking,
    BookingSessionIncident,
    BookingSessionReview,
)
from apps.bookings.services import create_booking
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalSpecialty,
)

from .models import Payment, Settlement
from .services.professional_booking_payments import (
    approve_professional_booking_payment,
    cancel_professional_booking_with_refund,
    open_professional_booking_payment,
)
from .services.professional_day_settlements import (
    SettlementProcessingError,
    release_professional_day_hold,
    settle_professional_day_settlement,
    sync_professional_day_settlement,
)


@override_settings(PAYMENTS_SANDBOX=True)
class ProfessionalDaySettlementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.professional = User.objects.create_user(
            username='prof_v13178', email='prof_v13178@example.test', password='test',
        )
        self.member = User.objects.create_user(
            username='member_v13178', email='member_v13178@example.test', password='test',
        )
        self.admin = User.objects.create_superuser(
            username='admin_v13178', email='admin_v13178@example.test', password='test',
        )
        category = ProfessionalCategory.objects.create(
            name='Categoría V13178', slug='categoria-v13178',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Especialidad V13178', slug='especialidad-v13178',
            category=category,
        )
        self.profile = ProfessionalProfile.objects.create(
            user=self.professional,
            category=category,
            specialty=specialty,
            bio='Profesional verificado.',
            offers_online=True,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        self.service = ProfessionalService.objects.create(
            professional_profile=self.profile,
            name='Sesión de prueba 13178',
            description='Servicio individual.',
            mode=ProfessionalService.ServiceMode.ONLINE,
            duration_minutes=60,
            price=20000,
            publication_status=ProfessionalService.PublicationStatus.PUBLISHED,
        )
        self.day = timezone.localdate() + timedelta(days=14)
        ProfessionalServiceAvailability.objects.create(
            service=self.service,
            weekday=self.day.weekday(),
            start_time=time(9),
            end_time=time(12),
            valid_from=self.day,
            is_active=True,
        )
        self.booking = create_booking(
            user=self.member,
            service=self.service,
            session_date=self.day,
            start_time=time(9),
            end_time=time(10),
        )
        self.start = timezone.make_aware(
            datetime.combine(self.day, time(9)), timezone.get_current_timezone(),
        )
        self.end = self.start + timedelta(hours=1)
        self.eligible = self.end + timedelta(hours=25)

    def _approved(self):
        self.booking.status = Booking.Status.CONFIRMED
        self.booking.confirmed_at = timezone.now()
        self.booking.save(update_fields=['status', 'confirmed_at', 'updated_at'])
        payment = open_professional_booking_payment(self.booking.pk, self.member)
        snapshot = SimpleNamespace(
            plan_code='professional_base',
            commission_rate_percent=Decimal('12.00'),
        )
        with patch(
            'apps.payments.services.commissions.get_professional_commission_snapshot',
            return_value=snapshot,
        ):
            return approve_professional_booking_payment(
                payment.public_id, self.member,
                accepts_policy=True, accepts_sandbox=True,
            )

    def _sync_at(self, when):
        with patch(
            'apps.payments.services.professional_day_settlements.timezone.now',
            return_value=when,
        ):
            return sync_professional_day_settlement(self.professional, self.day)

    def _settle_at(self, settlement, when):
        with patch(
            'apps.payments.services.professional_day_settlements.timezone.now',
            return_value=when,
        ):
            return settle_professional_day_settlement(
                settlement, reviewed_by=self.admin,
            )

    def test_no_payment_cannot_prepare(self):
        with self.assertRaises(SettlementProcessingError):
            sync_professional_day_settlement(self.professional, self.day)
        self.assertEqual(Settlement.objects.count(), 0)

    def test_approved_payment_requires_completed_session(self):
        self._approved()
        settlement = self._sync_at(self.eligible)
        self.assertEqual(settlement.net_amount_clp, 17600)
        self.assertEqual(settlement.status, Settlement.Status.PENDING)
        with self.assertRaises(SettlementProcessingError):
            self._settle_at(settlement, self.eligible)

    def test_completed_session_waits_24h_and_can_be_liquidated_once(self):
        payment = self._approved()
        self.booking.status = Booking.Status.COMPLETED
        self.booking.save(update_fields=['status', 'updated_at'])
        pending = self._sync_at(self.end + timedelta(hours=23))
        self.assertEqual(pending.status, Settlement.Status.PENDING)
        with self.assertRaises(SettlementProcessingError):
            self._settle_at(pending, self.end + timedelta(hours=23))

        eligible = self._sync_at(self.eligible)
        self.assertEqual(eligible.pk, pending.pk)
        self.assertEqual(eligible.status, Settlement.Status.ELIGIBLE)
        settled = self._settle_at(eligible, self.eligible)
        self.assertEqual(settled.status, Settlement.Status.SETTLED)
        self.assertEqual(settled.settled_by, self.admin)
        self.assertEqual(settled.net_amount_clp, 17600)
        self.assertEqual(self._settle_at(settled, self.eligible).pk, settled.pk)
        payment.refresh_from_db()
        self.assertEqual(payment.settlement_status, Payment.SettlementStatus.SETTLED)
        self.assertEqual(Settlement.objects.count(), 1)

    def test_partial_refund_retained_amount_is_paid_after_session_end(self):
        payment = self._approved()
        outcome = cancel_professional_booking_with_refund(
            self.booking.pk, self.member,
            by_professional=False,
            reason='Cancelación con 36 horas de anticipación.',
            cancelled_at=self.start - timedelta(hours=36),
        )
        self.assertEqual(outcome.refund.amount_clp, 15000)
        pending = self._sync_at(self.end + timedelta(hours=12))
        self.assertEqual(pending.net_amount_clp, 4400)
        self.assertEqual(pending.refunded_amount_clp, 15000)
        self.assertEqual(pending.commission_amount_clp, 600)
        self.assertEqual(pending.status, Settlement.Status.PENDING)

        eligible = self._sync_at(self.eligible)
        self.assertEqual(eligible.status, Settlement.Status.ELIGIBLE)
        self._settle_at(eligible, self.eligible)
        payment.refresh_from_db()
        self.assertEqual(payment.settlement_status, Payment.SettlementStatus.SETTLED)

    def test_full_refund_keeps_history_but_cannot_pay(self):
        self._approved()
        cancel_professional_booking_with_refund(
            self.booking.pk, self.member,
            by_professional=False,
            reason='Cancelación anticipada de prueba.',
            cancelled_at=self.start - timedelta(hours=60),
        )
        settlement = self._sync_at(self.eligible)
        self.assertEqual(settlement.refunded_amount_clp, 20000)
        self.assertEqual(settlement.net_amount_clp, 0)
        self.assertEqual(settlement.status, Settlement.Status.PENDING)
        with self.assertRaises(SettlementProcessingError):
            self._settle_at(settlement, self.eligible)

    def test_two_sessions_same_professional_and_day_share_one_settlement(self):
        first = self._approved()
        other_member = get_user_model().objects.create_user(
            username='other_v13178', email='other_v13178@example.test',
            password='test',
        )
        second_booking = create_booking(
            user=other_member, service=self.service,
            session_date=self.day, start_time=time(10), end_time=time(11),
        )
        second_booking.status = Booking.Status.CONFIRMED
        second_booking.confirmed_at = timezone.now()
        second_booking.save(update_fields=['status', 'confirmed_at', 'updated_at'])
        second_payment = open_professional_booking_payment(
            second_booking.pk, other_member,
        )
        with patch(
            'apps.payments.services.commissions.get_professional_commission_snapshot',
            return_value=SimpleNamespace(
                plan_code='professional_base',
                commission_rate_percent=Decimal('12.00'),
            ),
        ):
            second_payment = approve_professional_booking_payment(
                second_payment.public_id, other_member,
                accepts_policy=True, accepts_sandbox=True,
            )
        first_settlement = self._sync_at(self.eligible + timedelta(hours=1))
        second_settlement = self._sync_at(self.eligible + timedelta(hours=1))
        self.assertEqual(first_settlement.pk, second_settlement.pk)
        self.assertEqual(first_settlement.gross_amount_clp, 40000)
        self.assertEqual(first_settlement.commission_amount_clp, 4800)
        self.assertEqual(first_settlement.net_amount_clp, 35200)
        first.refresh_from_db()
        second_payment.refresh_from_db()
        self.assertEqual(first.settlement_id, first_settlement.pk)
        self.assertEqual(second_payment.settlement_id, first_settlement.pk)
        self.assertEqual(Settlement.objects.count(), 1)

    def test_open_incident_places_jornada_on_hold(self):
        self._approved()
        self.booking.status = Booking.Status.COMPLETED
        self.booking.save(update_fields=['status', 'updated_at'])
        review = BookingSessionReview.objects.create(
            booking=self.booking,
            status=BookingSessionReview.Status.REPORTED,
            expires_at=self.end + timedelta(hours=24),
            issue_reason='La sesión no se realizó correctamente.',
        )
        incident = BookingSessionIncident.objects.create(
            review=review,
            status=BookingSessionIncident.Status.OPEN,
        )
        held = self._sync_at(self.eligible)
        self.assertEqual(held.status, Settlement.Status.ON_HOLD)
        with self.assertRaises(SettlementProcessingError):
            self._settle_at(held, self.eligible)

        incident.status = BookingSessionIncident.Status.RESOLVED
        incident.resolution_type = BookingSessionIncident.Resolution.SERVICE_CONFIRMED
        incident.resolution_summary = 'Sesión comprobada por la administración.'
        incident.save()
        with patch(
            'apps.payments.services.professional_day_settlements.timezone.now',
            return_value=self.eligible,
        ):
            released = release_professional_day_hold(held, reviewed_by=self.admin)
        self.assertEqual(released.status, Settlement.Status.ELIGIBLE)

    def test_member_cannot_settle_even_if_eligible(self):
        self._approved()
        self.booking.status = Booking.Status.COMPLETED
        self.booking.save(update_fields=['status', 'updated_at'])
        settlement = self._sync_at(self.eligible)
        with self.assertRaises(SettlementProcessingError):
            settle_professional_day_settlement(
                settlement, reviewed_by=self.member,
            )

    def test_get_admin_does_not_create_settlement_and_member_is_forbidden(self):
        self._approved()
        url = reverse('payments:professional_day_settlement_admin')
        self.client.force_login(self.member)
        denied = self.client.get(url)
        self.assertEqual(denied.status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Jornadas económicas')
        self.assertEqual(Settlement.objects.count(), 0)

    def test_post_requires_confirmation_before_close(self):
        self._approved()
        self.booking.status = Booking.Status.COMPLETED
        self.booking.save(update_fields=['status', 'updated_at'])
        settlement = self._sync_at(self.eligible)
        self.client.force_login(self.admin)
        url = reverse('payments:professional_day_settlement_close', args=[settlement.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, Settlement.Status.ELIGIBLE)

    @override_settings(PAYMENTS_SANDBOX=False)
    def test_outside_sandbox_is_forbidden(self):
        url = reverse('payments:professional_day_settlement_admin')
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 404)
