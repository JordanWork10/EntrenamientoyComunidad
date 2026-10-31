"""Pruebas de la base económica para sesiones profesionales individuales.

python manage.py test apps.payments.tests_professional_payment_origin_v13174 --verbosity 2
"""

from datetime import time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.bookings.models import Booking
from apps.bookings.services import create_booking
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalSpecialty,
)

from .models import Payment
from .services.commissions import apply_payment_commission_snapshot


class ProfessionalPaymentOriginTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.professional = User.objects.create_user(
            username='prof_v13174_payment',
            email='prof_v13174_payment@example.test',
            password='test',
        )
        self.member = User.objects.create_user(
            username='member_v13174_payment',
            email='member_v13174_payment@example.test',
            password='test',
        )
        self.stranger = User.objects.create_user(
            username='stranger_v13174_payment',
            email='stranger_v13174_payment@example.test',
            password='test',
        )

        category = ProfessionalCategory.objects.create(
            name='Servicios de ensayo V13174',
            slug='servicios-ensayo-v13174',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Sesión de prueba V13174',
            slug='sesion-prueba-v13174',
            category=category,
        )
        profile = ProfessionalProfile.objects.create(
            user=self.professional,
            category=category,
            specialty=specialty,
            bio='Perfil de pruebas económicas.',
            offers_online=True,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        self.service = ProfessionalService.objects.create(
            professional_profile=profile,
            name='Sesión individual pagada',
            description='Servicio de prueba económica.',
            mode=ProfessionalService.ServiceMode.ONLINE,
            duration_minutes=60,
            price=20000,
            publication_status=ProfessionalService.PublicationStatus.PUBLISHED,
        )
        day = timezone.localdate() + timedelta(days=14)
        ProfessionalServiceAvailability.objects.create(
            service=self.service,
            weekday=day.weekday(),
            start_time=time(9, 0),
            end_time=time(12, 0),
            valid_from=day,
            is_active=True,
        )
        self.booking = create_booking(
            user=self.member,
            service=self.service,
            session_date=day,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

    def make_payment(self, **changes):
        values = {
            'payer': self.member,
            'professional_booking': self.booking,
            'economic_scope': Payment.EconomicScope.PROFESSIONAL_SERVICE,
            'amount_clp': self.booking.price_clp,
            'status': Payment.Status.PENDING,
        }
        values.update(changes)
        return Payment(**values)

    def test_valid_professional_booking_payment_preserves_booking_snapshot(self):
        payment = self.make_payment()
        payment.full_clean()
        payment.save()

        self.assertEqual(payment.professional_booking_id, self.booking.pk)
        self.assertIsNone(payment.activity_id)
        self.assertIsNone(payment.space_booking_id)
        self.assertEqual(payment.amount_clp, 20000)

    def test_payment_without_any_origin_is_invalid(self):
        payment = self.make_payment(professional_booking=None)
        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_payment_rejects_unrelated_payer(self):
        payment = self.make_payment(payer=self.stranger)
        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_payment_rejects_price_different_from_booking_snapshot(self):
        payment = self.make_payment(amount_clp=19500)
        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_payment_rejects_wrong_economic_scope(self):
        payment = self.make_payment(
            economic_scope=Payment.EconomicScope.PROFESSIONAL_ACTIVITY,
        )
        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_database_prevents_two_active_paid_operations_same_booking(self):
        first = self.make_payment(status=Payment.Status.APPROVED)
        first.save()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_payment(status=Payment.Status.APPROVED).save()

        self.assertEqual(
            Payment.objects.filter(
                professional_booking=self.booking,
                status=Payment.Status.APPROVED,
            ).count(),
            1,
        )

    def test_commission_beneficiary_is_service_professional(self):
        payment = self.make_payment()
        snapshot = SimpleNamespace(
            plan_code='professional_base',
            commission_rate_percent=Decimal('12.00'),
        )
        with patch(
            'apps.payments.services.commissions.get_professional_commission_snapshot',
            return_value=snapshot,
        ) as mocked:
            calculation = apply_payment_commission_snapshot(
                payment,
                save=False,
            )

        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.args[0], self.professional)
        self.assertEqual(calculation.commission_amount_clp, 2400)
        self.assertEqual(payment.net_amount_clp, 17600)

    def test_cancellation_does_not_invalidate_existing_payment_history(self):
        payment = self.make_payment(status=Payment.Status.APPROVED)
        payment.full_clean()
        payment.save()

        self.booking.status = Booking.Status.CANCELLED
        self.booking.cancellation_reason = 'No podré asistir ese día.'
        self.booking.cancelled_at = timezone.now()
        self.booking.save()

        payment.refresh_from_db()
        payment.full_clean()
