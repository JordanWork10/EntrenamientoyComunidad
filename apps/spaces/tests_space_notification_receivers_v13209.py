"""Pruebas unitarias V132.09F2 para notificaciones de arriendos."""

from datetime import datetime, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.accounts.models import NotificationEvent
from apps.spaces.models import SpaceBooking, SpaceBookingHistory
from apps.spaces.space_notification_receivers_v13209 import (
    _notification_specs,
    persist_space_booking_history_notifications,
    space_booking_history_notification,
)


MODULE = "apps.spaces.space_notification_receivers_v13209"


class SpaceNotificationReceiversV13209Tests(SimpleTestCase):

    def setUp(self):

        self.member = SimpleNamespace(
            pk=11,
            email="camila@example.com",
            get_full_name=lambda: "Camila Pérez",
        )

        self.provider = SimpleNamespace(
            pk=22,
            email="roberto@example.com",
            get_full_name=lambda: "Roberto Tototo",
        )

        self.booking = SimpleNamespace(
            pk=101,
            booked_by=self.member,
            provider_profile=SimpleNamespace(
                user=self.provider
            ),
            provider_name_snapshot="Roberto Tototo",
            space_name_snapshot="Gym ejemplo",
        )

    def _history(
        self,
        action,
        *,
        changed_by_id,
        previous_status=None,
    ):

        return SimpleNamespace(
            pk=201,
            booking=self.booking,
            action=action,
            changed_by_id=changed_by_id,
            previous_data=(
                {"status": previous_status}
                if previous_status
                else {}
            ),
            created_at=datetime(
                2026,
                11,
                6,
                12,
                tzinfo=datetime_timezone.utc,
            ),
        )

    def _specs(self, history):

        with patch(
            f"{MODULE}.reverse",
            side_effect=[
                "/mi-reserva/",
                "/proveedor/",
            ],
        ):
            return _notification_specs(history)

    def test_creacion_avisada_solo_al_proveedor(self):

        history = self._history(
            SpaceBookingHistory.Action.CREATED,
            changed_by_id=self.member.pk,
        )

        specs = self._specs(history)

        self.assertEqual(len(specs), 1)
        self.assertEqual(
            specs[0]["recipient"],
            self.provider,
        )
        self.assertEqual(
            specs[0]["scope"],
            NotificationEvent.Scope.SPACE,
        )
        self.assertEqual(
            specs[0]["notification_key"],
            "space-201",
        )
        self.assertEqual(
            specs[0]["detail_url"],
            "/proveedor/",
        )

    def test_confirmacion_avisada_solo_al_miembro(self):

        history = self._history(
            SpaceBookingHistory.Action.CONFIRMED,
            changed_by_id=self.provider.pk,
        )

        specs = self._specs(history)

        self.assertEqual(len(specs), 1)
        self.assertEqual(
            specs[0]["recipient"],
            self.member,
        )
        self.assertEqual(
            specs[0]["scope"],
            NotificationEvent.Scope.MEMBER,
        )
        self.assertIn(
            "confirmó",
            specs[0]["title"],
        )

    def test_rechazo_pendiente_identificado_correctamente(self):

        history = self._history(
            SpaceBookingHistory.Action.CANCELLED,
            changed_by_id=self.provider.pk,
            previous_status=SpaceBooking.Status.PENDING,
        )

        specs = self._specs(history)

        self.assertEqual(len(specs), 1)
        self.assertIn(
            "no pudo aceptar",
            specs[0]["title"],
        )
        self.assertEqual(
            specs[0]["recipient"],
            self.member,
        )

    def test_cancelacion_por_miembro_avisa_solo_al_proveedor(self):

        history = self._history(
            SpaceBookingHistory.Action.CANCELLED,
            changed_by_id=self.member.pk,
            previous_status=SpaceBooking.Status.CONFIRMED,
        )

        specs = self._specs(history)

        self.assertEqual(len(specs), 1)
        self.assertEqual(
            specs[0]["recipient"],
            self.provider,
        )
        self.assertIn(
            "Camila",
            specs[0]["title"],
        )

    def test_cancelacion_administrativa_no_culpa_al_proveedor(self):

        history = self._history(
            SpaceBookingHistory.Action.CANCELLED,
            changed_by_id=99,
            previous_status=SpaceBooking.Status.CONFIRMED,
        )

        specs = self._specs(history)

        self.assertEqual(len(specs), 2)

        self.assertEqual(
            {item["scope"] for item in specs},
            {
                NotificationEvent.Scope.MEMBER,
                NotificationEvent.Scope.SPACE,
            },
        )

        self.assertEqual(
            specs[0]["title"],
            "Se canceló tu arriendo",
        )

        self.assertNotIn(
            "Roberto canceló",
            specs[0]["title"],
        )

    def test_completada_notifica_al_miembro(self):

        history = self._history(
            SpaceBookingHistory.Action.COMPLETED,
            changed_by_id=self.provider.pk,
        )

        specs = self._specs(history)

        self.assertEqual(len(specs), 1)
        self.assertIn(
            "completó",
            specs[0]["title"],
        )

    def test_actualizaciones_genericas_no_generan_eventos(self):

        history = self._history(
            SpaceBookingHistory.Action.UPDATED,
            changed_by_id=self.provider.pk,
        )

        self.assertEqual(
            self._specs(history),
            [],
        )

    def test_no_programa_eventos_duplicados_o_cargas_raw(self):

        history = self._history(
            SpaceBookingHistory.Action.CONFIRMED,
            changed_by_id=self.provider.pk,
        )

        with patch(
            f"{MODULE}.transaction.on_commit"
        ) as on_commit:

            space_booking_history_notification(
                sender=SpaceBookingHistory,
                instance=history,
                created=False,
            )

            space_booking_history_notification(
                sender=SpaceBookingHistory,
                instance=history,
                created=True,
                raw=True,
            )

            on_commit.assert_not_called()

    def test_programa_registro_despues_del_commit(self):

        history = self._history(
            SpaceBookingHistory.Action.CREATED,
            changed_by_id=self.member.pk,
        )

        with patch(
            f"{MODULE}.transaction.on_commit"
        ) as on_commit:

            space_booking_history_notification(
                sender=SpaceBookingHistory,
                instance=history,
                created=True,
            )

            on_commit.assert_called_once()

            with patch(
                f"{MODULE}.persist_space_booking_history_notifications"
            ) as persist:

                on_commit.call_args.args[0]()

                persist.assert_called_once_with(
                    history.pk
                )

    def test_persistencia_usa_clave_y_destinatario_autorizados(self):

        history = self._history(
            SpaceBookingHistory.Action.CONFIRMED,
            changed_by_id=self.provider.pk,
        )

        with (
            patch(
                f"{MODULE}.SpaceBookingHistory.objects"
            ) as history_manager,
            patch(
                f"{MODULE}.reverse",
                side_effect=[
                    "/mi-reserva/",
                    "/proveedor/",
                ],
            ),
            patch(
                f"{MODULE}.record_notification_event"
            ) as record,
        ):

            history_manager.select_related.return_value.get.return_value = history

            persist_space_booking_history_notifications(
                history.pk
            )

        record.assert_called_once()

        payload = record.call_args.kwargs

        self.assertEqual(
            payload["recipient"],
            self.member,
        )

        self.assertEqual(
            payload["notification_key"],
            "space-201",
        )

        self.assertEqual(
            payload["category"],
            NotificationEvent.Category.SPACE,
        )