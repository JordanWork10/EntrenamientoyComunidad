"""V131.69: pruebas de integracion ORM para cancelaciones pagadas de espacios.

Ruta en el proyecto: apps/payments/tests_space_cancellation_integration_v13169.py

Ejecutar desde la raiz del proyecto, con el entorno virtual activado:
    python manage.py test apps.payments.tests_space_cancellation_integration_v13169 --verbosity 2

IMPORTANTE: Django crea una base de datos DE PRUEBAS independiente; no usar
runserver ni ejecutar estas pruebas contra la base de datos de produccion.
Se requiere un usuario de PostgreSQL capaz de crear bases de pruebas.
No se modifica ningun archivo ni modelo de produccion.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.locations.models import Commune, Region
from apps.spaces.models import (
    Space,
    SpaceAvailability,
    SpaceBooking,
    SpaceBookingHistory,
    SpaceProviderProfile,
    SpaceType,
)

from .models import Payment, Refund, Settlement, SpaceCancellationRequest
from .services.space_cancellations import (
    SpaceCancellationError,
    request_paid_space_cancellation,
    resolve_paid_space_cancellation,
)
from .services.space_policy import SPACE_POLICY_VERSION


@override_settings(PAYMENTS_SANDBOX=True)
class PaidSpaceCancellationIntegrationTests(TestCase):
    """Prueba las transacciones reales usando datos aislados de Django."""

    AMOUNT = 18000

    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(
            username='miembro_v13169',
            email='miembro_v13169@example.test',
            password='clave-solo-pruebas',
        )
        self.other_member = User.objects.create_user(
            username='otro_v13169',
            email='otro_v13169@example.test',
            password='clave-solo-pruebas',
        )
        self.provider = User.objects.create_user(
            username='proveedor_v13169',
            email='proveedor_v13169@example.test',
            password='clave-solo-pruebas',
        )
        self.admin = User.objects.create_superuser(
            username='admin_v13169',
            email='admin_v13169@example.test',
            password='clave-solo-pruebas',
        )

        region = Region.objects.create(name='Region Pruebas V13169', code='T69')
        commune = Commune.objects.create(
            name='Comuna Pruebas V13169', code='C69', region=region,
        )
        self.provider_profile = SpaceProviderProfile.objects.create(
            user=self.provider,
            public_name='Proveedor de prueba',
        )
        space_type = SpaceType.objects.create(
            name='Gimnasio de prueba', slug='gimnasio-prueba-v13169',
        )
        self.space = Space.objects.create(
            provider_profile=self.provider_profile,
            space_type=space_type,
            name='Espacio de prueba V13169',
            description='Espacio exclusivo para pruebas de integracion.',
            commune=commune,
            address='Direccion ficticia 123',
            capacity=10,
            hourly_price_clp=self.AMOUNT,
            publication_status=Space.PublicationStatus.PUBLISHED,
        )

        self.session_date = timezone.localdate() + timedelta(days=12)
        self.session_start = timezone.make_aware(
            datetime.combine(self.session_date, time(9, 0)),
            timezone.get_current_timezone(),
        )
        SpaceAvailability.objects.create(
            space=self.space,
            weekday=self.session_date.weekday(),
            start_time=time(9, 0),
            end_time=time(10, 0),
            valid_from=timezone.localdate(),
        )
        self.booking = SpaceBooking.objects.create(
            booked_by=self.member,
            space=self.space,
            provider_profile=self.provider_profile,
            session_date=self.session_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            duration_minutes=60,
            price_clp=self.AMOUNT,
            space_name_snapshot=self.space.name,
            space_type_snapshot='Gimnasio',
            provider_name_snapshot=self.provider_profile.public_name,
            address_snapshot=self.space.address,
            commune_snapshot=commune.name,
            status=SpaceBooking.Status.CONFIRMED,
            confirmed_at=timezone.now(),
        )
        self.payment = Payment.objects.create(
            payer=self.member,
            space_booking=self.booking,
            economic_scope=Payment.EconomicScope.SPACE_BOOKING,
            amount_clp=self.AMOUNT,
            status=Payment.Status.APPROVED,
            plan_code_snapshot='space_provider_base',
            commission_rate_percent=Decimal('10.00'),
            commission_base_clp=self.AMOUNT,
            commission_amount_clp=1800,
            net_amount_clp=16200,
            policy_version=SPACE_POLICY_VERSION,
            policy_accepted_at=timezone.now(),
            approved_at=timezone.now(),
        )

    def _request(self, *, hours_before_start, hours_after_payment=3, actor=None):
        """Fija el reloj para no esperar horas ni alterar datos reales."""
        cancelled_at = self.session_start - timedelta(hours=hours_before_start)
        self.payment.approved_at = cancelled_at - timedelta(
            hours=hours_after_payment,
        )
        self.payment.policy_accepted_at = (
            self.payment.approved_at
            if self.payment.policy_version == SPACE_POLICY_VERSION
            else None
        )
        self.payment.save(update_fields=[
            'approved_at', 'policy_accepted_at', 'updated_at',
        ])
        with patch('django.utils.timezone.now', return_value=cancelled_at):
            return request_paid_space_cancellation(
                booking_id=self.booking.pk,
                actor=actor or self.member,
                reason='No podre utilizar el espacio reservado.',
            )

    def _assert_economics(
        self, *, refund_clp, commission_clp, net_clp, status,
    ):
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.refunded_amount_clp, refund_clp)
        self.assertEqual(self.payment.status, status)
        self.assertEqual(self.payment.commission_base_clp, self.AMOUNT - refund_clp)
        self.assertEqual(self.payment.commission_amount_clp, commission_clp)
        self.assertEqual(self.payment.net_amount_clp, net_clp)
        self.assertEqual(self.booking.status, SpaceBooking.Status.CANCELLED)
        self.assertEqual(self.payment.settlement_status, Payment.SettlementStatus.PENDING)
        self.assertEqual(self.payment.settlement_hold_reason, '')

        refunds = Refund.objects.filter(payment=self.payment)
        self.assertEqual(refunds.count(), 1 if refund_clp else 0)
        if refund_clp:
            refund = refunds.get()
            self.assertEqual(refund.amount_clp, refund_clp)
            self.assertEqual(refund.status, Refund.Status.PROCESSED)
            self.assertEqual(refund.policy_version_snapshot, SPACE_POLICY_VERSION)

        self.assertEqual(
            SpaceBookingHistory.objects.filter(
                booking=self.booking, action=SpaceBookingHistory.Action.CANCELLED,
            ).count(),
            1,
        )
        settlement = Settlement.objects.get(
            space=self.space, reference_date=self.session_date,
            scope_type=Settlement.ScopeType.SPACE_DAY,
        )
        self.assertEqual(settlement.gross_amount_clp, self.AMOUNT)
        self.assertEqual(settlement.refunded_amount_clp, refund_clp)
        self.assertEqual(settlement.commission_amount_clp, commission_clp)
        self.assertEqual(settlement.net_amount_clp, net_clp)

    def test_more_than_48_hours_returns_100_percent(self):
        cancellation, created = self._request(hours_before_start=60)
        self.assertTrue(created)
        self.assertEqual(cancellation.status, SpaceCancellationRequest.Status.APPROVED)
        self.assertIsNone(cancellation.reviewed_by)
        self._assert_economics(
            refund_clp=18000, commission_clp=0, net_clp=0,
            status=Payment.Status.REFUNDED,
        )

    def test_between_24_and_48_hours_returns_50_percent(self):
        cancellation, created = self._request(hours_before_start=36)
        self.assertTrue(created)
        self.assertEqual(cancellation.refund_amount_clp, 9000)
        self._assert_economics(
            refund_clp=9000, commission_clp=900, net_clp=8100,
            status=Payment.Status.PARTIALLY_REFUNDED,
        )

    def test_less_than_24_hours_returns_zero_without_refund(self):
        cancellation, created = self._request(hours_before_start=12)
        self.assertTrue(created)
        self.assertEqual(cancellation.status, SpaceCancellationRequest.Status.APPROVED)
        self.assertEqual(cancellation.refund_amount_clp, 0)
        self.assertIsNone(cancellation.refund_id)
        self._assert_economics(
            refund_clp=0, commission_clp=1800, net_clp=16200,
            status=Payment.Status.APPROVED,
        )

    def test_two_hour_grace_returns_100_percent_with_36_hours_to_start(self):
        cancellation, _ = self._request(
            hours_before_start=36, hours_after_payment=1,
        )
        self.assertEqual(cancellation.refund_amount_clp, 18000)
        self._assert_economics(
            refund_clp=18000, commission_clp=0, net_clp=0,
            status=Payment.Status.REFUNDED,
        )

    def test_grace_expires_after_two_hours_and_returns_half(self):
        cancellation, _ = self._request(
            hours_before_start=36, hours_after_payment=2.1,
        )
        self.assertEqual(cancellation.refund_amount_clp, 9000)
        self._assert_economics(
            refund_clp=9000, commission_clp=900, net_clp=8100,
            status=Payment.Status.PARTIALLY_REFUNDED,
        )

    def test_repeat_resolution_cannot_refund_or_cancel_twice(self):
        cancellation, _ = self._request(hours_before_start=36)
        reviewed, changed = resolve_paid_space_cancellation(
            cancellation_id=cancellation.pk,
            reviewer=None,
            approve=True,
            refund_amount_clp=9000,
            review_notes='Reintento de resolucion automatica de prueba.',
            automated=True,
        )
        self.assertEqual(reviewed.pk, cancellation.pk)
        self.assertFalse(changed)
        with self.assertRaisesRegex(SpaceCancellationError, 'reserva confirmada'):
            self._request(hours_before_start=36)
        self._assert_economics(
            refund_clp=9000, commission_clp=900, net_clp=8100,
            status=Payment.Status.PARTIALLY_REFUNDED,
        )
        self.assertEqual(
            SpaceCancellationRequest.objects.filter(booking=self.booking).count(),
            1,
        )

    def test_legacy_payment_remains_on_hold_for_manual_review(self):
        self.payment.policy_version = 'LEGACY_PRE_POLICY'
        self.payment.policy_accepted_at = None
        self.payment.save(update_fields=['policy_version', 'policy_accepted_at'])
        cancellation, created = self._request(hours_before_start=60)
        self.assertTrue(created)
        cancellation.refresh_from_db()
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(cancellation.status, SpaceCancellationRequest.Status.PENDING)
        self.assertEqual(self.payment.settlement_status, Payment.SettlementStatus.ON_HOLD)
        self.assertEqual(self.booking.status, SpaceBooking.Status.CONFIRMED)
        self.assertFalse(Refund.objects.filter(payment=self.payment).exists())

        decision, changed = resolve_paid_space_cancellation(
            cancellation_id=cancellation.pk,
            reviewer=self.admin,
            approve=True,
            refund_amount_clp=18000,
            review_notes='Se autoriza devolucion completa de caso heredado.',
        )
        self.assertTrue(changed)
        self.assertEqual(decision.status, SpaceCancellationRequest.Status.APPROVED)
        self._assert_economics_manual(
            refunded_clp=18000, commission_clp=0, net_clp=0,
        )

    def test_provider_cancellation_needs_admin_and_refunds_full_balance(self):
        cancellation, created = self._request(
            hours_before_start=60, actor=self.provider,
        )
        self.assertTrue(created)
        self.assertEqual(cancellation.status, SpaceCancellationRequest.Status.PENDING)
        self.assertEqual(cancellation.requested_role, 'provider')
        with self.assertRaisesRegex(SpaceCancellationError, 'administrador autorizado'):
            resolve_paid_space_cancellation(
                cancellation_id=cancellation.pk,
                reviewer=self.provider,
                approve=True,
                refund_amount_clp=18000,
                review_notes='Proveedor intenta autorizar su propia solicitud.',
            )

        decision, changed = resolve_paid_space_cancellation(
            cancellation_id=cancellation.pk,
            reviewer=self.admin,
            approve=True,
            refund_amount_clp=18000,
            review_notes='Administracion autoriza cancelacion del proveedor.',
        )
        self.assertTrue(changed)
        self.assertEqual(decision.refund_amount_clp, 18000)
        self._assert_economics_manual(
            refunded_clp=18000, commission_clp=0, net_clp=0,
        )

    def test_admin_rejection_releases_hold_but_preserves_booking(self):
        cancellation, _ = self._request(
            hours_before_start=60, actor=self.provider,
        )
        decision, changed = resolve_paid_space_cancellation(
            cancellation_id=cancellation.pk,
            reviewer=self.admin,
            approve=False,
            refund_amount_clp=0,
            review_notes='El proveedor conserva la reserva al rechazar la solicitud.',
        )
        self.assertTrue(changed)
        self.assertEqual(decision.status, SpaceCancellationRequest.Status.REJECTED)
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, SpaceBooking.Status.CONFIRMED)
        self.assertEqual(self.payment.refunded_amount_clp, 0)
        self.assertEqual(self.payment.commission_amount_clp, 1800)
        self.assertEqual(self.payment.net_amount_clp, 16200)
        self.assertEqual(self.payment.settlement_status, Payment.SettlementStatus.PENDING)
        self.assertFalse(Refund.objects.filter(payment=self.payment).exists())

    def _assert_economics_manual(self, *, refunded_clp, commission_clp, net_clp):
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, SpaceBooking.Status.CANCELLED)
        self.assertEqual(self.payment.refunded_amount_clp, refunded_clp)
        self.assertEqual(self.payment.commission_amount_clp, commission_clp)
        self.assertEqual(self.payment.net_amount_clp, net_clp)
        self.assertEqual(self.payment.settlement_status, Payment.SettlementStatus.PENDING)
        self.assertEqual(Refund.objects.filter(payment=self.payment).count(), 1)

    def test_third_party_cannot_request_cancellation(self):
        with self.assertRaisesRegex(SpaceCancellationError, 'No tienes autorizacion|No tienes autorización'):
            self._request(hours_before_start=60, actor=self.other_member)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refunded_amount_clp, 0)
        self.assertFalse(SpaceCancellationRequest.objects.filter(booking=self.booking).exists())

    def test_settled_payment_cannot_be_cancelled_automatically(self):
        self.payment.settlement_status = Payment.SettlementStatus.SETTLED
        self.payment.save(update_fields=['settlement_status'])
        with self.assertRaisesRegex(SpaceCancellationError, 'ya está liquidado'):
            self._request(hours_before_start=60)
        self.assertFalse(SpaceCancellationRequest.objects.filter(booking=self.booking).exists())

    def test_member_rebooking_block_is_personal_and_persists_in_database(self):
        self._request(hours_before_start=60)
        self.assertTrue(SpaceBooking.member_cancelled_overlapping_slot(
            member_id=self.member.pk,
            space_id=self.space.pk,
            session_date=self.session_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        ))
        self.assertFalse(SpaceBooking.member_cancelled_overlapping_slot(
            member_id=self.other_member.pk,
            space_id=self.space.pk,
            session_date=self.session_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        ))

