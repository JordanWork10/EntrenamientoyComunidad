"""V131.85 — identificación del operador autenticado de eventos económicos.

Copiar como: apps/payments/tests_economic_actor_v13185.py

Ejecutar:
python manage.py test apps.payments.tests_economic_actor_v13185 --verbosity 2
"""

import unittest
from datetime import date
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import resolve, reverse

from .admin_economic_audit_v13183 import admin_economic_audit
from . import professional_booking_views
from .economic_actor_v13185 import (
    ECONOMIC_MUTATION_NAMES,
    attribute_economic_post,
)
from .economic_audit_events_v13184 import economic_audit_events
from .economic_audit_models_v13184 import EconomicAuditEvent
from .models import Settlement


class EconomicActorRouteTests(SimpleTestCase):
    def test_read_only_admin_routes_keep_original_view(self):
        self.assertIs(
            resolve(reverse('payments:admin_economic_audit')).func,
            admin_economic_audit,
        )
        self.assertIs(
            resolve(reverse('payments:economic_audit_events')).func,
            economic_audit_events,
        )

    def test_mutation_names_include_approval_refund_and_settlement(self):
        expected = {
            'sandbox_approve', 'sandbox_reject', 'cancel',
            'professional_booking_sandbox_approve',
            'professional_booking_sandbox_reject',
            'space_sandbox_approve', 'space_sandbox_reject',
            'professional_day_settlement_close',
            'space_settlement_close',
            'space_cancellation_resolve',
            'cancel_paid_activity',
        }
        self.assertTrue(expected.issubset(ECONOMIC_MUTATION_NAMES))

    def test_real_payment_mutation_route_uses_actor_wrapper(self):
        url = reverse('payments:professional_booking_sandbox_approve', kwargs={
            'payment_id': UUID('a1b2c3d4-1234-4123-8123-0123456789ab'),
        })
        callback = resolve(url).func
        self.assertIs(
            callback.__wrapped__,
            professional_booking_views.professional_booking_sandbox_approve,
        )

    def test_get_calls_view_without_economic_transaction(self):
        called = []

        def view(request):
            called.append(request.method)
            return HttpResponse('ok')

        request = RequestFactory().get('/pagos/ejemplo/')
        request.user = AnonymousUser()
        self.assertEqual(attribute_economic_post(view)(request).status_code, 200)
        self.assertEqual(called, ['GET'])


