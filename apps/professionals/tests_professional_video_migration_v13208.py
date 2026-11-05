"""
V132.08B - Pruebas de migración segura de videos locales a Supabase.

Destino:
apps/professionals/tests_professional_video_migration_v13208.py

Objetivos:
- Comprobar que --dry-run no modifica datos.
- Migrar únicamente el video seleccionado.
- Conservar metadatos y archivos locales originales.
- Evitar migraciones de archivos inexistentes o inconsistentes.
- Impedir que una subida fallida publique un objeto remoto inválido.
- Comprobar que los errores no pierden las referencias locales.

IMPORTANTE:
Todas las operaciones S3 se simulan mediante mocks.
No se establece conexión con Supabase.
"""

import os
import tempfile

from io import StringIO
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalSpecialty,
)

from .video_models_v13200 import ProfessionalPortfolioVideo
from .video_storage_v13201 import PrivatePortfolioStorage


FAKE_S3_ENV = {
    "SUPABASE_VIDEO_S3_BUCKET": "portafolio-pruebas",
    "SUPABASE_VIDEO_S3_ENDPOINT": (
        "https://ejemplo.storage.supabase.co/storage/v1/s3"
    ),
    "SUPABASE_VIDEO_S3_REGION": "us-east-1",
    "SUPABASE_VIDEO_S3_ACCESS_KEY": "clave-falsa-pruebas",
    "SUPABASE_VIDEO_S3_SECRET_KEY": "secreto-falso-pruebas",
}


