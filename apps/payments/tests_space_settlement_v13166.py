"""Pruebas aisladas V131.66 de permisos y barreras de liquidación.

Usan SimpleTestCase y simulaciones; NO crean una base de pruebas.
Verifican las condiciones internas de rechazo, no transacciones reales,
integración ORM, migraciones ni protección CSRF de extremo a extremo.

Ejecutar:
    python manage.py test apps.payments.tests_space_settlement_v13166 --verbosity 2
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

from .models import Settlement
from .services.settlements import (
    SettlementProcessingError,
    calculate_settlement_eligible_at,
    settle_space_day_settlement,
)
from .views import space_settlement_admin


def _validate_close_without_database(settlement, *, reviewed_by):
    """Evalúa la función interna sin abrir la transacción ORM del decorador.

El @transaction.atomic de Django se basa en ContextDecorator y conserva
la función original en __wrapped__. En las pruebas, las consultas se simulan.
No usar este auxiliar en código de producción ni con datos reales.
    """
    return settle_space_day_settlement.__wrapped__(
        settlement, reviewed_by=reviewed_by,
    )


def _operator(*, staff=True, permitted=True):
    """Operador simulado: evita tocar cuentas reales de prueba."""
    return SimpleNamespace(
        is_authenticated=True,
        is_active=True,
        is_staff=staff,
        has_perm=lambda permission: (
            permitted and permission == 'payments.change_settlement'
        ),
    )


class SpaceSettlementReadOnlyTests(SimpleTestCase):
    """Autorización GET y fecha de elegibilidad, sin usar la base de datos."""

    def test_provider_cannot_open_admin_panel(self):
        request = RequestFactory().get(
            '/pagos/administracion/espacios/liquidaciones/'
        )
        request.user = _operator(staff=False, permitted=False)

        with self.assertRaises(PermissionDenied):
            space_settlement_admin(request)

    def test_staff_without_permission_cannot_open_admin_panel(self):
        request = RequestFactory().get(
            '/pagos/administracion/espacios/liquidaciones/'
        )
        request.user = _operator(staff=True, permitted=False)

        with self.assertRaises(PermissionDenied):
            space_settlement_admin(request)

    def test_space_eligibility_starts_24_hours_after_end(self):
        service_end = timezone.make_aware(
            datetime(2026, 11, 2, 10, 0),
            timezone.get_current_timezone(),
        )

        self.assertEqual(
            calculate_settlement_eligible_at(service_end),
            service_end + timedelta(hours=24),
        )


@override_settings(PAYMENTS_SANDBOX=True)
class SpaceSettlementBlockingTests(SimpleTestCase):
    """Comprueba el rechazo del servicio antes de cualquier cierre contable.

    Las consultas se simulan antes de cualquier actualización. No se usa
    ninguna base de datos ni se abre una transacción.
    """

    def setUp(self):
        self.administrator = _operator()
        self.settlement_reference = SimpleNamespace(pk=9)

    def _stored_settlement(self, status, *, eligible_at=None):
        return SimpleNamespace(
            pk=9,
            scope_type=Settlement.ScopeType.SPACE_DAY,
            space_id=1,
            status=status,
            eligible_at=eligible_at,
            reference_date=timezone.localdate(),
            net_amount_clp=16200,
        )

    def _assert_rejected_without_updating_payments(self, expected_message, *, stored):
        with (
            patch(
                'apps.payments.services.settlements.Settlement.objects.select_for_update'
            ) as settlement_query,
            patch(
                'apps.payments.services.settlements.Payment.objects.filter'
            ) as payment_query,
        ):
            settlement_query.return_value.get.return_value = stored

            with self.assertRaisesRegex(
                SettlementProcessingError, expected_message
            ):
                _validate_close_without_database(
                    self.settlement_reference,
                    reviewed_by=self.administrator,
                )

            payment_query.assert_not_called()

    def test_pending_journey_cannot_be_settled(self):
        self._assert_rejected_without_updating_payments(
            'todavía no es elegible',
            stored=self._stored_settlement(Settlement.Status.PENDING),
        )

    def test_held_journey_cannot_be_settled(self):
        self._assert_rejected_without_updating_payments(
            'retenida para revisión',
            stored=self._stored_settlement(Settlement.Status.ON_HOLD),
        )

    def test_eligible_journey_cannot_settle_before_24_hours(self):
        self._assert_rejected_without_updating_payments(
            '24 horas posteriores',
            stored=self._stored_settlement(
                Settlement.Status.ELIGIBLE,
                eligible_at=timezone.now() + timedelta(hours=1),
            ),
        )

    def test_uncompleted_booking_blocks_close_even_after_wait(self):
        eligible_at = timezone.now() - timedelta(days=2)
        current = self._stored_settlement(
            Settlement.Status.ELIGIBLE,
            eligible_at=eligible_at,
        )
        current.beneficiary_id = 31
        space = SimpleNamespace(
            provider_profile=SimpleNamespace(user_id=31),
        )

        with (
            patch(
                'apps.payments.services.settlements.Settlement.objects.select_for_update'
            ) as settlement_query,
            patch(
                'apps.payments.services.settlements.Space.objects.select_related'
            ) as space_query,
            patch(
                'apps.payments.services.settlements._space_day_payments'
            ) as payments_for_day,
            patch(
                'apps.payments.services.settlements._space_day_review'
            ) as review,
            patch(
                'apps.payments.services.settlements.Payment.objects.filter'
            ) as payment_updates,
        ):
            settlement_query.return_value.get.return_value = current
            space_query.return_value.get.return_value = space
            payments_for_day.return_value = []
            review.return_value = (eligible_at, [], True)

            with self.assertRaisesRegex(
                SettlementProcessingError,
                'todavía no están marcadas como completadas',
            ):
                _validate_close_without_database(
                    self.settlement_reference,
                    reviewed_by=self.administrator,
                )

            payment_updates.assert_not_called()

    def test_provider_cannot_authorize_close(self):
        with patch(
            'apps.payments.services.settlements.Settlement.objects.select_for_update'
        ) as settlement_query:
            with self.assertRaisesRegex(
                SettlementProcessingError, 'administrador autorizado'
            ):
                _validate_close_without_database(
                    self.settlement_reference,
                    reviewed_by=_operator(staff=False, permitted=False),
                )

            settlement_query.assert_not_called()

    def test_staff_without_permission_cannot_authorize_close(self):
        with patch(
            'apps.payments.services.settlements.Settlement.objects.select_for_update'
        ) as settlement_query:
            with self.assertRaisesRegex(
                SettlementProcessingError, 'administrador autorizado'
            ):
                _validate_close_without_database(
                    self.settlement_reference,
                    reviewed_by=_operator(staff=True, permitted=False),
                )

            settlement_query.assert_not_called()

    @override_settings(PAYMENTS_SANDBOX=False)
    def test_close_forbidden_outside_sandbox(self):
        with patch(
            'apps.payments.services.settlements.Settlement.objects.select_for_update'
        ) as settlement_query:
            with self.assertRaisesRegex(
                SettlementProcessingError, 'fuera de sandbox'
            ):
                _validate_close_without_database(
                    self.settlement_reference,
                    reviewed_by=self.administrator,
                )

            settlement_query.assert_not_called()