@unittest.skipUnless(
    connection.vendor == 'postgresql',
    'La atribución transaccional V131.85 requiere PostgreSQL.',
)
class EconomicActorDatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser(
            username='actor_admin_13185',
            email='actor_admin_13185@example.test',
            password='test-pass',
        )
        cls.other = User.objects.create_user(
            username='actor_other_13185',
            email='actor_other_13185@example.test',
            password='test-pass',
            is_staff=True,
        )
        cls.beneficiary = User.objects.create_user(
            username='actor_beneficiary_13185',
            email='actor_beneficiary_13185@example.test',
            password='test-pass',
        )
        cls.settlement = Settlement.objects.create(
            beneficiary=cls.beneficiary,
            scope_type=Settlement.ScopeType.PROFESSIONAL_DAY,
            reference_date=date(2026, 11, 1),
            gross_amount_clp=10000,
            commission_base_clp=10000,
            commission_amount_clp=1200,
            net_amount_clp=8800,
            status=Settlement.Status.PENDING,
        )

    def _events(self):
        return EconomicAuditEvent.objects.filter(
            source_type=EconomicAuditEvent.Source.SETTLEMENT,
            source_public_id=self.settlement.public_id,
        ).order_by('pk')

    def _post(self, user):
        request = RequestFactory().post('/pagos/ejemplo/')
        request.user = user
        return request

    def _update_status(self, status):
        Settlement.objects.filter(pk=self.settlement.pk).update(status=status)

    def test_authenticated_post_identifies_operator(self):
        def view(request):
            self._update_status(Settlement.Status.ON_HOLD)
            return HttpResponse('ok')

        response = attribute_economic_post(view)(self._post(self.admin))
        self.assertEqual(response.status_code, 200)
        event = self._events().last()
        self.assertEqual(self._events().count(), 2)
        self.assertEqual(event.after_state['status'], 'on_hold')
        self.assertEqual(event.actor_identifier, str(self.admin.pk))
        self.assertEqual(event.actor_source, 'operador_autenticado')

    def test_anonymous_post_does_not_fake_an_actor(self):
        def view(request):
            self._update_status(Settlement.Status.ON_HOLD)
            return HttpResponse('ok')

        attribute_economic_post(view)(self._post(AnonymousUser()))
        event = self._events().last()
        self.assertEqual(event.actor_identifier, '')
        self.assertEqual(event.actor_source, '')

    def test_post_without_economic_change_creates_no_event(self):
        response = attribute_economic_post(
            lambda request: HttpResponse('sin cambios')
        )(self._post(self.admin))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._events().count(), 1)

    def test_actor_scope_is_cleared_after_post(self):
        def view(request):
            self._update_status(Settlement.Status.ON_HOLD)
            return HttpResponse('ok')

        attribute_economic_post(view)(self._post(self.admin))
        self._update_status(Settlement.Status.ELIGIBLE)
        events = list(self._events())
        self.assertEqual(len(events), 3)
        self.assertEqual(events[1].actor_identifier, str(self.admin.pk))
        self.assertEqual(events[2].actor_identifier, '')

    def test_previous_actor_context_is_restored(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('payments.audit_actor_id', %s, true)",
                ['actor_externo'],
            )

        attribute_economic_post(
            lambda request: HttpResponse('ok')
        )(self._post(self.admin))

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('payments.audit_actor_id', true)"
            )
            current_actor = cursor.fetchone()[0]
        self.assertEqual(current_actor, 'actor_externo')

    def test_request_actor_takes_priority_over_fallback_authorizer(self):
        def view(request):
            Settlement.objects.filter(pk=self.settlement.pk).update(
                status=Settlement.Status.SETTLED,
                settled_by=self.admin,
            )
            return HttpResponse('ok')

        attribute_economic_post(view)(self._post(self.other))
        event = self._events().last()
        self.assertEqual(event.actor_identifier, str(self.other.pk))
        self.assertEqual(event.actor_source, 'operador_autenticado')

    def test_without_request_actor_fallback_authorizer_remains(self):
        Settlement.objects.filter(pk=self.settlement.pk).update(
            status=Settlement.Status.SETTLED,
            settled_by=self.admin,
        )
        event = self._events().last()
        self.assertEqual(event.actor_identifier, str(self.admin.pk))
        self.assertEqual(event.actor_source, 'autorizador')

    def test_view_exception_rolls_back_money_and_event(self):
        def failing_view(request):
            self._update_status(Settlement.Status.ON_HOLD)
            raise RuntimeError('Fallo simulado')

        with self.assertRaises(RuntimeError):
            attribute_economic_post(failing_view)(self._post(self.admin))
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, Settlement.Status.PENDING)
        self.assertEqual(self._events().count(), 1)

    def test_view_exception_does_not_leak_actor(self):
        def failing_view(request):
            self._update_status(Settlement.Status.ON_HOLD)
            raise RuntimeError('Error de prueba')

        with self.assertRaises(RuntimeError):
            attribute_economic_post(failing_view)(self._post(self.admin))
        self._update_status(Settlement.Status.ELIGIBLE)
        event = self._events().last()
        self.assertEqual(event.actor_identifier, '')

    def test_get_does_not_attribute_a_financial_change(self):
        request = RequestFactory().get('/pagos/ejemplo/')
        request.user = self.admin

        def unsafe_read_view(req):
            # Defensa contra una vista GET antigua que escriba por error:
            # el wrapper no debe atribuir una mutación fuera de POST.
            self._update_status(Settlement.Status.ON_HOLD)
            return HttpResponse('ok')

        attribute_economic_post(unsafe_read_view)(request)
        event = self._events().last()
        self.assertEqual(event.actor_identifier, '')
