"""
V132.08 - Migración segura de videos profesionales a Supabase.

Destino:
apps/professionals/management/commands/
migrate_professional_videos_v13208.py

Objetivo:
Migrar videos antiguos desde almacenamiento local privado
hacia Supabase Storage, conservando sus registros originales.

Seguridad:
- El modo predeterminado es --dry-run.
- --apply requiere indicar un video mediante --video-id.
- Solo se migran videos publicados.
- No se eliminan los archivos locales.
- No se crean registros adicionales de videos.
- Se comprueba tamaño y tipo del archivo remoto.
- Las modificaciones de base de datos son transaccionales.
- Si falla una subida, se intenta registrar su limpieza.
"""

from pathlib import Path

from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.db import transaction

from apps.professionals.video_models_v13200 import (
    ProfessionalPortfolioVideo,
)

from apps.professionals.video_storage_cleanup_models_v132065 import (
    ProfessionalVideoStorageCleanup,
)

from apps.professionals.video_storage_cleanup_service_v132065 import (
    queue_remote_video_cleanup,
    run_remote_video_cleanup,
)

from apps.professionals.video_supabase_s3_adapter_v13206 import (
    SupabaseVideoS3Adapter,
)


CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def validate_local_video(video):
    """
    Comprueba que un video puede migrarse.

    Esta función solo consulta información.
    No modifica archivos ni registros.
    """

    if (
        video.storage_backend
        != ProfessionalPortfolioVideo.StorageBackend.LOCAL
    ):
        raise ValueError(
            "El video no utiliza almacenamiento local."
        )

    if (
        video.status
        != ProfessionalPortfolioVideo.Status.APPROVED
    ):
        raise ValueError(
            "Solo se migran videos publicados."
        )

    if video.external_asset_id:
        raise ValueError(
            "El video ya tiene un identificador remoto. "
            "Requiere revisión manual."
        )

    if not video.video_file:
        raise ValueError(
            "El video no tiene un archivo local asociado."
        )

    if not video.rights_confirmed:
        raise ValueError(
            "El video no tiene confirmados los derechos."
        )

    if not video.duration_seconds or video.duration_seconds <= 0:
        raise ValueError(
            "La duración del video es inválida."
        )

    filename = video.video_file.name

    extension = Path(filename).suffix.lower()

    if extension not in CONTENT_TYPES:
        raise ValueError(
            "El formato del archivo no es compatible con Supabase."
        )

    storage = video.video_file.storage

    if not storage.exists(filename):
        raise ValueError(
            "El archivo local no existe."
        )

    actual_size = storage.size(filename)

    if actual_size <= 0:
        raise ValueError(
            "El archivo local está vacío."
        )

    if actual_size != video.file_size_bytes:
        raise ValueError(
            "El tamaño local no coincide con "
            "los metadatos registrados."
        )

    return {
        "filename": filename,
        "extension": extension,
        "size_bytes": actual_size,
        "content_type": CONTENT_TYPES[extension],
    }


