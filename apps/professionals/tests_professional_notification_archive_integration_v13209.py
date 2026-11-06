"""
V132.09E2: persistencia y aislamiento del historial Profesional.

Usa la base temporal de Django. No requiere un Perfil Profesional real
porque verifica el adaptador autorizado, no el endpoint de acceso.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.notification_event_service_v13209 import (
    record_notification_event,
)
from apps.accounts.notification_read_service import get_read_keys, mark_as_read

from .professional_notification_feed_merge_v13209 import (
    merge_professional_notification_updates,
)


class ProfessionalNotificationArchiveIntegrationV13209Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.professional = User.objects.create_user(
            username="professional_archive_13209",
            email="professional_archive_13209@example.test",
            password="test-pass",
        )

        cls.other_professional = User.objects.create_user(
            username="other_professional_archive_13209",
            email="other_professional_archive_13209@example.test",
            password="test-pass",
        )

    def _record(self, recipient, key):
        return record_notification_event(
            recipient=recipient,
            scope="professional",
            notification_key=key,
            category="booking",
            title="El Miembro envio una solicitud",
            summary="Aviso persistente de prueba.",
            detail_url="/profesionales/",
        )

    def test_archived_event_is_recovered_for_correct_recipient(self):
        key = "booking-history-999101"

        self._record(self.professional, key)

        cards = merge_professional_notification_updates(
            self.professional,
            [],
        )

        self.assertEqual(
            [card["key"] for card in cards],
            [key],
        )
        self.assertEqual(
            cards[0]["kind"],
            "request_archived",
        )
        self.assertTrue(cards[0]["archived"])

    def test_different_professionals_archive_is_not_visible(self):
        key = "booking-history-999102"

        self._record(self.other_professional, key)

        self.assertEqual(
            merge_professional_notification_updates(
                self.professional,
                [],
            ),
            [],
        )

        self.assertEqual(
            [
                card["key"]
                for card in merge_professional_notification_updates(
                    self.other_professional,
                    [],
                )
            ],
            [key],
        )

    def test_archived_event_supports_postgresql_read_state(self):
        key = "booking-history-999103"

        self._record(self.professional, key)
        self._record(self.professional, key)

        available = [
            card["key"]
            for card in merge_professional_notification_updates(
                self.professional,
                [],
            )
        ]

        self.assertEqual(available, [key])

        mark_as_read(
            self.professional,
            "professional",
            [key],
            available,
        )

        self.assertEqual(
            get_read_keys(
                self.professional,
                "professional",
                available,
            ),
            {key},
        )