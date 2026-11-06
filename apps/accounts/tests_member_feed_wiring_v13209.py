"""
V132.09D2 - Integración del historial persistente
con el feed real de novedades del Miembro.

Utiliza la base de datos temporal de Django.
No modifica las reservas ni los datos de producción.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.notification_event_service_v13209 import (
    record_notification_event,
)

from apps.accounts.notification_read_service import (
    get_read_keys,
    mark_as_read,
)

from apps.accounts.notification_views import (
    _available_member_keys,
)

from apps.accounts.views import (
    _account_updates_for,
)


class MemberNotificationFeedWiringV13209Tests(TestCase):

    @classmethod
    def setUpTestData(cls):

        User = get_user_model()

        cls.member = User.objects.create_user(
            username="member_feed_wiring_13209",
            email="member_feed_wiring_13209@example.test",
            password="test-pass",
        )

        cls.other = User.objects.create_user(
            username="other_feed_wiring_13209",
            email="other_feed_wiring_13209@example.test",
            password="test-pass",
        )

    def _record(self, recipient, key):

        record_notification_event(
            recipient=recipient,
            scope="member",
            notification_key=key,
            category="booking",
            title="El Profesional confirmo tu sesion",
            summary="Aviso de prueba persistente.",
            detail_url="/cuenta/",
        )

    def test_stored_event_is_visible_and_authorized_for_mark_read(self):
        """
        Una notificación archivada aparece en el panel
        y puede marcarse como revisada mediante V128.
        """

        key = "professional-999001"

        self._record(
            self.member,
            key,
        )

        updates = _account_updates_for(
            self.member
        )

        self.assertEqual(
            [item["key"] for item in updates],
            [key],
        )

        self.assertEqual(
            updates[0]["kind"],
            "confirmed",
        )

        available = _available_member_keys(
            self.member
        )

        self.assertEqual(
            available,
            [key],
        )

        mark_as_read(
            self.member,
            "member",
            [key],
            available,
        )

        self.assertEqual(
            get_read_keys(
                self.member,
                "member",
                available,
            ),
            {key},
        )

    def test_another_members_stored_notification_stays_private(self):
        """
        Las notificaciones de otro usuario no deben
        aparecer en el panel del Miembro.
        """

        key = "professional-999002"

        self._record(
            self.other,
            key,
        )

        self.assertEqual(
            _account_updates_for(self.member),
            [],
        )

        self.assertEqual(
            _available_member_keys(self.member),
            [],
        )

        self.assertIn(
            key,
            _available_member_keys(self.other),
        )

    def test_repeated_event_does_not_duplicate_member_card(self):
        """
        Registrar dos veces un mismo evento no debe
        producir dos tarjetas de notificación.
        """

        key = "professional-999003"

        self._record(
            self.member,
            key,
        )

        self._record(
            self.member,
            key,
        )

        updates = _account_updates_for(
            self.member
        )

        self.assertEqual(
            [item["key"] for item in updates],
            [key],
        )