class Command(BaseCommand):

    help = (
        "Migra videos profesionales publicados "
        "desde almacenamiento local a Supabase Storage."
    )

    def add_arguments(self, parser):

        parser.add_argument(
            "--video-id",
            type=int,
            default=None,
            help="ID del video que se desea revisar o migrar.",
        )

        modes = parser.add_mutually_exclusive_group()

        modes.add_argument(
            "--dry-run",
            action="store_true",
            help="Consulta los videos sin modificar información.",
        )

        modes.add_argument(
            "--apply",
            action="store_true",
            help="Autoriza la migración del video seleccionado.",
        )

    def handle(self, *args, **options):

        video_id = options["video_id"]
        apply_changes = options["apply"]

        if video_id is not None and video_id <= 0:
            raise CommandError(
                "El identificador del video debe ser positivo."
            )

        self.stdout.write("")
        self.stdout.write(
            "==============================================="
        )
        self.stdout.write(
            " MIGRACION DE VIDEOS PROFESIONALES - V132.08"
        )
        self.stdout.write(
            "==============================================="
        )
        self.stdout.write("")

        if not apply_changes:
            self.show_dry_run(video_id)
            return

        if video_id is None:
            raise CommandError(
                "Para utilizar --apply debes indicar --video-id."
            )

        self.migrate_video(video_id)

    def show_dry_run(self, video_id=None):
        """
        Muestra los videos locales sin efectuar cambios.
        """

        queryset = (
            ProfessionalPortfolioVideo.objects
            .filter(
                storage_backend=(
                    ProfessionalPortfolioVideo.StorageBackend.LOCAL
                )
            )
            .order_by("pk")
        )

        if video_id is not None:
            queryset = queryset.filter(pk=video_id)

        self.stdout.write(
            self.style.WARNING(
                "MODO CONSULTA: no se modificaran videos."
            )
        )

        self.stdout.write("")

        count = 0
        eligible = 0

        for video in queryset:

            count += 1

            self.stdout.write(
                f"VIDEO ID: {video.pk}"
            )

            self.stdout.write(
                f"Titulo: {video.title}"
            )

            self.stdout.write(
                f"Estado: {video.status}"
            )

            self.stdout.write(
                f"Profesional: {video.professional_profile_id}"
            )

            try:

                details = validate_local_video(video)

                eligible += 1

                self.stdout.write(
                    f"Archivo: {details['filename']}"
                )

                self.stdout.write(
                    f"Tamano: {details['size_bytes']} bytes"
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        "Resultado: APTO PARA MIGRACION"
                    )
                )

            except Exception as exc:

                self.stdout.write(
                    self.style.ERROR(
                        "Resultado: NO APTO - "
                        f"{type(exc).__name__}: {exc}"
                    )
                )

            self.stdout.write(
                "-----------------------------------------------"
            )

        self.stdout.write("")

        self.stdout.write(
            f"Videos locales encontrados: {count}"
        )

        self.stdout.write(
            f"Videos aptos: {eligible}"
        )

        self.stdout.write("")
        self.stdout.write(
            "No se realizaron cambios en la base de datos."
        )

    def migrate_video(self, video_id):
        """
        Migra un único video.

        Mantiene el bloqueo de su registro mientras se sube
        y verifica el archivo, para impedir cambios concurrentes
        sobre el mismo video durante esta operación.
        """

        try:
            adapter = SupabaseVideoS3Adapter.from_settings()

        except Exception as exc:
            raise CommandError(
                "No se pudo inicializar Supabase Storage. "
                f"Error: {type(exc).__name__}"
            ) from exc

        remote_key = None
        professional_profile_id = None
        upload_attempted = False

        try:

            with transaction.atomic():

                try:
                    video = (
                        ProfessionalPortfolioVideo.objects
                        .select_for_update()
                        .get(pk=video_id)
                    )

                except ProfessionalPortfolioVideo.DoesNotExist:
                    raise CommandError(
                        "El video indicado no existe."
                    )

                details = validate_local_video(video)

                professional_profile_id = (
                    video.professional_profile_id
                )

                remote_key = adapter.new_key(
                    professional_profile_id=professional_profile_id,
                    extension=details["extension"],
                )

                self.stdout.write(
                    f"Migrando video ID {video.pk}..."
                )

                # -------------------------------------------------
                # COPIAR EL ARCHIVO LOCAL A SUPABASE
                # -------------------------------------------------

                with video.video_file.storage.open(
                    details["filename"],
                    "rb",
                ) as source:

                    upload_attempted = True

                    adapter.upload(
                        key=remote_key,
                        professional_profile_id=professional_profile_id,
                        fileobj=source,
                    )

                # -------------------------------------------------
                # VERIFICAR EL ARCHIVO REMOTO
                # -------------------------------------------------

                remote = adapter.head(
                    key=remote_key,
                    professional_profile_id=professional_profile_id,
                )

                if (
                    remote["size_bytes"]
                    != details["size_bytes"]
                ):
                    raise ValueError(
                        "El tamaño remoto no coincide "
                        "con el archivo original."
                    )

                if (
                    remote["content_type"]
                    != details["content_type"]
                ):
                    raise ValueError(
                        "El formato remoto no coincide "
                        "con el archivo original."
                    )

                # -------------------------------------------------
                # ACTUALIZAR EL REGISTRO EXISTENTE
                # -------------------------------------------------

                video.storage_backend = (
                    ProfessionalPortfolioVideo.StorageBackend.EXTERNAL
                )

                video.external_asset_id = remote_key

                # NO se modifica video_file:
                # el archivo local se conserva como respaldo.

                video.full_clean()

                video.save(
                    update_fields=[
                        "storage_backend",
                        "external_asset_id",
                        "updated_at",
                    ]
                )

            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Video {video_id} migrado correctamente."
                )
            )

            self.stdout.write(
                "El archivo local original se conservo."
            )

            self.stdout.write(
                "Los metadatos y el estado publicado no cambiaron."
            )

        except Exception as exc:

            if upload_attempted and remote_key:

                # Antes de limpiar, comprobar que el objeto
                # no haya quedado enlazado correctamente.
                try:
                    linked = (
                        ProfessionalPortfolioVideo.objects
                        .filter(
                            pk=video_id,
                            storage_backend=(
                                ProfessionalPortfolioVideo
                                .StorageBackend.EXTERNAL
                            ),
                            external_asset_id=remote_key,
                        )
                        .exists()
                    )

                except Exception as verify_exc:
                    raise CommandError(
                        "La migracion fallo y no se pudo comprobar "
                        "el estado final del registro. "
                        "No se ejecutara una eliminacion remota "
                        "hasta revisar el incidente. "
                        f"Clave para auditoria: {remote_key}"
                    ) from verify_exc

                if linked:
                    raise CommandError(
                        "El registro parece haber quedado enlazado "
                        "al objeto remoto. No se realizara limpieza "
                        "automatica; verifica el video manualmente."
                    ) from exc

                try:

                    with transaction.atomic():

                        task = queue_remote_video_cleanup(
                            professional_profile_id=professional_profile_id,
                            remote_key=remote_key,
                            reason=(
                                ProfessionalVideoStorageCleanup
                                .Reason.FAILED_UPLOAD
                            ),
                        )

                    # Intentar retirar el objeto solo después
                    # de guardar la tarea de auditoría.
                    try:
                        completed = run_remote_video_cleanup(
                            task.pk
                        )

                    except Exception:
                        completed = False

                except Exception as cleanup_exc:
                    raise CommandError(
                        "La migracion fallo y no se pudo registrar "
                        "la limpieza del objeto remoto. "
                        "El archivo local permanece intacto. "
                        f"Clave para auditoria: {remote_key}"
                    ) from cleanup_exc

                if completed:
                    raise CommandError(
                        "La migracion fallo. El objeto remoto "
                        "se limpio correctamente y el archivo "
                        "local permanece disponible."
                    ) from exc

                raise CommandError(
                    "La migracion fallo y se registro una tarea "
                    "de limpieza pendiente. "
                    f"ID de tarea: {task.pk}"
                ) from exc

            if isinstance(exc, CommandError):
                raise

            raise CommandError(
                "No se pudo migrar el video. "
                f"Tipo de error: {type(exc).__name__}"
            ) from exc