"""
V132.07B - Supervisión administrativa de limpiezas de videos.

Destino:
apps/professionals/video_cleanup_admin_v13207.py

Permite supervisar desde Django Admin:

- Eliminaciones pendientes.
- Eliminaciones completadas.
- Profesional asociado.
- Intentos realizados.
- Errores de almacenamiento.
- Fechas e identificadores de archivos.

SEGURIDAD:
- Acceso exclusivo para superusuarios.
- Todos los campos son de solo lectura.
- No permite crear, modificar ni eliminar registros.
- No ejecuta operaciones sobre Supabase Storage.
"""

from django.contrib import admin

from .models import ProfessionalVideoStorageCleanup


@admin.register(ProfessionalVideoStorageCleanup)
class ProfessionalVideoStorageCleanupAdmin(admin.ModelAdmin):
    """
    Registro administrativo de las operaciones de limpieza.

    Esta interfaz es exclusivamente informativa.
    """

    list_display = (
        "id",
        "professional_profile_id_snapshot",
        "file_name",
        "reason",
        "status",
        "attempts",
        "error_display",
        "created_at",
        "completed_at",
    )

    list_display_links = (
        "id",
    )

    list_filter = (
        "status",
        "reason",
        "created_at",
    )

    search_fields = (
        "remote_key",
    )

    ordering = (
        "-created_at",
    )

    date_hierarchy = "created_at"

    list_per_page = 50

    actions = ()

    @admin.display(
        description="Archivo",
    )
    def file_name(self, obj):
        """
        Muestra el nombre del archivo y no la ruta completa.
        """

        if not obj.remote_key:
            return "Sin archivo"

        return obj.remote_key.rsplit("/", 1)[-1]

    @admin.display(
        description="Último error",
    )
    def error_display(self, obj):
        """
        Muestra el último error registrado por el servicio.
        """

        return obj.last_error or "Sin errores"

    def get_readonly_fields(self, request, obj=None):
        """
        Todos los campos del modelo son de solo lectura.
        """

        return tuple(
            field.name
            for field in self.model._meta.concrete_fields
        )

    def has_module_permission(self, request):
        """
        Solo los superusuarios pueden ver este módulo.
        """

        return bool(
            request.user.is_active
            and request.user.is_staff
            and request.user.is_superuser
        )

    def has_view_permission(self, request, obj=None):
        """
        Solo los superusuarios pueden consultar registros.
        """

        return bool(
            request.user.is_active
            and request.user.is_staff
            and request.user.is_superuser
        )

    def has_add_permission(self, request):
        """
        Los registros deben generarse automáticamente.
        """

        return False

    def has_change_permission(self, request, obj=None):
        """
        No se permite modificar el historial de limpieza.
        """

        return False

    def has_delete_permission(self, request, obj=None):
        """
        No se permite eliminar registros de auditoría.
        """

        return False