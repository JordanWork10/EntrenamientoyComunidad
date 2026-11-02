"""V131.80: pruebas de historial privado del Miembro.

Copiar como: apps/payments/tests_member_payments_v13180.py

Ejecutar:
python manage.py test apps.payments.tests_member_payments_v13180 --verbosity 2
"""

from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
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


class MemberPaymentsV13180Tests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(
            username='member_13180',
            email='member_13180@example.test',
            password='test-pass',
        )
        self.other_member = User.objects.create_user(
            username='other_13180',
            email='other_13180@example.test',
            password='test-pass',
        )
        professional = User.objects.create_user(
            username='prof_13180',
            email='prof_13180@example.test',
            password='test-pass',
        )
        category = ProfessionalCategory.objects.create(
            name='Categoría V13180',
            slug='categoria-v13180',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Especialidad V13180',
            slug='especialidad-v13180',
            category=category,
        )
        self.profile = ProfessionalProfile.objects.create(
            user=professional,
            category=category,
            specialty=specialty,
            bio='Profesional de prueba.',
            offers_online=True,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        self.service = ProfessionalService.objects.create(
            professional_profile=self.profile,
            name='Entrenamiento V13180',
            description='Sesión individual de prueba.',
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
            end_time=time(14),
            valid_from=self.day,
            is_active=True,
        )

        self.booking = self._booking(self.member, 9)
        self.payment = self._payment(
            self.member,
            self.booking,
            Payment.Status.PARTIALLY_REFUNDED,
            refund=15000,
        )
        other_booking = self._booking(self.other_member, 10)
        self.other_payment = self._payment(
            self.other_member,
            other_booking,
            Payment.Status.APPROVED,
        )
        self.url = reverse('payments:my_payments')

    def _booking(self, member, hour):
        booking = create_booking(
            user=member,
            service=self.service,
            session_date=self.day,
            start_time=time(hour),
            end_time=time(hour + 1),
        )
        booking.status = Booking.Status.CONFIRMED
        booking.confirmed_at = timezone.now()
        booking.save(update_fields=['status', 'confirmed_at', 'updated_at'])
        return booking

    def _payment(self, member, booking, status, refund=0):
        balance = 20000 - refund if status in (
            Payment.Status.APPROVED,
            Payment.Status.PARTIALLY_REFUNDED,
            Payment.Status.REFUNDED,
        ) else 0
        commission = balance * 12 // 100
        return Payment.objects.create(
            payer=member,
            professional_booking=booking,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
            amount_clp=20000,
            status=status,
            refunded_amount_clp=refund,
            commission_base_clp=balance,
            commission_amount_clp=commission,
            net_amount_clp=balance - commission,
        )

    def test_login_is_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('next=', response.url)

    def test_member_sees_own_session_and_correct_receipt_link(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['movements_total'], 1)
        self.assertEqual(response.context['sessions_count'], 1)
        self.assertContains(response, 'Entrenamiento V13180')
        self.assertContains(response, 'Sesión individual')
        self.assertContains(
            response,
            reverse('payments:professional_booking_receipt', kwargs={
                'payment_id': self.payment.public_id,
            }),
        )

    def test_member_cannot_see_other_payer_payment(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url)
        payment_ids = list(
            response.context['payments'].values_list('pk', flat=True)
        )
        self.assertEqual(payment_ids, [self.payment.pk])
        self.assertNotContains(response, str(self.other_payment.public_id))

    def test_private_receipt_rejects_other_member(self):
        self.client.force_login(self.member)
        other_receipt = reverse(
            'payments:professional_booking_receipt',
            kwargs={'payment_id': self.other_payment.public_id},
        )
        self.assertEqual(self.client.get(other_receipt).status_code, 404)

    def test_partial_refund_summary_preserves_historical_paid_amount(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.context['approved_total'], 20000)
        self.assertEqual(response.context['refunded_total'], 15000)
        self.assertEqual(response.context['retained_total'], 5000)
        self.assertContains(response, 'Reembolso parcial')

    def test_full_refund_keeps_receipt_but_has_zero_retained(self):
        full_booking = self._booking(self.member, 11)
        self._payment(
            self.member, full_booking, Payment.Status.REFUNDED, refund=20000,
        )
        self.client.force_login(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.context['movements_total'], 2)
        self.assertEqual(response.context['approved_total'], 40000)
        self.assertEqual(response.context['refunded_total'], 35000)
        self.assertEqual(response.context['retained_total'], 5000)
        self.assertContains(response, 'Reembolsado')

    def test_pending_attempt_is_in_history_but_not_approved_total(self):
        pending_booking = self._booking(self.member, 12)
        self._payment(self.member, pending_booking, Payment.Status.PENDING)
        self.client.force_login(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.context['movements_total'], 2)
        self.assertEqual(response.context['approved_total'], 20000)
        self.assertContains(response, 'Pago no aprobado')

    def test_filter_sessions_and_empty_other_categories(self):
        self.client.force_login(self.member)
        sessions = self.client.get(self.url + '?tipo=sesiones')
        self.assertEqual(sessions.context['selected_type'], 'sesiones')
        self.assertEqual(len(sessions.context['payments']), 1)

        activities = self.client.get(self.url + '?tipo=actividades')
        self.assertEqual(activities.context['selected_type'], 'actividades')
        self.assertEqual(len(activities.context['payments']), 0)
        self.assertContains(activities, 'No hay movimientos para este filtro')

        spaces = self.client.get(self.url + '?tipo=espacios')
        self.assertEqual(len(spaces.context['payments']), 0)

    def test_unrecognized_filter_is_ignored_safely(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url + '?tipo=otro__campo')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_type'], 'todos')
        self.assertEqual(len(response.context['payments']), 1)

    def test_get_never_modifies_payment_or_booking(self):
        self.client.force_login(self.member)
        old_payment_updated_at = self.payment.updated_at
        old_booking_updated_at = self.booking.updated_at
        self.client.get(self.url)
        self.client.get(self.url + '?tipo=sesiones')
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.updated_at, old_payment_updated_at)
        self.assertEqual(self.booking.updated_at, old_booking_updated_at)

    def test_defense_against_inconsistent_payer_booking_relation(self):
        # Evita filtrar solo por payer en historiales con datos defectuosos:
        # un pago cuyo booked_by no coincide tampoco se muestra.
        member_booking = self._booking(self.member, 11)
        bad_payment = self._payment(
            self.other_member, member_booking, Payment.Status.APPROVED,
        )
        self.client.force_login(self.other_member)
        response = self.client.get(self.url)
        self.assertEqual(response.context['movements_total'], 1)
        self.assertNotContains(response, str(bad_payment.public_id))