@override_settings(
    PROFESSIONAL_VIDEO_STORAGE_MODE="supabase",
)
class ProfessionalVideoMigrationV13208Tests(TestCase):

    @classmethod
    def setUpTestData(cls):

        User = get_user_model()

        cls.owner = User.objects.create_user(
            username="migration_owner_v13208",
            email="migration_owner_v13208@example.test",
            password="test-password",
        )

        category = ProfessionalCategory.objects.create(
            name="Migración audiovisual V13208",
            slug="migracion-audiovisual-v13208",
        )

        specialty = ProfessionalSpecialty.objects.create(
            category=category,
            name="Pruebas de portafolio",
            slug="pruebas-portafolio-v13208",
        )

        cls.profile = ProfessionalProfile.objects.create(
            user=cls.owner,
            category=category,
            specialty=specialty,
            verification_status=(
                ProfessionalProfile.VerificationStatus.VERIFIED
            ),
            bio="Perfil utilizado exclusivamente para pruebas.",
        )

    def setUp(self):

        # Configuración S3 completamente ficticia.
        env_patch = patch.dict(
            os.environ,
            FAKE_S3_ENV,
        )

        env_patch.start()
        self.addCleanup(env_patch.stop)

        # Almacenamiento temporal.
        self.private_directory = tempfile.TemporaryDirectory()

        self.addCleanup(
            self.private_directory.cleanup
        )

        storage_settings = override_settings(
            PROFESSIONAL_VIDEO_PRIVATE_ROOT=(
                self.private_directory.name
            ),
        )

        storage_settings.enable()
        self.addCleanup(storage_settings.disable)

        # Aislar los archivos del almacenamiento real.
        self.field = ProfessionalPortfolioVideo._meta.get_field(
            "video_file"
        )

        self.original_storage = self.field.storage

        self.field.storage = PrivatePortfolioStorage()

        self.addCleanup(
            setattr,
            self.field,
            "storage",
            self.original_storage,
        )

        # Simular el adaptador remoto.
        adapter_patch = patch(
            "apps.professionals.video_supabase_s3_adapter_v13206."
            "SupabaseVideoS3Adapter.from_settings"
        )

        adapter_factory = adapter_patch.start()

        self.addCleanup(adapter_patch.stop)

        self.adapter_factory = adapter_factory

        self.adapter = Mock()

        self.adapter.bucket = "portafolio-pruebas"

        adapter_factory.return_value = self.adapter

        self.payload = (
            b"\x00\x00\x00\x18ftypisom"
            + b"0" * 1024
        )

        self.expected_size = len(self.payload)

        self.adapter.new_key.side_effect = (
            lambda *,
            professional_profile_id,
            extension: (
                f"professional_videos/"
                f"{professional_profile_id}/"
                f"{'a' * 32}{extension}"
            )
        )

        self.adapter.head.return_value = {
            "size_bytes": self.expected_size,
            "content_type": "video/mp4",
        }

    def create_local_video(self, title="Video de prueba"):

        video = ProfessionalPortfolioVideo(
            professional_profile=self.profile,
            title=title,
            description="Contenido demostrativo de pruebas.",
            category=(
                ProfessionalPortfolioVideo.Category.PRESENTATION
            ),
            status=(
                ProfessionalPortfolioVideo.Status.APPROVED
            ),
            storage_backend=(
                ProfessionalPortfolioVideo.StorageBackend.LOCAL
            ),
            duration_seconds=12,
            rights_confirmed=True,
            is_featured=False,
        )

        video.video_file.save(
            "video_prueba.mp4",
            ContentFile(self.payload),
            save=False,
        )

        video.file_size_bytes = video.video_file.size

        video.full_clean()
        video.save()

        return video

    def execute_command(self, *arguments):

        output = StringIO()
        errors = StringIO()

        call_command(
            "migrate_professional_videos_v13208",
            *arguments,
            stdout=output,
            stderr=errors,
        )

        return output.getvalue() + errors.getvalue()

    def test_01_dry_run_does_not_modify_database(self):

        video = self.create_local_video()

        original_key = video.video_file.name

        result = self.execute_command("--dry-run")

        video.refresh_from_db()

        self.assertEqual(
            video.storage_backend,
            ProfessionalPortfolioVideo.StorageBackend.LOCAL,
        )

        self.assertEqual(
            video.external_asset_id,
            "",
        )

        self.assertEqual(
            video.video_file.name,
            original_key,
        )

        self.assertTrue(
            video.video_file.storage.exists(original_key)
        )

        self.assertIn(
            "APTO PARA MIGRACION",
            result,
        )

        self.adapter_factory.assert_not_called()

        self.adapter.upload.assert_not_called()

    def test_02_apply_migrates_only_selected_video(self):

        first = self.create_local_video(
            "Primer video"
        )

        second = self.create_local_video(
            "Segundo video"
        )

        original_file = first.video_file.name

        original_public_id = first.public_id

        original_title = first.title

        original_description = first.description

        original_duration = first.duration_seconds

        original_size = first.file_size_bytes

        self.execute_command(
            "--apply",
            "--video-id",
            str(first.pk),
        )

        first.refresh_from_db()
        second.refresh_from_db()

        # El registro original se conserva.
        self.assertEqual(
            first.public_id,
            original_public_id,
        )

        self.assertEqual(
            first.title,
            original_title,
        )

        self.assertEqual(
            first.description,
            original_description,
        )

        self.assertEqual(
            first.duration_seconds,
            original_duration,
        )

        self.assertEqual(
            first.file_size_bytes,
            original_size,
        )

        self.assertEqual(
            first.status,
            ProfessionalPortfolioVideo.Status.APPROVED,
        )

        # El backend cambia a remoto.
        self.assertEqual(
            first.storage_backend,
            ProfessionalPortfolioVideo.StorageBackend.EXTERNAL,
        )

        self.assertEqual(
            first.external_asset_id,
            (
                f"professional_videos/"
                f"{self.profile.pk}/"
                f"{'a' * 32}.mp4"
            ),
        )

        # El respaldo local permanece disponible.
        self.assertEqual(
            first.video_file.name,
            original_file,
        )

        self.assertTrue(
            first.video_file.storage.exists(original_file)
        )

        # El segundo video permanece intacto.
        self.assertEqual(
            second.storage_backend,
            ProfessionalPortfolioVideo.StorageBackend.LOCAL,
        )

        self.assertEqual(
            second.external_asset_id,
            "",
        )

        self.assertEqual(
            ProfessionalPortfolioVideo.objects.count(),
            2,
        )

        self.adapter.upload.assert_called_once()

        self.adapter.head.assert_called_once()

        self.adapter.delete.assert_not_called()

    def test_03_migrated_video_is_not_selected_again(self):

        video = self.create_local_video()

        self.execute_command(
            "--apply",
            "--video-id",
            str(video.pk),
        )

        self.adapter.upload.assert_called_once()

        result = self.execute_command("--dry-run")

        self.assertIn(
            "Videos locales encontrados: 0",
            result,
        )

        # La consulta posterior no genera otra subida.
        self.adapter.upload.assert_called_once()

        self.assertEqual(
            ProfessionalPortfolioVideo.objects.count(),
            1,
        )

    def test_04_missing_local_file_is_not_migrated(self):

        video = self.create_local_video()

        video.video_file.name = (
            f"professional_videos/"
            f"{self.profile.pk}/"
            f"{'b' * 32}.mp4"
        )

        video.save(update_fields=["video_file"])

        result = self.execute_command("--dry-run")

        video.refresh_from_db()

        self.assertEqual(
            video.storage_backend,
            ProfessionalPortfolioVideo.StorageBackend.LOCAL,
        )

        self.assertEqual(
            video.external_asset_id,
            "",
        )

        self.assertNotIn(
            "Resultado: APTO PARA MIGRACION",
            result,
        )

        self.adapter_factory.assert_not_called()

    def test_05_incorrect_file_size_is_rejected(self):

        video = self.create_local_video()

        video.file_size_bytes += 100

        video.save(
            update_fields=["file_size_bytes"]
        )

        result = self.execute_command("--dry-run")

        video.refresh_from_db()

        self.assertEqual(
            video.storage_backend,
            ProfessionalPortfolioVideo.StorageBackend.LOCAL,
        )

        self.assertEqual(
            video.external_asset_id,
            "",
        )

        self.assertNotIn(
            "Resultado: APTO PARA MIGRACION",
            result,
        )

        self.adapter_factory.assert_not_called()

    def test_06_remote_size_mismatch_preserves_local_video(self):

        video = self.create_local_video()

        original_file = video.video_file.name

        self.adapter.head.return_value = {
            "size_bytes": self.expected_size + 500,
            "content_type": "video/mp4",
        }

        try:
            self.execute_command(
                "--apply",
                "--video-id",
                str(video.pk),
            )
        except CommandError:
            pass

        video.refresh_from_db()

        # La migración fallida no cambia el backend.
        self.assertEqual(
            video.storage_backend,
            ProfessionalPortfolioVideo.StorageBackend.LOCAL,
        )

        self.assertEqual(
            video.external_asset_id,
            "",
        )

        # El respaldo local continúa existiendo.
        self.assertTrue(
            video.video_file.storage.exists(original_file)
        )

        self.adapter.upload.assert_called_once()
        self.adapter.head.assert_called_once()

    def test_07_upload_error_preserves_original_video(self):

        video = self.create_local_video()

        original_file = video.video_file.name

        self.adapter.upload.side_effect = RuntimeError(
            "Fallo S3 simulado"
        )

        try:
            self.execute_command(
                "--apply",
                "--video-id",
                str(video.pk),
            )
        except CommandError:
            pass

        video.refresh_from_db()

        self.assertEqual(
            video.storage_backend,
            ProfessionalPortfolioVideo.StorageBackend.LOCAL,
        )

        self.assertEqual(
            video.external_asset_id,
            "",
        )

        self.assertTrue(
            video.video_file.storage.exists(original_file)
        )

        self.assertEqual(
            ProfessionalPortfolioVideo.objects.count(),
            1,
        )

        self.adapter.upload.assert_called_once()