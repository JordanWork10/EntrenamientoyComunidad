"""V131.81: pruebas del resumen read-only de jornadas de espacios.

Copiar como: apps/payments/tests_space_day_admin_v13181.py

Ejecutar:
python manage.py test apps.payments.tests_space_day_admin_v13181 --verbosity 2
"""

from datetime import date, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from .models import Payment, Settlement
from .space_day_admin_v13181 import build_space_day_rows, space_settlement_admin


class SpaceDayAdminV13181Tests(SimpleTestCase):
    def setUp(self):
        self.today = date(2026, 11, 1)
        self.space = SimpleNamespace(pk=21, name='Sala V13181')
        self.other_space = SimpleNamespace(pk=22, name='Cancha V13181')

    def _payment(
        self, *, space=None, day=None, booking_id=1,
        booking_status='completed',
        status=Payment.Status.PARTIALLY_REFUNDED,
        gross=20000, refund=15000, commission=500, net=4500,
    ):
        booking = SimpleNamespace(
            pk=booking_id,
            space=space or self.space,
            session_date=day or self.today,
            status=booking_status,
        )
        return SimpleNamespace(
            space_booking=booking,
            status=status,
            amount_clp=gross,
            refunded_amount_clp=refund,
            commission_amount_clp=commission,
            net_amount_clp=net,
        )

    def _settlement(
        self, *, space=None, day=None, status=Settlement.Status.PENDING,
        gross=20000, refund=15000, commission=500, net=4500,
    ):
        return SimpleNamespace(
            space=space or self.space,
            reference_date=day or self.today,
            status=status,
            gross_amount_clp=gross,
            refunded_amount_clp=refund,
            commission_amount_clp=commission,
            net_amount_clp=net,
        )

    def test_empty_history_does_not_create_rows(self):
        self.assertEqual(build_space_day_rows([], []), [])

    def test_partial_refund_breakdown_is_consistent(self):
        rows = build_space_day_rows([self._payment()], [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['gross_total'], 20000)
        self.assertEqual(row['refunded_total'], 15000)
        self.assertEqual(row['commission_total'], 500)
        self.assertEqual(row['net_total'], 4500)
        self.assertFalse(row['no_balance'])
        self.assertTrue(row['can_prepare'])
        self.assertFalse(row['can_settle'])

    def test_full_refund_is_visible_but_never_liquidable(self):
        fully_refunded = self._payment(
            booking_status='cancelled',
            status=Payment.Status.REFUNDED,
            refund=20000, commission=0, net=0,
        )
        settlement = self._settlement(
            status=Settlement.Status.PENDING,
            refund=20000, commission=0, net=0,
        )
        row = build_space_day_rows([fully_refunded], [settlement])[0]
        self.assertEqual(row['gross_total'], 20000)
        self.assertEqual(row['refunded_total'], 20000)
        self.assertEqual(row['net_total'], 0)
        self.assertTrue(row['no_balance'])
        self.assertEqual(row['operational_label'], 'Sin saldo por liquidar')
        self.assertFalse(row['can_settle'])

    def test_cancelled_booking_with_balance_needs_review(self):
        cancelled = self._payment(booking_status='cancelled')
        row = build_space_day_rows([cancelled], [self._settlement()])[0]
        self.assertTrue(row['cancelled_with_balance'])
        self.assertEqual(row['operational_label'], 'Cancelación con saldo retenido')

    def test_confirmed_booking_requires_completion(self):
        confirmed = self._payment(booking_status='confirmed')
        row = build_space_day_rows([confirmed], [self._settlement()])[0]
        self.assertTrue(row['incomplete'])
        self.assertEqual(row['operational_label'], 'Arriendo por completar')

    def test_eligible_consistent_day_can_show_close(self):
        eligible = self._settlement(status=Settlement.Status.ELIGIBLE)
        row = build_space_day_rows([self._payment()], [eligible])[0]
        self.assertTrue(row['can_settle'])
        self.assertFalse(row['outdated_snapshot'])

    def test_stale_settlement_disables_close_until_review(self):
        stale = self._settlement(
            status=Settlement.Status.ELIGIBLE,
            refund=0, commission=2400, net=17600,
        )
        row = build_space_day_rows([self._payment()], [stale])[0]
        self.assertTrue(row['outdated_snapshot'])
        self.assertTrue(row['can_prepare'])
        self.assertFalse(row['can_settle'])

    def test_already_settled_day_cannot_be_prepared_or_closed_again(self):
        settled = self._settlement(status=Settlement.Status.SETTLED)
        row = build_space_day_rows([self._payment()], [settled])[0]
        self.assertFalse(row['can_prepare'])
        self.assertFalse(row['can_settle'])

    def test_pending_attempts_do_not_count_as_income(self):
        pending = self._payment(
            status=Payment.Status.PENDING,
            refund=0, commission=0, net=0,
        )
        self.assertEqual(build_space_day_rows([pending], []), [])

    def test_two_payments_one_day_share_one_row_and_unique_bookings(self):
        first = self._payment(booking_id=1)
        second = self._payment(booking_id=2)
        row = build_space_day_rows([first, second], [])[0]
        self.assertEqual(row['payment_count'], 2)
        self.assertEqual(row['booking_count'], 2)
        self.assertEqual(row['gross_total'], 40000)
        self.assertEqual(row['refunded_total'], 30000)
        self.assertEqual(row['net_total'], 9000)

    def test_other_spaces_or_dates_never_merge(self):
        later = self.today + timedelta(days=2)
        rows = build_space_day_rows([
            self._payment(booking_id=1),
            self._payment(space=self.other_space, booking_id=2),
            self._payment(day=later, booking_id=3),
        ], [])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['date'], later)

    def test_admin_route_points_to_new_read_only_view(self):
        route = resolve(reverse('payments:space_settlement_admin'))
        self.assertEqual(route.func, space_settlement_admin)

    def test_nonstaff_user_is_forbidden_without_query(self):
        req = RequestFactory().get(reverse('payments:space_settlement_admin'))
        req.user = get_user_model()(username='not_staff_v13181', is_staff=False)
        with self.assertRaises(PermissionDenied):
            space_settlement_admin(req)

    def test_post_is_not_allowed_on_read_only_view(self):
        req = RequestFactory().post(reverse('payments:space_settlement_admin'))
        req.user = get_user_model()(username='staff_v13181', is_staff=True)
        response = space_settlement_admin(req)
        self.assertEqual(response.status_code, 405)

