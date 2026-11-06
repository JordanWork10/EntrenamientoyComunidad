"""
V132.09C2 - Pruebas de integración de notificaciones.

Comprueba el almacenamiento de NotificationEvent utilizando
la base de datos temporal de pruebas de Django.

No crea reservas ni pagos en la base de datos principal.
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    NotificationEvent,
    NotificationReadState,
)
from apps.accounts.notification_read_service import (
    get_read_keys,
    mark_as_read,
)

from .models import Booking, BookingHistory
from .notification_receivers_v13209 import (
    on_booking_history_created,
)


class BookingNotificationIntegrationV13209Tests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.member = User.objects.create_user(
            username="member_notification_integration_13209",
            email="member_notification_integration_13209@example.test",
            password="test-pass",
        )

        cls.professional = User.objects.create_user(
            username="professional_notification_integration_13209",
            email="professional_notification_integration_13209@example.test",
            password="test-pass",
        )

    def _history(
        self,
        *,
        pk=71,
        action="created",
        actor_id=None,
        previous_status=None,
    ):
        """
        Construye un historial simulado con usuarios reales
        creados dentro de la base de datos de pruebas.
        """

        booking = SimpleNamespace(
            pk=91,
            booked_by=self.member,
            professional_profile=SimpleNamespace(
                user=self.professional,
            ),
            service_name_snapshot=(
                "Sesion de prueba de notificaciones"
            ),
        )

        return SimpleNamespace(
            pk=pk,
            booking=booking,
            action=action,
            changed_by_id=(
                self.member.pk
                if actor_id is None
                else actor_id
            ),
            previous_data=(
                {"status": previous_status}
                if previous_status
                else {}
            ),
            created_at=timezone.now(),
        )

    def _publish_after_commit(self, history):
        """
        Ejecuta el receptor y su callback de confirmación.

        Se simula únicamente la carga del historial.
        NotificationEvent se guarda realmente en la
        base de datos temporal de Django.
        """

        with patch(
            "apps.bookings.notification_receivers_v13209._load_history",
            return_value=history,
        ):
            with self.captureOnCommitCallbacks(
                execute=True
            ) as callbacks:

                on_booking_history_created(
                    sender=BookingHistory,
                    instance=history,
                    created=True,
                    raw=False,
                    using="default",
                )

            self.assertEqual(
                len(callbacks),
                1,
            )

    def test_request_creates_real_persistent_event_for_professional(self):
        """
        Una solicitud del Miembro genera una notificación
        persistente destinada al Profesional.
        """

        history = self._history(
            action=BookingHistory.Action.CREATED,
        )

        self._publish_after_commit(history)

        event = NotificationEvent.objects.get()

        self.assertEqual(
            event.recipient,
            self.professional,
        )

        self.assertEqual(
            event.scope,
            "professional",
        )

        self.assertEqual(
            event.notification_key,
            "booking-history-71",
        )

        self.assertEqual(
            event.category,
            "booking",
        )

        self.assertTrue(
            event.detail_url.startswith("/")
        )

    def test_confirmation_is_stored_for_member_with_stable_key(self):
        """
        La confirmación del Profesional queda almacenada
        para el Miembro y conserva la clave de lectura V128.
        """

        history = self._history(
            action=BookingHistory.Action.CONFIRMED,
            actor_id=self.professional.pk,
            previous_status=Booking.Status.PENDING,
        )

        self._publish_after_commit(history)

        event = NotificationEvent.objects.get()

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
            "professional-71",
        )

        mark_as_read(
            self.member,
            NotificationReadState.Scope.MEMBER,
            [event.notification_key],
            [event.notification_key],
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

    def test_cancellations_reach_only_the_opposite_party(self):
        """
        Si cancela el Miembro, se notifica al Profesional.

        Si cancela el Profesional, se notifica al Miembro.
        """

        member_cancellation = self._history(
            pk=72,
            action=BookingHistory.Action.CANCELLED,
            actor_id=self.member.pk,
            previous_status=Booking.Status.CONFIRMED,
        )

        professional_rejection = self._history(
            pk=73,
            action=BookingHistory.Action.CANCELLED,
            actor_id=self.professional.pk,
            previous_status=Booking.Status.PENDING,
        )

        self._publish_after_commit(
            member_cancellation
        )

        self._publish_after_commit(
            professional_rejection
        )

        self.assertEqual(
            NotificationEvent.objects.count(),
            2,
        )

        self.assertTrue(
            NotificationEvent.objects.filter(
                recipient=self.professional,
                scope="professional",
                notification_key="booking-history-72",
            ).exists()
        )

        self.assertTrue(
            NotificationEvent.objects.filter(
                recipient=self.member,
                scope="member",
                notification_key="professional-73",
            ).exists()
        )

    def test_reprocessing_same_history_does_not_duplicate_event(self):
        """
        Procesar dos veces el mismo historial no debe
        producir dos notificaciones.
        """

        history = self._history(
            action=BookingHistory.Action.CREATED,
        )

        self._publish_after_commit(history)

        self._publish_after_commit(history)

        self.assertEqual(
            NotificationEvent.objects.count(),
            1,
        )

    def test_rolled_back_booking_does_not_generate_notification(self):
        """
        Una transacción revertida no debe dejar
        notificaciones persistentes.
        """

        history = self._history(
            action=BookingHistory.Action.CREATED,
        )

        with patch(
            "apps.bookings.notification_receivers_v13209._load_history",
            return_value=history,
        ):

            with self.captureOnCommitCallbacks(
                execute=True
            ) as callbacks:

                try:

                    with transaction.atomic():

                        on_booking_history_created(
                            sender=BookingHistory,
                            instance=history,
                            created=True,
                            raw=False,
                            using="default",
                        )

                        raise RuntimeError(
                            "Reversion simulada de reserva"
                        )

                except RuntimeError:
                    pass

        self.assertEqual(
            len(callbacks),
            0,
        )

        self.assertEqual(
            NotificationEvent.objects.count(),
            0,
        )