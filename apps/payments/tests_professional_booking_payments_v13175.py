"""V131.75: pagos sandbox y reembolsos de sesiones profesionales.

python manage.py test apps.payments.tests_professional_booking_payments_v13175 --verbosity 2
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.bookings.models import Booking
from apps.bookings.services import create_booking, get_available_slots
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalSpecialty,
)

from .models import Payment, Refund
from .services.professional_booking_payments import (
    ProfessionalBookingPaymentError,
    approve_professional_booking_payment,
    cancel_professional_booking_with_refund,
    close_pending_professional_payment,
    open_professional_booking_payment,
)


@override_settings(PAYMENTS_SANDBOX=True)
class ProfessionalBookingPaymentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.professional = User.objects.create_user(
            username='profesional_v13175',
            email='profesional_v13175@example.test',
            password='test',
        )
        self.member = User.objects.create_user(
            username='miembro_v13175',
            email='miembro_v13175@example.test',
            password='test',
        )
        self.other_member = User.objects.create_user(
            username='otro_miembro_v13175',
            email='otro_miembro_v13175@example.test',
            password='test',
        )
        category = ProfessionalCategory.objects.create(
            name='Entrenamientos individuales V13175',
            slug='individuales-v13175',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Sesiones individuales V13175',
            slug='sesiones-individuales-v13175',
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
            name='Sesión online personalizada',
            description='Sesión pagada de prueba.',
            mode=ProfessionalService.ServiceMode.ONLINE,
            duration_minutes=60,
            price=20000,
            publication_status=ProfessionalService.PublicationStatus.PUBLISHED,
        )
        self.day = timezone.localdate() + timedelta(days=14)
        self.start = timezone.make_aware(
            datetime.combine(self.day, time(9, 0)),
            timezone.get_current_timezone(),
        )
        ProfessionalServiceAvailability.objects.create(
            service=self.service,
            weekday=self.day.weekday(),
            start_time=time(9, 0),
            end_time=time(12, 0),
            valid_from=self.day,
            is_active=True,
        )
        self.booking = create_booking(
            user=self.member,
            service=self.service,
            session_date=self.day,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

    def accept_booking(self):
        self.booking.status = Booking.Status.CONFIRMED
        self.booking.confirmed_at = timezone.now()
        self.booking.save()

    def open_and_approve(self):
        self.accept_booking()
        payment = open_professional_booking_payment(
            self.booking.pk, self.member,
        )
        snapshot = SimpleNamespace(
            plan_code='professional_base',
            commission_rate_percent=Decimal('12.00'),
        )
        with patch(
            'apps.payments.services.commissions.get_professional_commission_snapshot',
            return_value=snapshot,
        ):
            payment = approve_professional_booking_payment(
                payment.public_id,
                self.member,
                accepts_policy=True,
                accepts_sandbox=True,
            )
        return payment

    def test_pending_booking_cannot_open_payment(self):
        with self.assertRaises(ProfessionalBookingPaymentError):
            open_professional_booking_payment(self.booking.pk, self.member)

    def test_member_cannot_open_payment_of_another_member(self):
        self.accept_booking()
        with self.assertRaises(Booking.DoesNotExist):
            open_professional_booking_payment(
                self.booking.pk, self.other_member,
            )

    def test_checkout_reuses_pending_attempt(self):
        self.accept_booking()
        first = open_professional_booking_payment(self.booking.pk, self.member)
        second = open_professional_booking_payment(self.booking.pk, self.member)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Payment.objects.count(), 1)

    def test_sandbox_approval_registers_commission_and_policy(self):
        payment = self.open_and_approve()
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.APPROVED)
        self.assertEqual(payment.commission_base_clp, 20000)
        self.assertEqual(payment.commission_amount_clp, 2400)
        self.assertEqual(payment.net_amount_clp, 17600)
        self.assertIsNotNone(payment.policy_accepted_at)
        self.assertIsNotNone(payment.settlement_eligible_at)

    def test_approval_is_idempotent(self):
        payment = self.open_and_approve()
        again = approve_professional_booking_payment(
            payment.public_id, self.member,
        )
        self.assertEqual(payment.pk, again.pk)
        self.assertEqual(Payment.objects.count(), 1)

    def test_policy_must_be_accepted_before_approval(self):
        self.accept_booking()
        payment = open_professional_booking_payment(self.booking.pk, self.member)
        with self.assertRaises(ProfessionalBookingPaymentError):
            approve_professional_booking_payment(
                payment.public_id, self.member, accepts_sandbox=True,
            )
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)

    def test_failed_attempt_does_not_cancel_booking(self):
        self.accept_booking()
        payment = open_professional_booking_payment(self.booking.pk, self.member)
        close_pending_professional_payment(
            payment.public_id, self.member, rejected=True,
        )
        self.booking.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(payment.status, Payment.Status.FAILED)

    def test_member_cancellation_before_48h_refunds_full_amount(self):
        payment = self.open_and_approve()
        outcome = cancel_professional_booking_with_refund(
            self.booking.pk,
            self.member,
            by_professional=False,
            reason='No podré asistir a la sesión.',
            cancelled_at=self.start - timedelta(hours=60),
        )
        payment.refresh_from_db()
        self.assertEqual(outcome.refund.amount_clp, 20000)
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertEqual(payment.net_amount_clp, 0)
        self.assertEqual(outcome.booking.status, Booking.Status.CANCELLED)

    def test_member_cancellation_at_36h_refunds_75_percent(self):
        payment = self.open_and_approve()
        outcome = cancel_professional_booking_with_refund(
            self.booking.pk,
            self.member,
            by_professional=False,
            reason='Cambio de disponibilidad personal.',
            cancelled_at=self.start - timedelta(hours=36),
        )
        payment.refresh_from_db()
        self.assertEqual(outcome.refund.amount_clp, 15000)
        self.assertEqual(payment.status, Payment.Status.PARTIALLY_REFUNDED)
        self.assertEqual(payment.commission_base_clp, 5000)
        self.assertEqual(payment.commission_amount_clp, 600)
        self.assertEqual(payment.net_amount_clp, 4400)

    def test_member_cancellation_at_12h_refunds_50_percent(self):
        payment = self.open_and_approve()
        outcome = cancel_professional_booking_with_refund(
            self.booking.pk,
            self.member,
            by_professional=False,
            reason='Imprevisto familiar de última hora.',
            cancelled_at=self.start - timedelta(hours=12),
        )
        payment.refresh_from_db()
        self.assertEqual(outcome.refund.amount_clp, 10000)
        self.assertEqual(payment.net_amount_clp, 8800)

    def test_professional_cancellation_refunds_all_and_blocks_slot(self):
        payment = self.open_and_approve()
        outcome = cancel_professional_booking_with_refund(
            self.booking.pk,
            self.professional,
            by_professional=True,
            reason='No podré atender por un problema de disponibilidad.',
            cancelled_at=self.start - timedelta(hours=12),
        )
        payment.refresh_from_db()
        self.assertEqual(outcome.refund.amount_clp, 20000)
        self.assertEqual(outcome.refund.reason, Refund.Reason.PROFESSIONAL_CANCELLATION)
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertNotIn(
            time(9, 0),
            [slot['start_time'] for slot in get_available_slots(self.service, self.day)],
        )

    def test_settled_payment_is_not_automatically_refunded(self):
        payment = self.open_and_approve()
        payment.settlement_status = Payment.SettlementStatus.SETTLED
        payment.save(update_fields=['settlement_status'])

        with self.assertRaises(ProfessionalBookingPaymentError):
            cancel_professional_booking_with_refund(
                self.booking.pk,
                self.member,
                by_professional=False,
                reason='No podré asistir a la sesión.',
            )
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertFalse(Refund.objects.filter(payment=payment).exists())

    def test_member_cancelling_unpaid_booking_only_closes_booking(self):
        outcome = cancel_professional_booking_with_refund(
            self.booking.pk,
            self.member,
            by_professional=False,
            reason='No podré asistir a esta sesión.',
        )
        self.assertIsNone(outcome.payment)
        self.assertIsNone(outcome.refund)
        self.assertEqual(outcome.booking.status, Booking.Status.CANCELLED)
