"""V132.09B - Pruebas de eventos persistentes.

Ejecutar:
python manage.py test apps.accounts.tests_notification_event_v13209 --verbosity 2

No realiza operaciones externas.
"""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import NotificationEvent, NotificationReadState
from .notification_event_service_v13209 import (
    list_notification_events,
    record_notification_event,
)
from .notification_read_service import (
    get_read_keys,
    mark_as_read,
)


class NotificationEventV13209Tests(TestCase):

    @classmethod
    def setUpTestData(cls):

        User = get_user_model()

        cls.member = User.objects.create_user(
            username="event_member_13209",
            email="event_member_13209@example.test",
            password="test-pass",
        )

        cls.other_member = User.objects.create_user(
            username="event_other_13209",
            email="event_other_13209@example.test",
            password="test-pass",
        )

    def _record(self, **overrides):

        data = {
            "recipient": self.member,
            "scope": NotificationEvent.Scope.MEMBER,
            "notification_key": "booking-history-21",
            "category": NotificationEvent.Category.BOOKING,
            "title": "Tu reserva fue confirmada",
            "summary": "Revisa los detalles de la sesion.",
            "detail_url": "/reservas/21/",
        }

        data.update(overrides)

        return record_notification_event(**data)

    def test_creates_persistent_notification(self):

        event, created = self._record()

        self.assertTrue(created)

        self.assertEqual(
            NotificationEvent.objects.count(),
            1,
        )

        self.assertEqual(
            event.recipient,
            self.member,
        )

        self.assertEqual(
            event.scope,
            "member",
        )

        self.assertEqual(
            event.notification_key,
            "booking-history-21",
        )

        self.assertEqual(
            event.detail_url,
            "/reservas/21/",
        )

    def test_duplicate_key_is_idempotent_and_preserves_first_text(self):

        first, first_created = self._record()

        second, second_created = self._record(
            title="Titulo alterado posteriormente",
            summary="Otro texto",
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)

        self.assertEqual(
            first.pk,
            second.pk,
        )

        self.assertEqual(
            NotificationEvent.objects.count(),
            1,
        )

        second.refresh_from_db()

        self.assertEqual(
            second.title,
            "Tu reserva fue confirmada",
        )

    def test_same_key_is_allowed_for_other_user_or_panel(self):

        member_event, _ = self._record()

        other_event, _ = self._record(
            recipient=self.other_member,
        )

        professional_event, _ = self._record(
            scope=NotificationEvent.Scope.PROFESSIONAL,
        )

        self.assertEqual(
            NotificationEvent.objects.count(),
            3,
        )

        self.assertNotEqual(
            member_event.pk,
            other_event.pk,
        )

        self.assertNotEqual(
            member_event.pk,
            professional_event.pk,
        )

    def test_listing_never_exposes_other_users_or_panels(self):

        event, _ = self._record()

        self._record(
            recipient=self.other_member,
        )

        self._record(
            scope=NotificationEvent.Scope.PROFESSIONAL,
        )

        visible = list_notification_events(
            recipient=self.member,
            scope="member",
        )

        self.assertEqual(
            [item.pk for item in visible],
            [event.pk],
        )

    def test_latest_events_are_ordered_and_limit_is_applied(self):

        now = timezone.now()

        self._record(
            notification_key="old-1",
            occurred_at=now - timedelta(days=2),
        )

        latest, _ = self._record(
            notification_key="new-2",
            occurred_at=now,
        )

        visible = list_notification_events(
            recipient=self.member,
            scope="member",
            limit=1,
        )

        self.assertEqual(
            [item.pk for item in visible],
            [latest.pk],
        )

    def test_invalid_keys_and_external_links_are_rejected(self):

        invalid_keys = (
            "",
            "../video",
            "bad/key",
            " leading",
            "x" * 256,
        )

        for bad_key in invalid_keys:

            with self.subTest(key=bad_key):

                with self.assertRaises(ValidationError):
                    self._record(
                        notification_key=bad_key,
                    )

        invalid_urls = (
            "https://example.com/",
            "//example.com/",
            "javascript:alert(1)",
        )

        for bad_url in invalid_urls:

            with self.subTest(url=bad_url):

                with self.assertRaises(ValidationError):
                    self._record(
                        detail_url=bad_url,
                    )

        self.assertEqual(
            NotificationEvent.objects.count(),
            0,
        )

    def test_invalid_scope_category_and_limit_are_rejected(self):

        with self.assertRaises(ValidationError):
            self._record(
                scope="admin",
            )

        with self.assertRaises(ValidationError):
            self._record(
                category="dangerous",
            )

        for limit in (0, 101, True, "20"):

            with self.subTest(limit=limit):

                with self.assertRaises(ValidationError):

                    list_notification_events(
                        recipient=self.member,
                        scope="member",
                        limit=limit,
                    )

    def test_anonymous_user_cannot_record_or_list(self):

        with self.assertRaises(PermissionDenied):

            self._record(
                recipient=AnonymousUser(),
            )

        with self.assertRaises(PermissionDenied):

            list_notification_events(
                recipient=AnonymousUser(),
                scope="member",
            )

    def test_existing_read_state_remains_compatible(self):

        event, _ = self._record()

        marked = mark_as_read(
            self.member,
            NotificationReadState.Scope.MEMBER,
            [event.notification_key],
            [event.notification_key],
        )

        self.assertEqual(
            marked,
            {event.notification_key},
        )

        self.assertEqual(
            get_read_keys(
                self.member,
                "member",
                [event.notification_key],
            ),
            {event.notification_key},
        )

        self.assertEqual(
            NotificationEvent.objects.count(),
            1,
        )

    def test_naive_dates_are_rejected(self):

        with self.assertRaises(ValidationError):

            self._record(
                occurred_at=datetime(
                    2026,
                    11,
                    5,
                    12,
                    0,
                ),
            )