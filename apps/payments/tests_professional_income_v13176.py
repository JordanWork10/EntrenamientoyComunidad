"""V131.76 - Pruebas del resumen profesional con sesiones individuales.

Instalar en apps/payments/tests_professional_income_v13176.py
Ejecutar:
python manage.py test apps.payments.tests_professional_income_v13176 --verbosity 2
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
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
from .services.professional_booking_payments import (
    approve_professional_booking_payment,
    cancel_professional_booking_with_refund,
    open_professional_booking_payment,
)


@override_settings(PAYMENTS_SANDBOX=True)
class ProfessionalIncomeSessionsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.professional = User.objects.create_user(
            username='income_pro_v13176',
            email='income_pro_v13176@example.test',
            password='test',
        )
        self.member = User.objects.create_user(
            username='income_member_v13176',
            email='income_member_v13176@example.test',
            password='test',
        )
        self.other_professional = User.objects.create_user(
            username='other_income_pro_v13176',
            email='other_income_pro_v13176@example.test',
            password='test',
        )

        category = ProfessionalCategory.objects.create(
            name='Profesionales con ingresos V13176',
            slug='profesionales-ingresos-v13176',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Especialidad económica V13176',
            slug='especialidad-economica-v13176',
            category=category,
        )
        self.profile = ProfessionalProfile.objects.create(
            user=self.professional,
            category=category,
            specialty=specialty,
            bio='Profesional verificado con pagos sandbox.',
            offers_online=True,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        self.other_profile = ProfessionalProfile.objects.create(
            user=self.other_professional,
            category=category,
            specialty=specialty,
            bio='Profesional distinto de prueba.',
            offers_online=True,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )

        self.service = ProfessionalService.objects.create(
            professional_profile=self.profile,
            name='Sesión personalizada V13176',
            description='Sesión individual para prueba de ingresos.',
            mode=ProfessionalService.ServiceMode.ONLINE,
            duration_minutes=60,
            price=28000,
            publication_status=ProfessionalService.PublicationStatus.PUBLISHED,
        )
        self.day = timezone.localdate() + timedelta(days=14)
        self.start_datetime = timezone.make_aware(
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

    def _income(self, user=None):
        self.client.force_login(user or self.professional)
        return self.client.get(reverse('payments:professional_income'))

    def _approved_payment(self):
        self.booking.status = Booking.Status.CONFIRMED
        self.booking.confirmed_at = timezone.now()
        self.booking.save()

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
                payment.public_id,
                self.member,
                accepts_policy=True,
                accepts_sandbox=True,
            )

    def test_only_pending_attempt_is_not_an_income(self):
        self.booking.status = Booking.Status.CONFIRMED
        self.booking.confirmed_at = timezone.now()
        self.booking.save()
        open_professional_booking_payment(self.booking.pk, self.member)

        response = self._income()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['paid_session_count'], 0)
        self.assertEqual(response.context['to_settle_total'], 0)
        self.assertEqual(response.context['refunded_total'], 0)

    def test_approved_session_enters_income_at_snapshot_values(self):
        self._approved_payment()

        response = self._income()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['paid_session_count'], 1)
        self.assertEqual(response.context['gross_total'], 28000)
        self.assertEqual(response.context['refunded_total'], 0)
        self.assertEqual(response.context['commission_total'], 3360)
        self.assertEqual(response.context['to_settle_total'], 24640)
        self.assertContains(response, 'Sesión personalizada V13176')

    def test_full_refund_preserves_gross_but_zeroes_net(self):
        payment = self._approved_payment()
        cancel_professional_booking_with_refund(
            self.booking.pk,
            self.member,
            by_professional=False,
            reason='No puedo asistir a esta sesión.',
        )
        payment.refresh_from_db()

        response = self._income()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['paid_session_count'], 1)
        self.assertEqual(response.context['gross_total'], 28000)
        self.assertEqual(response.context['refunded_total'], 28000)
        self.assertEqual(response.context['commission_total'], 0)
        self.assertEqual(response.context['to_settle_total'], 0)
        self.assertEqual(response.context['session_groups'][0]['net_total'], 0)
        self.assertEqual(response.context['session_groups'][0]['settlement_code'], 'refunded')
        self.assertContains(response, 'Reembolsado')

    def test_partial_refund_uses_retained_amount_and_original_rate(self):
        self._approved_payment()
        cancel_professional_booking_with_refund(
            self.booking.pk,
            self.member,
            by_professional=False,
            reason='Cambio de disponibilidad de último momento.',
            cancelled_at=self.start_datetime - timedelta(hours=36),
        )

        response = self._income()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['refunded_total'], 21000)
        self.assertEqual(response.context['commission_total'], 840)
        self.assertEqual(response.context['to_settle_total'], 6160)
        self.assertEqual(
            response.context['session_groups'][0]['settlement_code'],
            'partially_refunded',
        )

    def test_different_professional_cannot_see_the_payment(self):
        self._approved_payment()
        response = self._income(self.other_professional)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['paid_session_count'], 0)
        self.assertEqual(response.context['gross_total'], 0)
        self.assertNotContains(response, 'Sesión personalizada V13176')
