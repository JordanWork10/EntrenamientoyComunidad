"""
V132.06.5B - Recuperación administrativa de videos pendientes de eliminación.

Destino:
apps/professionals/management/commands/retry_professional_video_cleanup.py

Permite consultar y reintentar eliminaciones pendientes en Supabase Storage.

Seguridad:
- Por defecto, el comando solo consulta la base de datos.
- Para ejecutar eliminaciones reales, se requiere --apply.
- Nunca elimina archivos que no estén registrados como pendientes.
- El servicio de limpieza valida la ubicación y el identificador del archivo.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.professionals.models import ProfessionalVideoStorageCleanup
from apps.professionals.video_storage_cleanup_service_v132065 import (
    run_pending_remote_video_cleanups,
)


class Command(BaseCommand):
    help = (
        "Consulta o reintenta las eliminaciones pendientes "
        "del almacenamiento privado de videos profesionales."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help=(
                "Cantidad máxima de tareas pendientes que se procesarán. "
                "Predeterminado: 100."
            ),
        )

        mode = parser.add_mutually_exclusive_group()

        mode.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Consulta las tareas pendientes sin eliminar archivos. "
                "Este es el comportamiento predeterminado."
            ),
        )

        mode.add_argument(
            "--apply",
            action="store_true",
            help=(
                "Autoriza explícitamente el procesamiento de las "
                "eliminaciones pendientes en Supabase Storage."
            ),
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        apply_changes = options["apply"]

        if not 1 <= limit <= 1000:
            raise CommandError(
                "El límite debe ser un número entre 1 y 1000."
            )

        pending_tasks = ProfessionalVideoStorageCleanup.objects.filter(
            status=ProfessionalVideoStorageCleanup.Status.PENDING
        )

        pending_count = pending_tasks.count()

        self.stdout.write("")
        self.stdout.write(
            "==============================================="
        )
        self.stdout.write(
            " LIMPIEZA DE VIDEOS PROFESIONALES - V132.06.5B"
        )
        self.stdout.write(
            "==============================================="
        )
        self.stdout.write("")

        self.stdout.write(
            f"Tareas pendientes: {pending_count}"
        )
        self.stdout.write(
            f"Limite por ejecucion: {limit}"
        )
        self.stdout.write("")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    "MODO CONSULTA: no se eliminara ningun archivo."
                )
            )

            if pending_count == 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        "No existen eliminaciones pendientes."
                    )
                )
            else:
                self.stdout.write(
                    f"Tareas que podrian procesarse: "
                    f"{min(pending_count, limit)}"
                )

                self.stdout.write(
                    "Para procesarlas se requiere ejecutar "
                    "el comando con --apply."
                )

            self.stdout.write("")
            return

        if pending_count == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "No hay tareas pendientes para procesar."
                )
            )
            self.stdout.write("")
            return

        self.stdout.write(
            self.style.WARNING(
                "MODO EJECUCION: procesando eliminaciones pendientes."
            )
        )

        try:
            results = run_pending_remote_video_cleanups(
                limit=limit
            )
        except Exception as exc:
            raise CommandError(
                "No se pudo completar el proceso de limpieza. "
                f"Tipo de error: {type(exc).__name__}"
            ) from exc

        processed = results.get("processed", 0)
        completed = results.get("completed", 0)
        failed = results.get("failed", 0)

        self.stdout.write("")
        self.stdout.write("RESULTADO")
        self.stdout.write("-------------------------------")

        self.stdout.write(
            f"Tareas procesadas: {processed}"
        )
        self.stdout.write(
            f"Eliminaciones completadas: {completed}"
        )
        self.stdout.write(
            f"Eliminaciones fallidas: {failed}"
        )

        remaining = ProfessionalVideoStorageCleanup.objects.filter(
            status=ProfessionalVideoStorageCleanup.Status.PENDING
        ).count()

        self.stdout.write(
            f"Tareas pendientes restantes: {remaining}"
        )
        self.stdout.write("")

        if failed:
            raise CommandError(
                "Algunas eliminaciones no se completaron. "
                "Las tareas fallidas permanecen registradas "
                "para un nuevo intento."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Proceso de limpieza finalizado correctamente."
            )
        )