"""
V132.09E1 - Pruebas del historial del Centro Profesional.

Comprueba la integración de novedades sin modificar
reservas, pagos ni incidencias.
"""

from datetime import date, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.bookings.models import Booking, BookingHistory

from .professional_notification_feed_merge_v13209 import (
    merge_professional_notification_updates,
)


class ProfessionalNotificationFeedMergeV13209Tests(SimpleTestCase):

    def setUp(self):

        self.user = SimpleNamespace(
            pk=21,
            is_authenticated=True,
        )

        self.now = timezone.now()

    def _event(
        self,
        key,
        *,
        title="El Miembro envio una solicitud",
        seconds=0,
        category="booking",
    ):

        return SimpleNamespace(
            notification_key=key,
            title=title,
            summary="Resumen persistente",
            detail_url="/reservas/profesional/91/",
            occurred_at=(
                self.now
                + timedelta(seconds=seconds)
            ),
            category=category,
        )

    def _history(
        self,
        *,
        action=BookingHistory.Action.CREATED,
        status=Booking.Status.PENDING,
    ):

        booking = SimpleNamespace(
            pk=91,
            status=status,
            booked_by=SimpleNamespace(
                pk=12,
                email="miembro@example.test",
            ),
            service_name_snapshot="Servicio de prueba",
            session_date=date(2026, 11, 8),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )

        return SimpleNamespace(
            action=action,
            booking=booking,
        )

    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209._load_professional_booking_histories"
    )
    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209.list_notification_events"
    )
    def test_current_card_wins_over_archived_duplicate(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event("booking-history-70")
        ]

        live = {
            "key": "booking-history-70",
            "kind": "request",
            "created_at": self.now,
        }

        result = merge_professional_notification_updates(
            self.user,
            [live],
        )

        self.assertEqual(
            result,
            [live],
        )

        histories.assert_not_called()

        events.assert_called_once_with(
            recipient=self.user,
            scope="professional",
            limit=100,
        )

    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209._load_professional_booking_histories"
    )
    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209.list_notification_events"
    )
    def test_confirmed_old_request_is_not_presented_as_new(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event("booking-history-71")
        ]

        histories.return_value = {
            71: self._history(
                status=Booking.Status.CONFIRMED
            )
        }

        result = merge_professional_notification_updates(
            self.user,
            [],
        )

        self.assertEqual(
            result[0]["kind"],
            "request_archived",
        )

        self.assertTrue(
            result[0]["archived"]
        )

        self.assertEqual(
            result[0]["booking"].session_date,
            date(2026, 11, 8),
        )

        self.assertEqual(
            result[0]["member"].pk,
            12,
        )

    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209._load_professional_booking_histories"
    )
    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209.list_notification_events"
    )
    def test_still_pending_request_keeps_request_kind(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event("booking-history-72")
        ]

        histories.return_value = {
            72: self._history()
        }

        result = merge_professional_notification_updates(
            self.user,
            [],
        )

        self.assertEqual(
            result[0]["kind"],
            "request",
        )

    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209._load_professional_booking_histories"
    )
    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209.list_notification_events"
    )
    def test_member_cancellation_is_archived_as_cancelled(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event(
                "booking-history-73",
                title="El Miembro cancelo su reserva",
            )
        ]

        histories.return_value = {
            73: self._history(
                action=BookingHistory.Action.CANCELLED,
                status=Booking.Status.CANCELLED,
            )
        }

        result = merge_professional_notification_updates(
            self.user,
            [],
        )

        self.assertEqual(
            result[0]["kind"],
            "cancelled",
        )

        self.assertEqual(
            result[0]["reason"],
            "",
        )

    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209._load_professional_booking_histories"
    )
    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209.list_notification_events"
    )
    def test_missing_history_retains_safe_event_without_booking(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event("booking-history-74")
        ]

        histories.return_value = {}

        result = merge_professional_notification_updates(
            self.user,
            [],
        )

        self.assertEqual(
            result[0]["kind"],
            "request_archived",
        )

        self.assertIsNone(
            result[0]["booking"]
        )

        self.assertIsNone(
            result[0]["member"]
        )

        self.assertEqual(
            result[0]["link_url"],
            "/reservas/profesional/91/",
        )

    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209._load_professional_booking_histories"
    )
    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209.list_notification_events"
    )
    def test_incidents_remain_on_their_current_source(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event(
                "incident-5",
                category="incident",
            )
        ]

        result = merge_professional_notification_updates(
            self.user,
            [],
        )

        self.assertEqual(
            result,
            [],
        )

        histories.assert_not_called()

    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209._load_professional_booking_histories"
    )
    @patch(
        "apps.professionals.professional_notification_feed_merge_v13209.list_notification_events"
    )
    def test_feed_returns_latest_30_and_keeps_unique_keys(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event(
                f"booking-history-{number}",
                seconds=number,
            )
            for number in range(1, 41)
        ]

        histories.return_value = {}

        result = merge_professional_notification_updates(
            self.user,
            [],
            limit=30,
        )

        self.assertEqual(
            len(result),
            30,
        )

        self.assertEqual(
            result[0]["key"],
            "booking-history-40",
        )

        self.assertEqual(
            result[-1]["key"],
            "booking-history-11",
        )

        self.assertEqual(
            len({
                item["key"]
                for item in result
            }),
            30,
        )

    def test_invalid_limit_is_rejected(self):

        with self.assertRaises(ValueError):

            merge_professional_notification_updates(
                self.user,
                [],
                limit=101,
            )