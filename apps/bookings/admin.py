from django.contrib import admin

from .models import BookingSessionReview


# =====================================================
# V121 - CONFIRMACIONES Y EVALUACIONES DE SESIONES
# =====================================================

@admin.register(BookingSessionReview)
class BookingSessionReviewAdmin(admin.ModelAdmin):

    # Columnas del panel de administración
    list_display = (
        'booking',
        'status',
        'rating',
        'expires_at',
        'responded_at',
        'created_at',
    )

    # Filtros disponibles
    list_filter = (
        'status',
        'rating',
    )

    # Búsqueda de registros
    search_fields = (
        'booking__service_name_snapshot',
        'booking__booked_by__email',
    )

    # Ordenar por fecha de creación
    ordering = (
        '-created_at',
    )

    # Cantidad de registros por página
    list_per_page = 25

    # Campos de solo lectura
    readonly_fields = (
        'booking',
        'status',
        'expires_at',
        'responded_at',
        'issue_reason',
        'rating',
        'rating_comment',
        'rated_at',
        'created_at',
        'updated_at',
    )

    # Organización de la información
    fieldsets = (

        (
            'Información de la sesión',
            {
                'fields': (
                    'booking',
                    'status',
                    'expires_at',
                    'responded_at',
                )
            }
        ),

        (
            'Problemas reportados',
            {
                'fields': (
                    'issue_reason',
                )
            }
        ),

        (
            'Evaluación del miembro',
            {
                'fields': (
                    'rating',
                    'rating_comment',
                    'rated_at',
                )
            }
        ),

        (
            'Registro del sistema',
            {
                'fields': (
                    'created_at',
                    'updated_at',
                )
            }
        ),

    )

    # No permitir crear confirmaciones manualmente
    def has_add_permission(self, request):
        return False

    # No permitir eliminar registros de conformidad
    def has_delete_permission(self, request, obj=None):
        return False