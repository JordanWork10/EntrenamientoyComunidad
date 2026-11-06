"""V132.09C1 - Pruebas de notificaciones de reservas.

Ejecutar:
python manage.py test apps.bookings.tests_booking_notification_v13209 --verbosity 2

No modifica reservas reales ni ejecuta pagos.
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from .models import Booking, BookingHistory
from .notification_receivers_v13209 import (
    _persist_history_notification,
    build_booking_notification_payload,
    on_booking_history_created,
)


def fake_user(pk, name):

    return SimpleNamespace(
        pk=pk,
        email=f"usuario{pk}@example.test",
        get_full_name=lambda: name,
    )


class BookingNotificationV13209Tests(SimpleTestCase):

    def setUp(self):

        self.member = fake_user(
            11,
            "Ana Miembro",
        )

        self.professional = fake_user(
            22,
            "Luis Profesional",
        )

        self.booking = SimpleNamespace(
            pk=31,
            booked_by=self.member,
            professional_profile=SimpleNamespace(
                user=self.professional,
            ),
            service_name_snapshot="Entrenamiento personalizado",
        )

    def history(
        self,
        *,
        action,
        actor_id,
        previous_status=None,
    ):

        return SimpleNamespace(
            pk=47,
            booking=self.booking,
            action=action,
            changed_by_id=actor_id,
            previous_data=(
                {"status": previous_status}
                if previous_status
                else {}
            ),
            created_at=timezone.now(),
            reason="Informacion sensible que no debe archivarse",
        )

    def test_member_request_notifies_professional_with_old_key(self):

        event = self.history(
            action=BookingHistory.Action.CREATED,
            actor_id=self.member.pk,
        )

        payload = build_booking_notification_payload(
            event
        )

        self.assertIs(
            payload["recipient"],
            self.professional,
        )

        self.assertEqual(
            payload["scope"],
            "professional",
        )

        self.assertEqual(
            payload["notification_key"],
            "booking-history-47",
        )

        self.assertEqual(
            payload["category"],
            "booking",
        )

        self.assertTrue(
            payload["detail_url"].startswith("/")
        )

        self.assertEqual(
            payload["occurred_at"],
            event.created_at,
        )

    def test_professional_confirmation_notifies_member(self):

        payload = build_booking_notification_payload(
            self.history(
                action=BookingHistory.Action.CONFIRMED,
                actor_id=self.professional.pk,
                previous_status=Booking.Status.PENDING,
            )
        )

        self.assertIs(
            payload["recipient"],
            self.member,
        )

        self.assertEqual(
            payload["scope"],
            "member",
        )

        self.assertEqual(
            payload["notification_key"],
            "professional-47",
        )

        self.assertIn(
            "confirm",
            payload["title"].lower(),
        )

    def test_professional_rejection_differs_from_later_cancellation(self):

        rejected = build_booking_notification_payload(
            self.history(
                action=BookingHistory.Action.CANCELLED,
                actor_id=self.professional.pk,
                previous_status=Booking.Status.PENDING,
            )
        )

        cancelled = build_booking_notification_payload(
            self.history(
                action=BookingHistory.Action.CANCELLED,
                actor_id=self.professional.pk,
                previous_status=Booking.Status.CONFIRMED,
            )
        )

        self.assertIs(
            rejected["recipient"],
            self.member,
        )

        self.assertIn(
            "rechazada",
            rejected["summary"],
        )

        self.assertIn(
            "cancelada",
            cancelled["summary"],
        )

        self.assertEqual(
            rejected["notification_key"],
            "professional-47",
        )

    def test_member_cancellation_notifies_professional(self):

        payload = build_booking_notification_payload(
            self.history(
                action=BookingHistory.Action.CANCELLED,
                actor_id=self.member.pk,
                previous_status=Booking.Status.CONFIRMED,
            )
        )

        self.assertIs(
            payload["recipient"],
            self.professional,
        )

        self.assertEqual(
            payload["scope"],
            "professional",
        )

        self.assertEqual(
            payload["notification_key"],
            "booking-history-47",
        )

    def test_system_events_and_unexpected_actors_are_ignored(self):

        cases = (
            (BookingHistory.Action.EXPIRED, None),
            (BookingHistory.Action.COMPLETED, self.professional.pk),
            (BookingHistory.Action.CREATED, 999),
            (BookingHistory.Action.CONFIRMED, self.member.pk),
            (BookingHistory.Action.CANCELLED, 999),
        )

        for action, actor in cases:

            with self.subTest(
                action=action,
                actor=actor,
            ):

                self.assertIsNone(
                    build_booking_notification_payload(
                        self.history(
                            action=action,
                            actor_id=actor,
                        )
                    )
                )

    def test_no_self_notification(self):

        self.booking.professional_profile.user = self.member

        self.assertIsNone(
            build_booking_notification_payload(
                self.history(
                    action=BookingHistory.Action.CREATED,
                    actor_id=self.member.pk,
                )
            )
        )

    def test_free_text_reason_is_not_persisted(self):

        payload = build_booking_notification_payload(
            self.history(
                action=BookingHistory.Action.CANCELLED,
                actor_id=self.member.pk,
                previous_status=Booking.Status.PENDING,
            )
        )

        self.assertNotIn(
            "Informacion sensible",
            str(payload),
        )

    @patch(
        "apps.bookings.notification_receivers_v13209.transaction.on_commit"
    )
    def test_signal_schedules_after_commit_only_for_creation(
        self,
        register,
    ):

        history = self.history(
            action=BookingHistory.Action.CREATED,
            actor_id=self.member.pk,
        )

        on_booking_history_created(
            sender=BookingHistory,
            instance=history,
            created=True,
            raw=False,
            using="default",
        )

        register.assert_called_once()

        callback = register.call_args.args[0]

        with patch(
            "apps.bookings.notification_receivers_v13209."
            "_persist_history_notification"
        ) as persist:

            callback()

            persist.assert_called_once_with(47)

    @patch(
        "apps.bookings.notification_receivers_v13209.transaction.on_commit"
    )
    def test_signal_ignores_updates_raw_fixtures_and_other_databases(
        self,
        register,
    ):

        history = self.history(
            action=BookingHistory.Action.CREATED,
            actor_id=self.member.pk,
        )

        on_booking_history_created(
            sender=BookingHistory,
            instance=history,
            created=False,
            raw=False,
            using="default",
        )

        on_booking_history_created(
            sender=BookingHistory,
            instance=history,
            created=True,
            raw=True,
            using="default",
        )

        on_booking_history_created(
            sender=BookingHistory,
            instance=history,
            created=True,
            raw=False,
            using="otra_base",
        )

        register.assert_not_called()

    @patch(
        "apps.bookings.notification_receivers_v13209.record_notification_event"
    )
    @patch(
        "apps.bookings.notification_receivers_v13209._load_history"
    )
    def test_callback_records_notification(
        self,
        load_history,
        record,
    ):

        load_history.return_value = self.history(
            action=BookingHistory.Action.CONFIRMED,
            actor_id=self.professional.pk,
            previous_status=Booking.Status.PENDING,
        )

        _persist_history_notification(47)

        record.assert_called_once()

        self.assertEqual(
            record.call_args.kwargs["notification_key"],
            "professional-47",
        )

    @patch(
        "apps.bookings.notification_receivers_v13209.logger"
    )
    @patch(
        "apps.bookings.notification_receivers_v13209._load_history"
    )
    def test_callback_failure_is_logged_without_raising(
        self,
        load_history,
        logger,
    ):

        load_history.side_effect = RuntimeError(
            "Base de datos no disponible"
        )

        _persist_history_notification(47)

        logger.exception.assert_called_once()