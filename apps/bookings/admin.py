from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    BookingSessionReview,
    BookingSessionIncident,
    BookingIncidentProfessionalResponse,
)


# =====================================================
# V121 - CONFIRMACIONES Y EVALUACIONES DE SESIONES
# =====================================================

@admin.register(BookingSessionReview)
class BookingSessionReviewAdmin(admin.ModelAdmin):

    list_display = (
        'booking',
        'status',
        'rating',
        'expires_at',
        'responded_at',
        'created_at',
    )

    list_filter = (
        'status',
        'rating',
    )

    search_fields = (
        'booking__service_name_snapshot',
        'booking__booked_by__email',
    )

    ordering = (
        '-created_at',
    )

    list_per_page = 25

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

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# =====================================================
# V123 - ADMINISTRACIÓN DE INCIDENCIAS
# =====================================================

@admin.register(BookingSessionIncident)
class BookingSessionIncidentAdmin(admin.ModelAdmin):

    # -------------------------------------------------
    # LISTADO DE INCIDENCIAS
    # -------------------------------------------------

    list_display = (
        'numero_reserva',
        'miembro',
        'profesional',
        'status',
        'assigned_to',
        'resolution_type',
        'created_at',
    )

    list_filter = (
        'status',
        'resolution_type',
        'created_at',
    )

    search_fields = (
        'review__booking__booked_by__email',
        'review__booking__service_name_snapshot',
        'review__booking__professional_profile__user__email',
        'review__issue_reason',
    )

    ordering = ('-created_at',)
    list_per_page = 25

    list_select_related = (
        'review__booking',
        'assigned_to',
    )

    # -------------------------------------------------
    # CAMPOS PROTEGIDOS Y DATOS DE AMBAS PARTES
    # -------------------------------------------------

    readonly_fields = (
        'review',
        'miembro_reportante',
        'motivo_reportado',
        'fecha_reporte_miembro',
        'profesional_que_respondio',
        'declaracion_profesional',
        'fecha_respuesta_profesional',
        'reviewed_at',
        'resolved_at',
        'resolved_by',
        'created_at',
        'updated_at',
    )

    # -------------------------------------------------
    # ORGANIZACIÓN DE LA INVESTIGACIÓN
    # -------------------------------------------------

    fieldsets = (
        (
            'Información de la incidencia',
            {
                'fields': (
                    'review',
                    'status',
                )
            }
        ),
        (
            '01 - Reporte original del Miembro',
            {
                'fields': (
                    'miembro_reportante',
                    'motivo_reportado',
                    'fecha_reporte_miembro',
                )
            }
        ),
        (
            '02 - Antecedentes del Profesional',
            {
                'fields': (
                    'profesional_que_respondio',
                    'declaracion_profesional',
                    'fecha_respuesta_profesional',
                )
            }
        ),
        (
            '03 - Gestión administrativa (privada)',
            {
                'fields': (
                    'assigned_to',
                    'internal_notes',
                    'reviewed_at',
                )
            }
        ),
        (
            '04 - Resolución del problema',
            {
                'fields': (
                    'resolution_type',
                    'resolution_summary',
                    'resolved_by',
                    'resolved_at',
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

    # -------------------------------------------------
    # DATOS DEL LISTADO
    # -------------------------------------------------

    @admin.display(description='Número de reserva')
    def numero_reserva(self, obj):
        return f'#{obj.review.booking_id}'

    @admin.display(description='Miembro')
    def miembro(self, obj):
        user = obj.review.booking.booked_by
        return user.get_full_name() or user.email

    @admin.display(description='Profesional')
    def profesional(self, obj):
        user = obj.review.booking.professional_profile.user
        return user.get_full_name() or user.email

    # -------------------------------------------------
    # REPORTE ORIGINAL DEL MIEMBRO (SOLO LECTURA)
    # -------------------------------------------------

    @admin.display(description='Miembro que reportó')
    def miembro_reportante(self, obj):
        if not obj or not obj.pk:
            return 'Sin información'
        return self.miembro(obj)

    @admin.display(description='Motivo reportado')
    def motivo_reportado(self, obj):
        if not obj or not obj.pk:
            return 'Sin información'
        texto = obj.review.issue_reason or 'Sin motivo registrado'
        return format_html(
            '<div style="white-space: pre-wrap; overflow-wrap: anywhere; '
            'line-height: 1.6; max-width: 900px;">{}</div>',
            texto,
        )

    @admin.display(description='Fecha del reporte del Miembro')
    def fecha_reporte_miembro(self, obj):
        if not obj or not obj.pk or not obj.review.responded_at:
            return 'Sin fecha registrada'
        return timezone.localtime(obj.review.responded_at).strftime(
            '%d/%m/%Y a las %H:%M'
        )

    # -------------------------------------------------
    # RESPUESTA ORIGINAL DEL PROFESIONAL (SOLO LECTURA)
    # -------------------------------------------------

    def _respuesta(self, obj):
        if not obj or not obj.pk:
            return None
        try:
            return obj.professional_response
        except BookingIncidentProfessionalResponse.DoesNotExist:
            return None

    @admin.display(description='Profesional que presentó antecedentes')
    def profesional_que_respondio(self, obj):
        respuesta = self._respuesta(obj)
        if respuesta is None:
            return 'Sin antecedentes presentados'
        usuario = respuesta.submitted_by
        return usuario.get_full_name() or usuario.email

    @admin.display(description='Declaración original del Profesional')
    def declaracion_profesional(self, obj):
        respuesta = self._respuesta(obj)
        if respuesta is None:
            return 'El Profesional todavía no ha presentado su versión.'
        return format_html(
            '<div style="white-space: pre-wrap; overflow-wrap: anywhere; '
            'line-height: 1.6; max-width: 900px;">{}</div>',
            respuesta.statement,
        )

    @admin.display(description='Fecha de presentación de antecedentes')
    def fecha_respuesta_profesional(self, obj):
        respuesta = self._respuesta(obj)
        if respuesta is None:
            return 'Sin fecha registrada'
        return timezone.localtime(respuesta.created_at).strftime(
            '%d/%m/%Y a las %H:%M'
        )

    # -------------------------------------------------
    # OPTIMIZAR CONSULTAS DE LA PÁGINA
    # -------------------------------------------------

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'review__booking__booked_by',
            'review__booking__professional_profile__user',
            'assigned_to',
            'resolved_by',
            'professional_response__submitted_by',
        )

    # -------------------------------------------------
    # REGISTRO AUTOMÁTICO DEL ADMINISTRADOR (CONSERVADO)
    # -------------------------------------------------

    def save_model(self, request, obj, form, change):
        now = timezone.now()

        if obj.status == BookingSessionIncident.Status.IN_REVIEW:
            if obj.reviewed_at is None:
                obj.reviewed_at = now
            if obj.assigned_to_id is None:
                obj.assigned_to = request.user

        if obj.status == BookingSessionIncident.Status.RESOLVED:
            if obj.reviewed_at is None:
                obj.reviewed_at = now
            if obj.resolved_at is None:
                obj.resolved_at = now
            if obj.resolved_by_id is None:
                obj.resolved_by = request.user

        super().save_model(request, obj, form, change)

    # -------------------------------------------------
    # PERMISOS (CONSERVADOS)
    # -------------------------------------------------

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# =====================================================
# V123 - RESPUESTAS PROFESIONALES A INCIDENCIAS
# =====================================================

@admin.register(BookingIncidentProfessionalResponse)
class BookingIncidentProfessionalResponseAdmin(admin.ModelAdmin):

    # -------------------------------------------------
    # LISTADO DE RESPUESTAS
    # -------------------------------------------------

    list_display = (
        'numero_reserva',
        'nombre_profesional',
        'estado_incidencia',
        'created_at',
    )

    list_filter = (
        'created_at',
        'incident__status',
    )

    search_fields = (
        'submitted_by__email',
        'incident__review__booking__service_name_snapshot',
        'incident__review__booking__booked_by__email',
        'statement',
    )

    ordering = (
        '-created_at',
    )

    list_per_page = 25

    # -------------------------------------------------
    # CAMPOS DE SOLO LECTURA
    # -------------------------------------------------

    readonly_fields = (
        'incident',
        'submitted_by',
        'statement',
        'created_at',
    )

    # -------------------------------------------------
    # ORGANIZACIÓN DEL DETALLE
    # -------------------------------------------------

    fieldsets = (

        (
            'Información de la incidencia',
            {
                'fields': (
                    'incident',
                    'submitted_by',
                    'created_at',
                )
            }
        ),

        (
            'Declaración del profesional',
            {
                'fields': (
                    'statement',
                )
            }
        ),

    )

    # -------------------------------------------------
    # INFORMACIÓN DEL LISTADO
    # -------------------------------------------------

    @admin.display(description='Número de reserva')
    def numero_reserva(self, obj):

        return (
            f'#{obj.incident.review.booking_id}'
        )

    @admin.display(description='Profesional')
    def nombre_profesional(self, obj):

        user = obj.submitted_by

        return (
            user.get_full_name()
            or user.email
        )

    @admin.display(description='Estado de la incidencia')
    def estado_incidencia(self, obj):

        return (
            obj.incident.get_status_display()
        )

    # -------------------------------------------------
    # CONSULTAS OPTIMIZADAS
    # -------------------------------------------------

    def get_queryset(self, request):

        queryset = super().get_queryset(request)

        return queryset.select_related(
            'incident',
            'incident__review',
            'incident__review__booking',
            'submitted_by',
        )

    # -------------------------------------------------
    # PERMISOS
    # -------------------------------------------------

    def has_add_permission(self, request):

        # Las declaraciones se presentan desde
        # la cuenta del Profesional.
        return False

    def has_change_permission(self, request, obj=None):

        # No permitir modificar testimonios
        # que ya fueron presentados.
        return False

    def has_delete_permission(self, request, obj=None):

        # Conservar las declaraciones originales
        # como antecedentes administrativos.
        return False