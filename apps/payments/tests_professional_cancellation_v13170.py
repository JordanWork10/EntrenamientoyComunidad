"""V131.70: politica y reembolsos de ACTIVIDADES profesionales pagadas.

No corresponde a reservas individuales de servicios profesionales.

Ejecutar con la base de pruebas independiente de Django:
    python manage.py test apps.payments.tests_professional_cancellation_v13170 --verbosity 2

Se necesitan permisos para crear la base de prueba PostgreSQL.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory, ActivityRegistration
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalSpecialty,
)

from .models import Payment, Refund, Settlement
from .services.cancellation_policy import (
    PAYMENTS_POLICY_VERSION,
    calculate_forced_full_refund,
    calculate_member_cancellation,
)
from .services.refunds import (
    RefundProcessingError,
    process_member_activity_cancellation,
)


class ProfessionalActivityPolicyBoundariesTests(SimpleTestCase):
    """Los cortes usan segundos reales, no las horas ya redondeadas."""

    def setUp(self):
        self.start = timezone.make_aware(
            datetime(2027, 2, 10, 9, 0),
            timezone.get_current_timezone(),
        )

    def decide(self, seconds_before, amount_clp=20000):
        return calculate_member_cancellation(
            amount_clp,
            self.start,
            cancelled_at=self.start - timedelta(seconds=seconds_before),
        )

    def test_exactly_48_hours_is_full_refund(self):
        self.assertEqual(self.decide(48 * 3600).refund_percent, Decimal('100'))

    def test_one_second_before_48_hour_threshold_is_75_percent(self):
        decision = self.decide(48 * 3600 - 1)
        self.assertEqual(decision.refund_percent, Decimal('75'))
        self.assertEqual(decision.refund_amount_clp, 15000)

    def test_exactly_24_hours_is_75_percent(self):
        self.assertEqual(self.decide(24 * 3600).refund_percent, Decimal('75'))

    def test_one_second_before_24_hour_threshold_is_50_percent(self):
        decision = self.decide(24 * 3600 - 1)
        self.assertEqual(decision.refund_percent, Decimal('50'))
        self.assertEqual(decision.refund_amount_clp, 10000)

    def test_last_second_before_start_is_still_cancellable(self):
        decision = self.decide(1)
        self.assertEqual(decision.bucket, 'less_than_24h')
        self.assertEqual(decision.refund_percent, Decimal('50'))
        # Se muestra 0.00h, pero eso no significa que ya haya empezado.
        self.assertEqual(decision.hours_before_service, Decimal('0.00'))

    def test_exact_start_is_not_eligible_for_member_automatic_refund(self):
        decision = self.decide(0)
        self.assertEqual(decision.bucket, 'service_started_or_no_show')
        self.assertEqual(decision.refund_amount_clp, 0)

    def test_clp_rounding_is_half_up(self):
        decision = self.decide(36 * 3600, amount_clp=10001)
        self.assertEqual(decision.refund_amount_clp, 7501)
        self.assertEqual(decision.retained_amount_clp, 2500)

    def test_forced_full_refund_calculator_only(self):
        # Se prueba el calculo, no un flujo de cancelacion del organizador.
        decision = calculate_forced_full_refund(20000)
        self.assertEqual(decision.refund_amount_clp, 20000)
        self.assertEqual(decision.retained_amount_clp, 0)


@override_settings(PAYMENTS_SANDBOX=True)
class ProfessionalActivityRefundIntegrationTests(TestCase):
    """Verifica pago, reembolso, inscripcion y liquidacion ORM reales."""

    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(
            username='miembro_prof_v13170',
            email='miembro_prof_v13170@example.test',
            password='clave-de-prueba',
        )
        self.other_member = User.objects.create_user(
            username='otro_prof_v13170',
            email='otro_prof_v13170@example.test',
            password='clave-de-prueba',
        )
        organizer = User.objects.create_user(
            username='profesional_v13170',
            email='profesional_v13170@example.test',
            password='clave-de-prueba',
        )

        category = ProfessionalCategory.objects.create(
            name='Entrenamiento V13170', slug='entrenamiento-v13170',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Preparacion V13170', slug='preparacion-v13170',
            category=category,
        )
        profile = ProfessionalProfile.objects.create(
            user=organizer, category=category, specialty=specialty,
            bio='Perfil exclusivo para pruebas de cancelacion.',
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
        )
        activity_category = ActivityCategory.objects.create(
            name='Actividad V13170', slug='actividad-v13170',
        )
        self.session_date = timezone.localdate() + timedelta(days=12)
        self.start = timezone.make_aware(
            datetime.combine(self.session_date, time(9, 0)),
            timezone.get_current_timezone(),
        )
        self.activity = Activity.objects.create(
            organizer=organizer,
            activity_type=Activity.ActivityType.PROFESSIONAL,
            professional_profile=profile,
            category=activity_category,
            title='Actividad pagada de prueba',
            description='Caso de integracion sin pago real.',
            date=self.session_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            capacity=10,
            price=20000,
            status=Activity.Status.PUBLISHED,
        )
        self.registration = ActivityRegistration.objects.create(
            activity=self.activity,
            member=self.member,
            status=ActivityRegistration.Status.REGISTERED,
        )
        self.payment = Payment.objects.create(
            payer=self.member,
            activity=self.activity,
            registration=self.registration,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_ACTIVITY,
            amount_clp=20000,
            status=Payment.Status.APPROVED,
            commission_rate_percent=Decimal('12.00'),
            commission_base_clp=20000,
            commission_amount_clp=2400,
            net_amount_clp=17600,
            policy_version=PAYMENTS_POLICY_VERSION,
            policy_accepted_at=timezone.now(),
            approved_at=timezone.now(),
        )

    def _cancel(self, seconds_before_start, *, member=None):
        return process_member_activity_cancellation(
            self.payment,
            member or self.member,
            cancelled_at=self.start - timedelta(seconds=seconds_before_start),
        )

    def _assert_result(self, refund_clp, commission_clp, net_clp, status):
        self.payment.refresh_from_db()
        self.registration.refresh_from_db()
        self.assertEqual(self.payment.status, status)
        self.assertEqual(self.payment.refunded_amount_clp, refund_clp)
        self.assertEqual(self.payment.commission_base_clp, 20000 - refund_clp)
        self.assertEqual(self.payment.commission_amount_clp, commission_clp)
        self.assertEqual(self.payment.net_amount_clp, net_clp)
        self.assertEqual(self.registration.status, ActivityRegistration.Status.CANCELLED)
        refunds = Refund.objects.filter(payment=self.payment)
        self.assertEqual(refunds.count(), 1)
        self.assertEqual(refunds.get().amount_clp, refund_clp)
        settlement = Settlement.objects.get(
            scope_type=Settlement.ScopeType.ACTIVITY,
            activity=self.activity,
        )
        self.assertEqual(settlement.refunded_amount_clp, refund_clp)
        self.assertEqual(settlement.commission_amount_clp, commission_clp)
        self.assertEqual(settlement.net_amount_clp, net_clp)

    def test_full_refund_and_zero_commission(self):
        outcome = self._cancel(60 * 3600)
        self.assertEqual(outcome.decision.refund_percent, Decimal('100'))
        self._assert_result(20000, 0, 0, Payment.Status.REFUNDED)

    def test_75_percent_refund_recalculates_commission(self):
        outcome = self._cancel(36 * 3600)
        self.assertEqual(outcome.decision.refund_percent, Decimal('75'))
        self._assert_result(15000, 600, 4400, Payment.Status.PARTIALLY_REFUNDED)

    def test_50_percent_refund_recalculates_commission(self):
        outcome = self._cancel(12 * 3600)
        self.assertEqual(outcome.decision.refund_percent, Decimal('50'))
        self._assert_result(10000, 1200, 8800, Payment.Status.PARTIALLY_REFUNDED)

    def test_last_second_before_start_is_accepted_without_rounding_error(self):
        outcome = self._cancel(1)
        self.assertEqual(outcome.decision.bucket, 'less_than_24h')
        self._assert_result(10000, 1200, 8800, Payment.Status.PARTIALLY_REFUNDED)

    def test_cannot_process_same_refund_twice(self):
        self._cancel(36 * 3600)
        with self.assertRaisesRegex(
            RefundProcessingError, 'ya no admite una cancelación automática',
        ):
            self._cancel(36 * 3600)
        self.assertEqual(Refund.objects.filter(payment=self.payment).count(), 1)

    def test_other_member_cannot_cancel_this_payment(self):
        with self.assertRaisesRegex(RefundProcessingError, 'no pertenece a tu cuenta'):
            self._cancel(36 * 3600, member=self.other_member)
        self.payment.refresh_from_db()
        self.registration.refresh_from_db()
        self.assertEqual(self.payment.refunded_amount_clp, 0)
        self.assertEqual(self.registration.status, ActivityRegistration.Status.REGISTERED)
        self.assertFalse(Refund.objects.filter(payment=self.payment).exists())

    def test_payment_without_policy_acceptance_cannot_refund(self):
        self.payment.policy_accepted_at = None
        self.payment.save(update_fields=['policy_accepted_at'])
        with self.assertRaisesRegex(RefundProcessingError, 'antes de la política'):
            self._cancel(36 * 3600)
        self.assertFalse(Refund.objects.filter(payment=self.payment).exists())

    def test_already_settled_payment_cannot_refund(self):
        self.payment.settlement_status = Payment.SettlementStatus.SETTLED
        self.payment.save(update_fields=['settlement_status'])
        with self.assertRaisesRegex(RefundProcessingError, 'ya fue liquidado'):
            self._cancel(36 * 3600)
        self.assertFalse(Refund.objects.filter(payment=self.payment).exists())

    def test_service_start_cannot_be_cancelled_automatically(self):
        with self.assertRaisesRegex(RefundProcessingError, 'ya comenzó'):
            self._cancel(0)
        self.assertFalse(Refund.objects.filter(payment=self.payment).exists())
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, ActivityRegistration.Status.REGISTERED)
