"""V131.72: no reabrir inscripciones pagadas ya canceladas.

python manage.py test apps.payments.tests_cancelled_activity_rebooking_v13172 --verbosity 2
"""

from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory, ActivityRegistration
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalSpecialty,
)

from .models import Payment, Refund


@override_settings(PAYMENTS_SANDBOX=True)
class CancelledActivityRebookingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.organizer = User.objects.create_user(
            username='organizer_v13172',
            email='organizer_v13172@example.test',
            password='test-only',
        )
        self.camila = User.objects.create_user(
            username='camila_v13172',
            email='camila_v13172@example.test',
            password='test-only',
        )
        self.roberto = User.objects.create_user(
            username='roberto_v13172',
            email='roberto_v13172@example.test',
            password='test-only',
        )
        professional_category = ProfessionalCategory.objects.create(
            name='Entrenamiento V13172',
            slug='entrenamiento-v13172',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Boxeo V13172',
            slug='boxeo-v13172',
            category=professional_category,
        )
        self.profile = ProfessionalProfile.objects.create(
            user=self.organizer,
            category=professional_category,
            specialty=specialty,
            bio='Profesional de prueba.',
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        self.category = ActivityCategory.objects.create(
            name='Actividad V13172',
            slug='actividad-v13172',
        )
        self.activity = Activity.objects.create(
            organizer=self.organizer,
            activity_type=Activity.ActivityType.PROFESSIONAL,
            professional_profile=self.profile,
            category=self.category,
            title='Clase de ensayo V13172',
            description='Actividad profesional pagada.',
            modality=Activity.Modality.ONLINE,
            online_access_info='Sala de ensayo',
            date=timezone.localdate() + timedelta(days=20),
            start_time=time(20, 0),
            end_time=time(21, 0),
            capacity=10,
            price=8000,
            status=Activity.Status.PUBLISHED,
        )
        self.old_registration = ActivityRegistration.objects.create(
            activity=self.activity,
            member=self.camila,
            status=ActivityRegistration.Status.CANCELLED,
        )
        self.old_payment = Payment.objects.create(
            payer=self.camila,
            activity=self.activity,
            registration=self.old_registration,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_ACTIVITY,
            amount_clp=8000,
            refunded_amount_clp=8000,
            commission_rate_percent=Decimal('12.00'),
            commission_base_clp=0,
            commission_amount_clp=0,
            net_amount_clp=0,
            status=Payment.Status.REFUNDED,
        )
        Refund.objects.create(
            payment=self.old_payment,
            requested_by=self.camila,
            refund_type=Refund.RefundType.FULL,
            reason=Refund.Reason.MEMBER_CANCELLATION,
            amount_clp=8000,
            status=Refund.Status.PROCESSED,
        )
        self.pending_payment = Payment.objects.create(
            payer=self.camila,
            activity=self.activity,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_ACTIVITY,
            amount_clp=8000,
            status=Payment.Status.PENDING,
        )

    def test_detail_displays_neutral_lock_without_payment_button(self):
        self.client.force_login(self.camila)
        response = self.client.get(
            reverse('activities:detail', args=[self.activity.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reserva no habilitada')
        self.assertNotContains(response, 'Reservar cupo ·')

    def test_checkout_redirects_before_attempting_payment(self):
        self.client.force_login(self.camila)
        response = self.client.get(
            reverse('payments:checkout', args=[self.activity.pk])
        )
        self.assertRedirects(
            response,
            reverse('activities:detail', args=[self.activity.pk]),
        )
        self.assertEqual(
            Payment.objects.filter(
                payer=self.camila,
                activity=self.activity,
            ).count(),
            2,
        )
        self.pending_payment.refresh_from_db()
        self.assertEqual(self.pending_payment.status, Payment.Status.PENDING)

    def test_old_pending_receipt_warns_cannot_approve(self):
        self.client.force_login(self.camila)
        response = self.client.get(
            reverse('payments:receipt', args=[self.pending_payment.public_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reserva no habilitada')
        self.assertContains(response, 'Cancelar este intento pendiente')

    def test_pending_attempt_can_be_cancelled_from_receipt(self):
        self.client.force_login(self.camila)
        response = self.client.post(
            reverse('payments:cancel', args=[self.pending_payment.public_id])
        )
        self.assertRedirects(
            response,
            reverse('payments:receipt', args=[self.pending_payment.public_id]),
        )
        self.pending_payment.refresh_from_db()
        self.old_payment.refresh_from_db()
        self.assertEqual(self.pending_payment.status, Payment.Status.CANCELLED)
        self.assertEqual(self.old_payment.status, Payment.Status.REFUNDED)

    def test_direct_approval_of_old_pending_attempt_is_cancelled(self):
        self.client.force_login(self.camila)
        response = self.client.post(
            reverse(
                'payments:sandbox_approve',
                args=[self.pending_payment.public_id],
            ),
            {'accept_policy': '1'},
        )
        self.assertRedirects(
            response,
            reverse('activities:detail', args=[self.activity.pk]),
        )
        self.pending_payment.refresh_from_db()
        self.old_payment.refresh_from_db()
        self.old_registration.refresh_from_db()
        self.assertEqual(
            self.pending_payment.status,
            Payment.Status.CANCELLED,
        )
        self.assertIsNone(self.pending_payment.registration_id)
        self.assertIn(
            'Reserva no habilitada',
            self.pending_payment.failure_reason,
        )
        self.assertEqual(self.old_payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.old_payment.refunded_amount_clp, 8000)
        self.assertEqual(
            self.old_registration.status,
            ActivityRegistration.Status.CANCELLED,
        )
        self.assertEqual(Refund.objects.count(), 1)

    def test_cancelled_attempt_receipt_does_not_offer_retry(self):
        self.client.force_login(self.camila)
        self.client.post(
            reverse(
                'payments:sandbox_approve',
                args=[self.pending_payment.public_id],
            ),
            {'accept_policy': '1'},
        )
        response = self.client.get(
            reverse(
                'payments:receipt',
                args=[self.pending_payment.public_id],
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reserva no habilitada')
        self.assertNotContains(response, 'Intentar nuevamente')

    def test_unaffected_member_may_reserve_same_activity(self):
        self.client.force_login(self.roberto)
        response = self.client.get(
            reverse('payments:checkout', args=[self.activity.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Payment.objects.filter(
                activity=self.activity,
                payer=self.roberto,
                status=Payment.Status.PENDING,
            ).count(),
            1,
        )

    def test_same_member_may_pay_different_activity(self):
        other_activity = Activity.objects.create(
            organizer=self.organizer,
            activity_type=Activity.ActivityType.PROFESSIONAL,
            professional_profile=self.profile,
            category=self.category,
            title='Otra clase futura',
            description='Actividad distinta.',
            modality=Activity.Modality.ONLINE,
            online_access_info='Sala alternativa',
            date=self.activity.date + timedelta(days=1),
            start_time=time(20, 0),
            end_time=time(21, 0),
            capacity=10,
            price=8000,
            status=Activity.Status.PUBLISHED,
        )
        self.client.force_login(self.camila)
        response = self.client.get(
            reverse('payments:checkout', args=[other_activity.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Payment.objects.filter(
                activity=other_activity,
                payer=self.camila,
                status=Payment.Status.PENDING,
            ).exists()
        )

    def test_normal_sandbox_approval_remains_available_to_new_member(self):
        self.client.force_login(self.roberto)
        self.client.get(
            reverse('payments:checkout', args=[self.activity.pk])
        )
        payment = Payment.objects.get(
            activity=self.activity,
            payer=self.roberto,
            status=Payment.Status.PENDING,
        )
        response = self.client.post(
            reverse('payments:sandbox_approve', args=[payment.public_id]),
            {'accept_policy': '1'},
        )
        self.assertRedirects(
            response,
            reverse('payments:receipt', args=[payment.public_id]),
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.APPROVED)
        self.assertIsNotNone(payment.registration_id)
        self.assertEqual(
            payment.registration.status,
            ActivityRegistration.Status.REGISTERED,
        )
