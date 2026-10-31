"""V131.71: cancelación del organizador y bloqueo de franja profesional.

Ejecutar en PostgreSQL:
python manage.py test apps.payments.tests_professional_organizer_cancellation_v13171 --verbosity 2
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory, ActivityRegistration
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalSpecialty,
)

from .models import Payment, Refund, Settlement
from .services.professional_activity_cancellations import (
    ProfessionalActivityCancellationError,
    cancel_professional_activity,
)


@override_settings(PAYMENTS_SANDBOX=True)
class OrganizerCancellationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.organizer = User.objects.create_user(
            username='organizador_v13171',
            email='organizador_v13171@example.test',
            password='test',
        )
        self.other_organizer = User.objects.create_user(
            username='otro_organizador_v13171',
            email='otro_organizador_v13171@example.test',
            password='test',
        )
        self.member1 = User.objects.create_user(
            username='miembro1_v13171',
            email='miembro1_v13171@example.test',
            password='test',
        )
        self.member2 = User.objects.create_user(
            username='miembro2_v13171',
            email='miembro2_v13171@example.test',
            password='test',
        )
        professional_category = ProfessionalCategory.objects.create(
            name='Preparación V13171',
            slug='preparacion-v13171',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Movilidad V13171',
            slug='movilidad-v13171',
            category=professional_category,
        )
        self.profile = ProfessionalProfile.objects.create(
            user=self.organizer,
            category=professional_category,
            specialty=specialty,
            bio='Organizador de prueba.',
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        self.other_profile = ProfessionalProfile.objects.create(
            user=self.other_organizer,
            category=professional_category,
            specialty=specialty,
            bio='Otro organizador de prueba.',
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        self.category = ActivityCategory.objects.create(
            name='Clase V13171',
            slug='clase-v13171',
        )
        self.day = timezone.localdate() + timedelta(days=10)
        self.start_datetime = timezone.make_aware(
            datetime.combine(self.day, time(9, 0)),
            timezone.get_current_timezone(),
        )
        self.activity = Activity.objects.create(
            organizer=self.organizer,
            activity_type=Activity.ActivityType.PROFESSIONAL,
            professional_profile=self.profile,
            category=self.category,
            title='Clase grupal V13171',
            description='Actividad profesional de ensayo.',
            modality=Activity.Modality.ONLINE,
            online_access_info='Link de ensayo',
            date=self.day,
            start_time=time(9, 0),
            end_time=time(10, 0),
            capacity=12,
            price=18000,
            status=Activity.Status.PUBLISHED,
        )
        self.registration1 = self.create_registration(self.member1)
        self.payment1 = self.create_payment(self.member1, self.registration1)
        self.cancelled_at = self.start_datetime - timedelta(hours=2)

    def create_registration(self, member):
        return ActivityRegistration.objects.create(
            activity=self.activity,
            member=member,
            status=ActivityRegistration.Status.REGISTERED,
        )

    def create_payment(self, member, registration):
        return Payment.objects.create(
            payer=member,
            activity=self.activity,
            registration=registration,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_ACTIVITY,
            amount_clp=18000,
            status=Payment.Status.APPROVED,
            commission_rate_percent=Decimal('12.00'),
            commission_base_clp=18000,
            commission_amount_clp=2160,
            net_amount_clp=15840,
            approved_at=timezone.now(),
        )

    def cancel(self, **kwargs):
        return cancel_professional_activity(
            self.activity,
            kwargs.pop('organizer', self.organizer),
            kwargs.pop('reason', 'Problema de disponibilidad del organizador.'),
            kwargs.pop('cancelled_at', self.cancelled_at),
        )

    def test_organizer_cancels_and_refunds_every_active_payer(self):
        registration2 = self.create_registration(self.member2)
        payment2 = self.create_payment(self.member2, registration2)
        result = self.cancel()

        self.assertEqual(result.cancelled_registrations, 2)
        self.assertEqual(result.refunds_created, 2)
        self.assertEqual(result.total_refunded_clp, 36000)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, Activity.Status.CANCELLED)
        self.assertEqual(self.activity.cancelled_by_id, self.organizer.id)
        self.assertEqual(
            self.activity.cancellation_reason,
            'Problema de disponibilidad del organizador.',
        )
        self.assertEqual(
            self.activity.cancelled_at,
            self.cancelled_at,
        )
        for payment, registration in (
            (self.payment1, self.registration1),
            (payment2, registration2),
        ):
            payment.refresh_from_db()
            registration.refresh_from_db()
            self.assertEqual(payment.status, Payment.Status.REFUNDED)
            self.assertEqual(payment.refunded_amount_clp, 18000)
            self.assertEqual(payment.commission_base_clp, 0)
            self.assertEqual(payment.commission_amount_clp, 0)
            self.assertEqual(payment.net_amount_clp, 0)
            self.assertEqual(registration.status, ActivityRegistration.Status.CANCELLED)
            refund = Refund.objects.get(payment=payment)
            self.assertEqual(refund.amount_clp, 18000)
            self.assertEqual(
                refund.reason,
                Refund.Reason.PROFESSIONAL_CANCELLATION,
            )
        settlement = Settlement.objects.get(activity=self.activity)
        self.assertEqual(settlement.refunded_amount_clp, 36000)
        self.assertEqual(settlement.net_amount_clp, 0)

    def test_cannot_cancel_twice_or_duplicate_refund(self):
        self.cancel()
        with self.assertRaisesRegex(
            ProfessionalActivityCancellationError,
            'Solo se pueden cancelar',
        ):
            self.cancel()
        self.assertEqual(Refund.objects.filter(payment=self.payment1).count(), 1)

    def test_another_professional_cannot_cancel(self):
        with self.assertRaisesRegex(
            ProfessionalActivityCancellationError,
            'no pertenece',
        ):
            self.cancel(organizer=self.other_organizer)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, Activity.Status.PUBLISHED)
        self.assertFalse(Refund.objects.exists())

    def test_started_activity_requires_admin(self):
        with self.assertRaisesRegex(
            ProfessionalActivityCancellationError,
            'ya comenzó',
        ):
            self.cancel(cancelled_at=self.start_datetime)
        self.assertFalse(Refund.objects.exists())

    def test_settled_payment_requires_admin_and_rolls_back(self):
        self.payment1.settlement_status = Payment.SettlementStatus.SETTLED
        self.payment1.save(update_fields=['settlement_status'])
        with self.assertRaisesRegex(
            ProfessionalActivityCancellationError,
            'retenidos o liquidados',
        ):
            self.cancel()
        self.payment1.refresh_from_db()
        self.assertEqual(self.payment1.status, Payment.Status.APPROVED)
        self.assertFalse(Refund.objects.exists())

    def test_held_settlement_requires_admin(self):
        Settlement.objects.create(
            beneficiary=self.organizer,
            scope_type=Settlement.ScopeType.ACTIVITY,
            activity=self.activity,
            gross_amount_clp=18000,
            commission_base_clp=18000,
            commission_amount_clp=2160,
            net_amount_clp=15840,
            status=Settlement.Status.ON_HOLD,
        )
        with self.assertRaisesRegex(
            ProfessionalActivityCancellationError,
            'liquidación',
        ):
            self.cancel()
        self.assertFalse(Refund.objects.exists())

    def test_pending_refund_requires_admin(self):
        Refund.objects.create(
            payment=self.payment1,
            refund_type=Refund.RefundType.FULL,
            reason=Refund.Reason.MEMBER_CANCELLATION,
            amount_clp=18000,
            status=Refund.Status.REQUESTED,
        )
        with self.assertRaisesRegex(
            ProfessionalActivityCancellationError,
            'pendientes',
        ):
            self.cancel()
        self.assertEqual(
            Refund.objects.filter(status=Refund.Status.PROCESSED).count(),
            0,
        )

    def test_cancelled_slot_blocks_overlapping_republication(self):
        self.cancel()
        another = Activity.objects.create(
            organizer=self.organizer,
            activity_type=Activity.ActivityType.PROFESSIONAL,
            professional_profile=self.profile,
            category=self.category,
            title='Intento de reutilizar horario',
            description='No debe ser publicada.',
            modality=Activity.Modality.ONLINE,
            online_access_info='Enlace de ensayo',
            date=self.day,
            start_time=time(9, 30),
            end_time=time(10, 30),
            capacity=5,
            price=18000,
            status=Activity.Status.DRAFT,
        )
        self.assertTrue(another.conflicts_with_organizer_cancelled_slot())
        with self.assertRaisesRegex(ValidationError, 'Horario no habilitado'):
            another.publish()
        another.refresh_from_db()
        self.assertEqual(another.status, Activity.Status.DRAFT)

    def test_other_professional_and_nonoverlapping_hour_not_blocked(self):
        self.cancel()
        later = Activity(
            organizer=self.organizer,
            activity_type=Activity.ActivityType.PROFESSIONAL,
            professional_profile=self.profile,
            category=self.category,
            title='Clase posterior',
            description='Empieza exactamente al término anterior.',
            modality=Activity.Modality.ONLINE,
            online_access_info='Enlace',
            date=self.day,
            start_time=time(10, 0),
            end_time=time(11, 0),
            capacity=5,
            price=18000,
            status=Activity.Status.DRAFT,
        )
        other = Activity(
            organizer=self.other_organizer,
            activity_type=Activity.ActivityType.PROFESSIONAL,
            professional_profile=self.other_profile,
            category=self.category,
            title='Clase de otro profesional',
            description='Su agenda no está bloqueada.',
            modality=Activity.Modality.ONLINE,
            online_access_info='Enlace',
            date=self.day,
            start_time=time(9, 0),
            end_time=time(10, 0),
            capacity=5,
            price=18000,
            status=Activity.Status.DRAFT,
        )
        self.assertFalse(later.conflicts_with_organizer_cancelled_slot())
        self.assertFalse(other.conflicts_with_organizer_cancelled_slot())
        later.save()
        other.save()
        later.publish()
        other.publish()
        later.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(later.status, Activity.Status.PUBLISHED)
        self.assertEqual(other.status, Activity.Status.PUBLISHED)

    def test_previous_member_cancellation_does_not_retroactively_refund(self):
        self.payment1.refunded_amount_clp = 9000
        self.payment1.status = Payment.Status.PARTIALLY_REFUNDED
        self.payment1.commission_base_clp = 9000
        self.payment1.commission_amount_clp = 1080
        self.payment1.net_amount_clp = 7920
        self.payment1.save()
        self.registration1.status = ActivityRegistration.Status.CANCELLED
        self.registration1.save(update_fields=['status'])
        Refund.objects.create(
            payment=self.payment1,
            refund_type=Refund.RefundType.PARTIAL,
            reason=Refund.Reason.MEMBER_CANCELLATION,
            amount_clp=9000,
            status=Refund.Status.PROCESSED,
        )
        result = self.cancel()
        self.assertEqual(result.refunds_created, 0)
        self.payment1.refresh_from_db()
        self.assertEqual(self.payment1.refunded_amount_clp, 9000)
        self.assertEqual(Refund.objects.filter(payment=self.payment1).count(), 1)

    def test_pending_payment_attempt_is_cancelled(self):
        self.payment1.delete()
        pending = Payment.objects.create(
            payer=self.member1,
            activity=self.activity,
            amount_clp=18000,
            status=Payment.Status.PENDING,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_ACTIVITY,
        )
        result = self.cancel()
        pending.refresh_from_db()
        self.assertEqual(pending.status, Payment.Status.CANCELLED)
        self.assertEqual(result.pending_payments_cancelled, 1)
        self.assertEqual(result.refunds_created, 0)

    def test_empty_reason_does_not_cancel_or_refund(self):
        with self.assertRaisesRegex(
            ProfessionalActivityCancellationError,
            'entre 10 y 1000',
        ):
            self.cancel(reason='No')
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, Activity.Status.PUBLISHED)
        self.assertFalse(Refund.objects.exists())

    @override_settings(PAYMENTS_SANDBOX=False)
    def test_active_paid_reservations_require_sandbox(self):
        with self.assertRaisesRegex(
            ProfessionalActivityCancellationError,
            'solo funciona',
        ):
            self.cancel()
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, Activity.Status.PUBLISHED)
        self.assertFalse(Refund.objects.exists())

    def test_inconsistent_financial_balance_does_not_partially_mutate(self):
        registration2 = self.create_registration(self.member2)
        payment2 = self.create_payment(self.member2, registration2)
        payment2.refunded_amount_clp = 1000
        payment2.save(update_fields=['refunded_amount_clp'])
        with self.assertRaisesRegex(
            ProfessionalActivityCancellationError,
            'inconsistentes',
        ):
            self.cancel()
        self.payment1.refresh_from_db()
        self.activity.refresh_from_db()
        self.assertEqual(self.payment1.status, Payment.Status.APPROVED)
        self.assertEqual(self.activity.status, Activity.Status.PUBLISHED)
        self.assertFalse(Refund.objects.exists())

    def test_free_professional_activity_cancels_without_refunds(self):
        self.payment1.delete()
        self.activity.price = 0
        self.activity.save(update_fields=['price'])
        result = self.cancel()
        self.activity.refresh_from_db()
        self.registration1.refresh_from_db()
        self.assertEqual(result.refunds_created, 0)
        self.assertEqual(self.activity.status, Activity.Status.CANCELLED)
        self.assertEqual(
            self.registration1.status,
            ActivityRegistration.Status.CANCELLED,
        )
