"""
V132.09D1 - Pruebas del adaptador de notificaciones del Miembro.

No requieren modificar reservas ni utilizar la base
de datos principal.
"""

from datetime import date, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.bookings.models import Booking, BookingHistory

from .notification_feed_merge_v13209 import (
    merge_member_notification_updates,
)


class MemberNotificationFeedMergeV13209Tests(SimpleTestCase):

    def setUp(self):

        self.user = SimpleNamespace(
            pk=11,
            is_authenticated=True,
        )

        self.now = timezone.now()

    def _event(
        self,
        key,
        *,
        title="Confirmo tu sesion",
        seconds=0,
        category="booking",
    ):

        return SimpleNamespace(
            notification_key=key,
            category=category,
            title=title,
            summary="Resumen persistente",
            detail_url="/reservas/91/",
            occurred_at=(
                self.now
                + timedelta(seconds=seconds)
            ),
        )

    def _history(
        self,
        *,
        action=BookingHistory.Action.CONFIRMED,
        previous_status=None,
    ):

        professional = SimpleNamespace(
            get_full_name=lambda: "Profesional Demo",
            email="profesional@example.test",
        )

        booking = SimpleNamespace(
            professional_profile=SimpleNamespace(
                user=professional,
            ),
            service_name_snapshot="Entrenamiento personal",
            session_date=date(2026, 11, 8),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )

        return SimpleNamespace(
            action=action,
            previous_data=(
                {"status": previous_status}
                if previous_status
                else {}
            ),
            booking=booking,
        )

    @patch(
        "apps.accounts.notification_feed_merge_v13209._load_member_booking_histories"
    )
    @patch(
        "apps.accounts.notification_feed_merge_v13209.list_notification_events"
    )
    def test_duplicate_prefers_complete_current_card(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event("professional-70")
        ]

        live = {
            "key": "professional-70",
            "kind": "confirmed",
            "created_at": self.now,
            "reason": "Motivo de la vista actual",
        }

        result = merge_member_notification_updates(
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
            scope="member",
            limit=100,
        )

    @patch(
        "apps.accounts.notification_feed_merge_v13209._load_member_booking_histories"
    )
    @patch(
        "apps.accounts.notification_feed_merge_v13209.list_notification_events"
    )
    def test_archived_confirmation_keeps_fields_expected_by_template(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event("professional-71")
        ]

        histories.return_value = {
            71: self._history()
        }

        result = merge_member_notification_updates(
            self.user,
            [],
        )

        self.assertEqual(
            len(result),
            1,
        )

        card = result[0]

        self.assertEqual(
            card["key"],
            "professional-71",
        )

        self.assertEqual(
            card["module"],
            "professional",
        )

        self.assertEqual(
            card["kind"],
            "confirmed",
        )

        self.assertEqual(
            card["session_date"],
            date(2026, 11, 8),
        )

        self.assertEqual(
            card["start_time"],
            time(10, 0),
        )

        self.assertEqual(
            card["end_time"],
            time(11, 0),
        )

        self.assertEqual(
            card["reason"],
            "",
        )

    @patch(
        "apps.accounts.notification_feed_merge_v13209._load_member_booking_histories"
    )
    @patch(
        "apps.accounts.notification_feed_merge_v13209.list_notification_events"
    )
    def test_rejected_cancellation_restores_correct_kind(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event("professional-72")
        ]

        histories.return_value = {
            72: self._history(
                action=BookingHistory.Action.CANCELLED,
                previous_status=Booking.Status.PENDING,
            )
        }

        result = merge_member_notification_updates(
            self.user,
            [],
        )

        self.assertEqual(
            result[0]["kind"],
            "rejected",
        )

    @patch(
        "apps.accounts.notification_feed_merge_v13209._load_member_booking_histories"
    )
    @patch(
        "apps.accounts.notification_feed_merge_v13209.list_notification_events"
    )
    def test_missing_booking_history_retains_safe_archive_fallback(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event(
                "professional-73",
                title="Confirmo tu sesion",
            )
        ]

        histories.return_value = {}

        result = merge_member_notification_updates(
            self.user,
            [],
        )

        self.assertEqual(
            result[0]["kind"],
            "confirmed",
        )

        self.assertIsNone(
            result[0]["session_date"]
        )

        self.assertEqual(
            result[0]["detail_url"],
            "/reservas/91/",
        )

    @patch(
        "apps.accounts.notification_feed_merge_v13209._load_member_booking_histories"
    )
    @patch(
        "apps.accounts.notification_feed_merge_v13209.list_notification_events"
    )
    def test_other_categories_stay_on_their_existing_feed(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event(
                "activity-11",
                category="activity",
            )
        ]

        result = merge_member_notification_updates(
            self.user,
            [],
        )

        self.assertEqual(
            result,
            [],
        )

        histories.assert_not_called()

    @patch(
        "apps.accounts.notification_feed_merge_v13209._load_member_booking_histories"
    )
    @patch(
        "apps.accounts.notification_feed_merge_v13209.list_notification_events"
    )
    def test_feed_returns_latest_30_without_duplicates(
        self,
        events,
        histories,
    ):

        events.return_value = [
            self._event(
                f"professional-{number}",
                seconds=number,
            )
            for number in range(1, 41)
        ]

        histories.return_value = {}

        result = merge_member_notification_updates(
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
            "professional-40",
        )

        self.assertEqual(
            result[-1]["key"],
            "professional-11",
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

            merge_member_notification_updates(
                self.user,
                [],
                limit=101,
            )
            