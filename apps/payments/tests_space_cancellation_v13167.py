"""Pruebas aisladas V131.67; no crean bases de datos PostgreSQL.

Verifican permisos, sandbox y barreras contables. NO sustituyen las
pruebas de integración transaccional/ORM ni CSRF de extremo a extremo.

Comando:
python manage.py test apps.payments.tests_space_cancellation_v13167 --verbosity 2
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from .models import Payment, SpaceCancellationRequest
from .services.space_cancellations import (
    SpaceCancellationError,
    request_paid_space_cancellation,
    resolve_paid_space_cancellation,
)
from .services.settlements import _space_day_review


def _make_booking(*, status='completed'):
    date = timezone.localdate() - timedelta(days=4)
    return SimpleNamespace(
        pk=9,
        space_id=22,
        booked_by_id=7,
        provider_profile_id=44,
        provider_profile=SimpleNamespace(user_id=13),
        session_date=date,
        start_time=datetime(2026, 11, 2, 9, 0).time(),
        end_time=datetime(2026, 11, 2, 10, 0).time(),
        status=status,
    )


def _make_payment(booking):
    return SimpleNamespace(
        pk=42,
        space_booking=booking,
        space_booking_id=booking.pk,
        amount_clp=18000,
        refunded_amount_clp=0,
        commission_base_clp=18000,
        commission_amount_clp=1800,
        net_amount_clp=16200,
        payer_id=7,
        settlement_id=None,
        settlement_status=Payment.SettlementStatus.PENDING,
    )


def _review_without_database(payment, cancellations):
    with (
        patch('apps.payments.services.settlements.Refund.objects.filter') as refunds,
        patch(
            'apps.payments.services.settlements.SpaceCancellationRequest.objects.filter'
        ) as cancellation_query,
    ):
        refunds.return_value.values_list.return_value = []
        refunds.return_value.values.return_value.annotate.return_value = (
            [{'payment_id': payment.pk, 'total': payment.refunded_amount_clp}]
            if payment.refunded_amount_clp else []
        )
        cancellation_query.return_value.order_by.return_value = cancellations
        return _space_day_review(
            [payment],
            space=SimpleNamespace(pk=22, provider_profile_id=44),
        )


class SpaceCancellationSettlementReviewTests(SimpleTestCase):
    def test_pending_cancellation_blocks_liquidation(self):
        payment = _make_payment(_make_booking())
        cancellation = SimpleNamespace(
            payment_id=42,
            booking_id=9,
            status=SpaceCancellationRequest.Status.PENDING,
        )
        _, blockers, _ = _review_without_database(payment, [cancellation])
        self.assertTrue(any('cancelación pagada pendiente' in row for row in blockers))

    def test_cancelled_booking_without_approval_blocks_liquidation(self):
        payment = _make_payment(_make_booking(status='cancelled'))
        _, blockers, waiting = _review_without_database(payment, [])
        self.assertFalse(waiting)
        self.assertTrue(any('sin resolución económica' in row for row in blockers))

    def test_approved_cancel_with_retained_balance_may_be_evaluated(self):
        payment = _make_payment(_make_booking(status='cancelled'))
        payment.refunded_amount_clp = 9000
        payment.commission_base_clp = 9000
        payment.commission_amount_clp = 900
        payment.net_amount_clp = 8100
        cancellation = SimpleNamespace(
            payment_id=42,
            booking_id=9,
            status=SpaceCancellationRequest.Status.APPROVED,
            refund_amount_clp=9000,
        )
        _, blockers, waiting = _review_without_database(payment, [cancellation])
        self.assertEqual(blockers, [])
        self.assertFalse(waiting)

    def test_payment_already_held_blocks_even_with_approved_cancel(self):
        payment = _make_payment(_make_booking(status='cancelled'))
        payment.settlement_status = Payment.SettlementStatus.ON_HOLD
        cancellation = SimpleNamespace(
            payment_id=42, booking_id=9,
            status=SpaceCancellationRequest.Status.APPROVED,
            refund_amount_clp=0,
        )
        _, blockers, _ = _review_without_database(payment, [cancellation])
        self.assertTrue(any('pago retenido' in row for row in blockers))


@override_settings(PAYMENTS_SANDBOX=True)
class SpaceCancellationAccessTests(SimpleTestCase):
    def test_unauthorized_user_cannot_open_cancellation_request(self):
        booking = _make_booking(status='confirmed')
        booking.session_date = timezone.localdate() + timedelta(days=10)
        actor = SimpleNamespace(
            pk=999, is_authenticated=True, is_active=True,
        )
        with patch(
            'apps.payments.services.space_cancellations.SpaceBooking.objects.select_for_update'
        ) as bookings:
            bookings.return_value.select_related.return_value.get.return_value = booking
            with self.assertRaisesRegex(
                SpaceCancellationError, 'No tienes autorización'
            ):
                request_paid_space_cancellation.__wrapped__(
                    booking_id=9, actor=actor, reason='No podré asistir',
                )

    def test_provider_cannot_resolve_paid_cancellation(self):
        provider = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            has_perm=lambda _: False,
        )
        with patch(
            'apps.payments.services.space_cancellations.SpaceCancellationRequest.objects.select_for_update'
        ) as requests:
            with self.assertRaisesRegex(
                SpaceCancellationError, 'administrador autorizado'
            ):
                resolve_paid_space_cancellation.__wrapped__(
                    cancellation_id=1, reviewer=provider, approve=True,
                    refund_amount_clp=18000,
                    review_notes='Devolución total revisada',
                )
            requests.assert_not_called()

    def test_repeat_resolution_is_idempotent(self):
        administrator = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            has_perm=lambda permission: permission == 'payments.change_settlement',
        )
        reviewed = SimpleNamespace(
            pk=5, status=SpaceCancellationRequest.Status.APPROVED,
        )
        with (
            patch(
                'apps.payments.services.space_cancellations.SpaceCancellationRequest.objects.only'
            ) as request_refs,
            patch(
                'apps.payments.services.space_cancellations.SpaceBooking.objects.select_for_update'
            ) as bookings,
            patch(
                'apps.payments.services.space_cancellations.SpaceCancellationRequest.objects.select_for_update'
            ) as requests,
            patch(
                'apps.payments.services.space_cancellations.Payment.objects.select_for_update'
            ) as payments,
        ):
            request_refs.return_value.get.return_value = SimpleNamespace(booking_id=9)
            bookings.return_value.select_related.return_value.get.return_value = (
                SimpleNamespace(pk=9)
            )
            requests.return_value.get.return_value = reviewed
            result, created = resolve_paid_space_cancellation.__wrapped__(
                cancellation_id=5,
                reviewer=administrator,
                approve=True,
                refund_amount_clp=18000,
                review_notes='Ya se resolvió la cancelación',
            )
            self.assertIs(result, reviewed)
            self.assertFalse(created)
            payments.assert_not_called()

    @override_settings(PAYMENTS_SANDBOX=False)
    def test_request_forbidden_outside_sandbox(self):
        with patch(
            'apps.payments.services.space_cancellations.SpaceBooking.objects.select_for_update'
        ) as bookings:
            with self.assertRaisesRegex(
                SpaceCancellationError, 'solo está disponible en sandbox'
            ):
                request_paid_space_cancellation.__wrapped__(
                    booking_id=9,
                    actor=SimpleNamespace(
                        pk=7, is_authenticated=True, is_active=True,
                    ),
                    reason='No podré asistir',
                )
            bookings.assert_not_called()
