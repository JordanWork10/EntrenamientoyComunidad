"""V131.86: pruebas de atribución en rutas económicas fuera de /pagos/.

Destino: apps/payments/tests_economic_actor_routes_v13186.py

Ejecutar:
python manage.py test apps.payments.tests_economic_actor_routes_v13186 --verbosity 2
"""

import unittest
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import path, resolve, reverse

from .economic_actor_routes_v13186 import (
    EXTERNAL_ECONOMIC_ROUTE_NAMES,
    enable_external_economic_audit,
)
from .economic_audit_models_v13184 import EconomicAuditEvent
from .models import Settlement


class ExternalEconomicRouteTests(SimpleTestCase):
    def test_expected_routes_are_listed(self):
        self.assertEqual(
            EXTERNAL_ECONOMIC_ROUTE_NAMES['bookings'],
            {'cancel_my_booking', 'professional_cancel'},
        )
        self.assertEqual(
            EXTERNAL_ECONOMIC_ROUTE_NAMES['activities'],
            {'cancel_professional'},
        )
        self.assertEqual(
            EXTERNAL_ECONOMIC_ROUTE_NAMES['spaces'],
            {'cancel_my_booking', 'provider_cancel_booking'},
        )

    def test_enables_only_selected_routes_and_keeps_original_callback(self):
        def original(request):
            return HttpResponse('ok')

        paths = [
            path('cancelar/', original, name='cancel_my_booking'),
            path('detalle/', original, name='booking_detail'),
            path('proveedor/cancelar/', original, name='provider_cancel_booking'),
        ]
        result = enable_external_economic_audit(paths, app_name='spaces')

        self.assertIs(result, paths)
        self.assertIs(result[0].callback.__wrapped__, original)
        self.assertIs(result[1].callback, original)
        self.assertIs(result[2].callback.__wrapped__, original)

    def test_double_activation_is_idempotent(self):
        view = lambda request: HttpResponse('ok')
        paths = [
            path('cancelar/', view, name='cancel_my_booking'),
            path('profesional/cancelar/', view, name='professional_cancel'),
        ]
        enable_external_economic_audit(paths, app_name='bookings')
        first_callback = paths[0].callback
        enable_external_economic_audit(paths, app_name='bookings')
        self.assertIs(paths[0].callback, first_callback)

    def test_missing_mutation_route_fails_loudly(self):
        paths = [path('detalle/', lambda r: HttpResponse('ok'), name='detail')]
        with self.assertRaisesRegex(RuntimeError, 'Faltan rutas económicas'):
            enable_external_economic_audit(paths, app_name='activities')

    def test_unknown_module_is_rejected(self):
        with self.assertRaises(ValueError):
            enable_external_economic_audit([], app_name='desconocido')

    def test_real_bookings_cancel_routes_are_attributed(self):
        for name in ('bookings:cancel_my_booking', 'bookings:professional_cancel'):
            with self.subTest(name=name):
                url = reverse(name, kwargs={'booking_id': 12})
                self.assertTrue(
                    getattr(resolve(url).func, '_economic_actor_v13186', False)
                )

    def test_real_spaces_cancel_routes_are_attributed(self):
        for name in ('spaces:cancel_my_booking', 'spaces:provider_cancel_booking'):
            with self.subTest(name=name):
                url = reverse(name, kwargs={'booking_id': 12})
                self.assertTrue(
                    getattr(resolve(url).func, '_economic_actor_v13186', False)
                )

    def test_real_professional_activity_cancel_is_attributed(self):
        url = reverse('activities:cancel_professional', kwargs={'activity_id': 12})
        self.assertTrue(getattr(resolve(url).func, '_economic_actor_v13186', False))

    def test_read_only_routes_keep_their_original_view(self):
        from apps.bookings import views as booking_views
        url = reverse('bookings:my_bookings')
        self.assertIs(resolve(url).func, booking_views.my_bookings)


@unittest.skipUnless(
    connection.vendor == 'postgresql',
    'La atribución de auditoría V131.86 requiere PostgreSQL.',
)
class ExternalEconomicActorDatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.operator = User.objects.create_user(
            username='external_actor_operator_13186',
            email='external_actor_operator_13186@example.test',
            password='test-pass',
        )
        cls.beneficiary = User.objects.create_user(
            username='external_actor_beneficiary_13186',
            email='external_actor_beneficiary_13186@example.test',
            password='test-pass',
        )
        cls.settlement = Settlement.objects.create(
            beneficiary=cls.beneficiary,
            scope_type=Settlement.ScopeType.PROFESSIONAL_DAY,
            reference_date=date(2026, 11, 1),
            gross_amount_clp=18000,
            commission_base_clp=18000,
            commission_amount_clp=1800,
            net_amount_clp=16200,
            status=Settlement.Status.PENDING,
        )

    def _event_set(self):
        return EconomicAuditEvent.objects.filter(
            source_type=EconomicAuditEvent.Source.SETTLEMENT,
            source_public_id=self.settlement.public_id,
        ).order_by('pk')

    def _request(self, method='post'):
        request = getattr(RequestFactory(), method)('/reservas/ejemplo/cancelar/')
        request.user = self.operator
        return request

    def _wrapped_route(self):
        def cancel_view(request):
            Settlement.objects.filter(pk=self.settlement.pk).update(
                status=Settlement.Status.ON_HOLD,
            )
            return HttpResponse('ok')

        routes = [
            path('cancelar/', cancel_view, name='cancel_my_booking'),
            path('profesional/cancelar/', cancel_view, name='professional_cancel'),
        ]
        enable_external_economic_audit(routes, app_name='bookings')
        return routes[0].callback

    def test_external_post_identifies_authenticated_operator(self):
        response = self._wrapped_route()(self._request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._event_set().count(), 2)
        event = self._event_set().last()
        self.assertEqual(event.actor_identifier, str(self.operator.pk))
        self.assertEqual(event.actor_source, 'operador_autenticado')

    def test_external_get_does_not_attribute_operator(self):
        response = self._wrapped_route()(self._request('get'))
        self.assertEqual(response.status_code, 200)
        event = self._event_set().last()
        self.assertEqual(event.actor_identifier, '')

    def test_external_post_does_not_leak_actor_to_future_updates(self):
        self._wrapped_route()(self._request())
        Settlement.objects.filter(pk=self.settlement.pk).update(
            status=Settlement.Status.ELIGIBLE,
        )
        last_event = self._event_set().last()
        self.assertEqual(last_event.actor_identifier, '')
