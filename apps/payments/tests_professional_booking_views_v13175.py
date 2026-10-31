"""Pruebas de integración de rutas y pantallas V131.75.

python manage.py test apps.payments.tests_professional_booking_views_v13175 --verbosity 2
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking, BookingHistory
from apps.bookings.services import create_booking
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalSpecialty,
)

from .models import Payment, Refund


@override_settings(PAYMENTS_SANDBOX=True)
class ProfessionalBookingPageTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(
            username='member_page_13175', email='member_page_13175@example.test', password='test',
        )
        self.professional = User.objects.create_user(
            username='pro_page_13175', email='pro_page_13175@example.test', password='test',
        )
        self.stranger = User.objects.create_user(
            username='stranger_page_13175', email='stranger_page_13175@example.test', password='test',
        )
        category = ProfessionalCategory.objects.create(
            name='Categoría de vistas 13175', slug='categoria-vistas-13175',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Especialidad de vistas 13175', slug='especialidad-vistas-13175', category=category,
        )
        self.profile = ProfessionalProfile.objects.create(
            user=self.professional,
            category=category,
            specialty=specialty,
            bio='Profesional verificado de prueba.',
            offers_online=True,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        self.service = ProfessionalService.objects.create(
            professional_profile=self.profile,
            name='Sesión presencial o online',
            description='Sesión individual.',
            mode=ProfessionalService.ServiceMode.ONLINE,
            duration_minutes=60,
            price=20000,
            publication_status=ProfessionalService.PublicationStatus.PUBLISHED,
        )
        self.day = timezone.localdate() + timedelta(days=14)
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

    def _accept(self):
        self.booking.status = Booking.Status.CONFIRMED
        self.booking.confirmed_at = timezone.now()
        self.booking.save()

    def _approve_through_page(self):
        self._accept()
        self.client.force_login(self.member)
        response = self.client.get(reverse(
            'payments:professional_booking_checkout', args=[self.booking.pk],
        ))
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get(professional_booking=self.booking)
        snapshot = SimpleNamespace(
            plan_code='professional_base', commission_rate_percent=Decimal('12.00'),
        )
        with patch(
            'apps.payments.services.commissions.get_professional_commission_snapshot',
            return_value=snapshot,
        ):
            response = self.client.post(reverse(
                'payments:professional_booking_sandbox_approve', args=[payment.public_id],
            ), {'accept_policy': '1', 'accept_sandbox': '1'})
        self.assertEqual(response.status_code, 302)
        return payment

    def test_pending_booking_has_no_checkout(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse(
            'payments:professional_booking_checkout', args=[self.booking.pk],
        ))
        self.assertRedirects(
            response, reverse('bookings:detail', args=[self.booking.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(Payment.objects.exists())

    def test_unrelated_member_cannot_checkout(self):
        self._accept()
        self.client.force_login(self.stranger)
        response = self.client.get(reverse(
            'payments:professional_booking_checkout', args=[self.booking.pk],
        ))
        self.assertEqual(response.status_code, 404)

    def test_member_can_approve_and_read_receipt(self):
        payment = self._approve_through_page()
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.APPROVED)
        self.assertEqual(payment.net_amount_clp, 17600)
        receipt = self.client.get(reverse(
            'payments:professional_booking_receipt', args=[payment.public_id],
        ))
        self.assertEqual(receipt.status_code, 200)
        self.assertContains(receipt, 'Pago aprobado en sandbox')

    def test_receipt_is_private(self):
        payment = self._approve_through_page()
        self.client.force_login(self.stranger)
        receipt = self.client.get(reverse(
            'payments:professional_booking_receipt', args=[payment.public_id],
        ))
        self.assertEqual(receipt.status_code, 404)

    def test_paid_member_cancel_registers_refund(self):
        payment = self._approve_through_page()
        response = self.client.post(
            reverse('bookings:cancel_my_booking', args=[self.booking.pk]),
            {'cancellation_reason': 'No podré asistir a esa sesión.'},
        )
        self.assertEqual(response.status_code, 302)
        self.booking.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertEqual(Refund.objects.filter(payment=payment).count(), 1)

    def test_professional_cancellation_refunds_and_records_actor(self):
        payment = self._approve_through_page()
        self.client.force_login(self.professional)
        response = self.client.post(
            reverse('bookings:professional_cancel', args=[self.booking.pk]),
            {'cancellation_reason': 'No podré atender el servicio.'},
        )
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertTrue(BookingHistory.objects.filter(
            booking=self.booking,
            action=BookingHistory.Action.CANCELLED,
            changed_by=self.professional,
        ).exists())

    def test_member_detail_displays_checkout_link(self):
        self._accept()
        self.client.force_login(self.member)
        response = self.client.get(reverse('bookings:detail', args=[self.booking.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Realizar pago sandbox')

    def test_sandbox_reject_does_not_cancel_booking(self):
        self._accept()
        self.client.force_login(self.member)
        self.client.get(reverse(
            'payments:professional_booking_checkout', args=[self.booking.pk],
        ))
        payment = Payment.objects.get(professional_booking=self.booking)
        response = self.client.post(reverse(
            'payments:professional_booking_sandbox_reject', args=[payment.public_id],
        ))
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
