"""
V132.06.5B - Pruebas del comando administrativo de limpieza.

Destino:
apps/professionals/tests_professional_video_cleanup_command_v132065.py

Todas las operaciones de limpieza se simulan.
Estas pruebas NO acceden a Supabase Storage real.
"""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


COMMAND_MODULE = (
    "apps.professionals.management.commands."
    "retry_professional_video_cleanup"
)


class ProfessionalVideoCleanupCommandTests(SimpleTestCase):
    def setUp(self):
        self.output = StringIO()

        filter_patcher = patch(
            f"{COMMAND_MODULE}."
            "ProfessionalVideoStorageCleanup.objects.filter"
        )

        self.mock_filter = filter_patcher.start()
        self.addCleanup(filter_patcher.stop)

        self.mock_filter.return_value.count.return_value = 0

        service_patcher = patch(
            f"{COMMAND_MODULE}.run_pending_remote_video_cleanups"
        )

        self.mock_service = service_patcher.start()
        self.addCleanup(service_patcher.stop)

    def test_default_execution_is_read_only(self):
        """
        Sin --apply no debe ejecutarse ninguna eliminación.
        """

        self.mock_filter.return_value.count.return_value = 3

        call_command(
            "retry_professional_video_cleanup",
            stdout=self.output,
        )

        result = self.output.getvalue()

        self.assertIn(
            "Tareas pendientes: 3",
            result,
        )

        self.assertIn(
            "MODO CONSULTA",
            result,
        )

        self.mock_service.assert_not_called()

    def test_explicit_dry_run_respects_limit(self):
        """
        --dry-run muestra cuántas tareas podrían procesarse.
        """

        self.mock_filter.return_value.count.return_value = 5

        call_command(
            "retry_professional_video_cleanup",
            "--dry-run",
            "--limit",
            "2",
            stdout=self.output,
        )

        result = self.output.getvalue()

        self.assertIn(
            "Limite por ejecucion: 2",
            result,
        )

        self.assertIn(
            "Tareas que podrian procesarse: 2",
            result,
        )

        self.mock_service.assert_not_called()

    def test_apply_processes_pending_tasks(self):
        """
        Solo --apply permite llamar al servicio de limpieza.
        """

        self.mock_filter.return_value.count.side_effect = [
            2,
            0,
        ]

        self.mock_service.return_value = {
            "processed": 2,
            "completed": 2,
            "failed": 0,
        }

        call_command(
            "retry_professional_video_cleanup",
            "--apply",
            "--limit",
            "10",
            stdout=self.output,
        )

        self.mock_service.assert_called_once_with(
            limit=10,
        )

        result = self.output.getvalue()

        self.assertIn(
            "Tareas procesadas: 2",
            result,
        )

        self.assertIn(
            "Eliminaciones completadas: 2",
            result,
        )

        self.assertIn(
            "Tareas pendientes restantes: 0",
            result,
        )

    def test_apply_without_pending_tasks_does_not_call_service(self):
        """
        No debe invocarse el servicio si no hay tareas pendientes.
        """

        self.mock_filter.return_value.count.return_value = 0

        call_command(
            "retry_professional_video_cleanup",
            "--apply",
            stdout=self.output,
        )

        self.assertIn(
            "No hay tareas pendientes",
            self.output.getvalue(),
        )

        self.mock_service.assert_not_called()

    def test_failed_cleanup_reports_error(self):
        """
        Una limpieza fallida debe producir un resultado de error.
        """

        self.mock_filter.return_value.count.side_effect = [
            2,
            1,
        ]

        self.mock_service.return_value = {
            "processed": 2,
            "completed": 1,
            "failed": 1,
        }

        with self.assertRaisesMessage(
            CommandError,
            "Algunas eliminaciones no se completaron",
        ):
            call_command(
                "retry_professional_video_cleanup",
                "--apply",
                stdout=self.output,
            )

        self.mock_service.assert_called_once_with(
            limit=100,
        )

        result = self.output.getvalue()

        self.assertIn(
            "Eliminaciones fallidas: 1",
            result,
        )

        self.assertIn(
            "Tareas pendientes restantes: 1",
            result,
        )

    def test_invalid_limits_are_rejected(self):
        """
        No deben permitirse límites fuera del rango establecido.
        """

        for invalid_limit in (0, -1, 1001):
            with self.subTest(limit=invalid_limit):
                with self.assertRaisesMessage(
                    CommandError,
                    "El límite debe ser un número entre 1 y 1000",
                ):
                    call_command(
                        "retry_professional_video_cleanup",
                        "--limit",
                        str(invalid_limit),
                        stdout=StringIO(),
                    )

        self.mock_service.assert_not_called()

    def test_service_exception_does_not_expose_sensitive_details(self):
        """
        Un error inesperado no debe mostrar secretos
        del proveedor de almacenamiento.
        """

        self.mock_filter.return_value.count.return_value = 1

        self.mock_service.side_effect = RuntimeError(
            "Credencial privada simulada"
        )

        with self.assertRaises(CommandError) as captured:
            call_command(
                "retry_professional_video_cleanup",
                "--apply",
                stdout=self.output,
            )

        error_message = str(captured.exception)

        self.assertIn(
            "RuntimeError",
            error_message,
        )

        self.assertNotIn(
            "Credencial privada simulada",
            error_message,
        )