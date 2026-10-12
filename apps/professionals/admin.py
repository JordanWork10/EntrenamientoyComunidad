from django import forms
from django.contrib import admin, messages
from django.utils import timezone

from .models import (
    ProfessionalCategory,
    ProfessionalCredential,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalSpecialty,
)


# =========================================================
# FORMULARIO ADMIN - PERFIL PROFESIONAL
# =========================================================

class ProfessionalProfileAdminForm(forms.ModelForm):
    """
    Validaciones administrativas para evitar
    estados inconsistentes en un Perfil Profesional.
    """

    class Meta:
        model = ProfessionalProfile
        fields = '__all__'

    def clean(self):

        cleaned_data = super().clean()

        verification_status = cleaned_data.get(
            'verification_status'
        )

        rejection_reason = (
            cleaned_data.get(
                'rejection_reason'
            )
            or ''
        ).strip()

        # -------------------------------------------------
        # RECHAZO
        # -------------------------------------------------

        if (
            verification_status
            == ProfessionalProfile
            .VerificationStatus
            .REJECTED
            and not rejection_reason
        ):

            self.add_error(
                'rejection_reason',
                (
                    'Debes indicar el motivo por el cual '
                    'el Perfil Profesional fue rechazado.'
                )
            )

        # -------------------------------------------------
        # VERIFICACIÓN
        # -------------------------------------------------

        if (
            verification_status
            == ProfessionalProfile
            .VerificationStatus
            .VERIFIED
        ):

            if not self.instance.pk:

                self.add_error(
                    'verification_status',
                    (
                        'El Perfil Profesional debe existir '
                        'antes de poder verificarse.'
                    )
                )

            else:

                has_verified_credential = (
                    self.instance
                    .credentials
                    .filter(
                        review_status=(
                            ProfessionalCredential
                            .ReviewStatus
                            .VERIFIED
                        )
                    )
                    .exists()
                )

                if not has_verified_credential:

                    self.add_error(
                        'verification_status',
                        (
                            'No puedes verificar este Perfil '
                            'Profesional hasta que tenga al menos '
                            'una acreditación verificada.'
                        )
                    )

            # Al aprobar ya no debe quedar
            # un motivo de rechazo anterior.
            cleaned_data[
                'rejection_reason'
            ] = ''

        # -------------------------------------------------
        # VOLVER A PENDIENTE
        # -------------------------------------------------

        if (
            verification_status
            == ProfessionalProfile
            .VerificationStatus
            .PENDING
        ):

            cleaned_data[
                'rejection_reason'
            ] = ''

        return cleaned_data


# =========================================================
# FORMULARIO ADMIN - ACREDITACIÓN
# =========================================================

class ProfessionalCredentialAdminForm(forms.ModelForm):
    """
    Validaciones administrativas para la revisión
    de documentos profesionales.
    """

    class Meta:
        model = ProfessionalCredential
        fields = '__all__'

    def clean(self):

        cleaned_data = super().clean()

        review_status = cleaned_data.get(
            'review_status'
        )

        rejection_reason = (
            cleaned_data.get(
                'rejection_reason'
            )
            or ''
        ).strip()

        # -------------------------------------------------
        # RECHAZO
        # -------------------------------------------------

        if (
            review_status
            == ProfessionalCredential
            .ReviewStatus
            .REJECTED
            and not rejection_reason
        ):

            self.add_error(
                'rejection_reason',
                (
                    'Debes indicar el motivo por el cual '
                    'la acreditación fue rechazada.'
                )
            )

        # -------------------------------------------------
        # LIMPIAR MOTIVO ANTIGUO
        # -------------------------------------------------

        if review_status in (
            ProfessionalCredential
            .ReviewStatus
            .PENDING,

            ProfessionalCredential
            .ReviewStatus
            .VERIFIED,
        ):

            cleaned_data[
                'rejection_reason'
            ] = ''

        return cleaned_data


# =========================================================
# CATEGORÍAS
# =========================================================

@admin.register(ProfessionalCategory)
class ProfessionalCategoryAdmin(admin.ModelAdmin):

    list_display = (
        'name',
        'slug',
        'display_order',
        'is_active',
    )

    search_fields = (
        'name',
        'slug',
    )

    list_filter = (
        'is_active',
    )

    ordering = (
        'display_order',
        'name',
    )


# =========================================================
# ESPECIALIDADES
# =========================================================

@admin.register(ProfessionalSpecialty)
class ProfessionalSpecialtyAdmin(admin.ModelAdmin):

    list_display = (
        'name',
        'category',
        'display_order',
        'is_active',
    )

    search_fields = (
        'name',
        'slug',
        'category__name',
    )

    list_filter = (
        'category',
        'is_active',
    )

    ordering = (
        'category__display_order',
        'display_order',
        'name',
    )

    autocomplete_fields = (
        'category',
    )


# =========================================================
# ACREDITACIONES DENTRO DEL PERFIL
# =========================================================

class ProfessionalCredentialInline(admin.TabularInline):
    """
    Las acreditaciones se muestran dentro del perfil,
    pero su revisión se realiza desde su propia ficha.

    De esta forma el administrador debe abrir el documento
    y revisar la acreditación antes de cambiar su estado.
    """

    model = ProfessionalCredential

    extra = 0

    fields = (
        'credential_type',
        'name',
        'issuing_institution',
        'review_status',
        'created_at',
    )

    readonly_fields = (
        'credential_type',
        'name',
        'issuing_institution',
        'review_status',
        'created_at',
    )

    show_change_link = True

    can_delete = False

    def has_add_permission(
        self,
        request,
        obj=None
    ):
        return False


# =========================================================
# PERFIL PROFESIONAL
# =========================================================

@admin.register(ProfessionalProfile)
class ProfessionalProfileAdmin(admin.ModelAdmin):

    form = ProfessionalProfileAdminForm

    list_display = (
        'user',
        'category',
        'specialty',
        'years_experience',
        'verification_status',
        'is_public',
        'reviewed_by',
        'requested_at',
    )

    search_fields = (
        'user__first_name',
        'user__last_name',
        'user__email',
        'user__rut',
        'professional_title',
        'bio',
        'category__name',
        'specialty__name',
    )

    list_filter = (
        'verification_status',
        'is_public',
        'offers_in_person',
        'offers_online',
        'category',
        'requested_at',
    )

    autocomplete_fields = (
        'user',
        'category',
        'specialty',
        'coverage_communes',
    )

    filter_horizontal = (
        'coverage_communes',
    )

    readonly_fields = (
        'is_public',
        'reviewed_at',
        'reviewed_by',
        'requested_at',
        'updated_at',
    )

    fieldsets = (
        (
            'Cuenta asociada',
            {
                'fields': (
                    'user',
                )
            },
        ),

        (
            'Información profesional',
            {
                'fields': (
                    'category',
                    'specialty',
                    'professional_title',
                    'years_experience',
                    'bio',
                )
            },
        ),

        (
            'Modalidad y cobertura',
            {
                'fields': (
                    'offers_in_person',
                    'offers_online',
                    'coverage_communes',
                )
            },
        ),

        (
            'Verificación administrativa',
            {
                'fields': (
                    'verification_status',
                    'rejection_reason',
                    'is_public',
                    'reviewed_at',
                    'reviewed_by',
                )
            },
        ),

        (
            'Sistema',
            {
                'fields': (
                    'requested_at',
                    'updated_at',
                )
            },
        ),
    )

    inlines = (
        ProfessionalCredentialInline,
    )

    def has_add_permission(
        self,
        request
    ):
        """
        Los Perfiles Profesionales deben originarse
        mediante una solicitud del usuario.
        """

        return False

    def save_model(
        self,
        request,
        obj,
        form,
        change
    ):
        """
        Gestiona automáticamente publicación,
        administrador revisor y fecha de revisión.
        """

        previous_status = None

        if change and obj.pk:

            previous_status = (
                ProfessionalProfile.objects
                .filter(
                    pk=obj.pk
                )
                .values_list(
                    'verification_status',
                    flat=True,
                )
                .first()
            )

        status_changed = (
            previous_status
            != obj.verification_status
        )

        # -------------------------------------------------
        # PERFIL VERIFICADO
        # -------------------------------------------------

        if (
            obj.verification_status
            == ProfessionalProfile
            .VerificationStatus
            .VERIFIED
        ):

            obj.is_public = True

            obj.rejection_reason = ''

        # -------------------------------------------------
        # CUALQUIER OTRO ESTADO
        # -------------------------------------------------

        else:

            obj.is_public = False

        # -------------------------------------------------
        # CAMBIO DE ESTADO
        # -------------------------------------------------

        if status_changed:

            if (
                obj.verification_status
                == ProfessionalProfile
                .VerificationStatus
                .PENDING
            ):

                obj.reviewed_at = None
                obj.reviewed_by = None

            else:

                obj.reviewed_at = (
                    timezone.now()
                )

                obj.reviewed_by = (
                    request.user
                )

        super().save_model(
            request,
            obj,
            form,
            change
        )


# =========================================================
# ACREDITACIÓN PROFESIONAL
# =========================================================

@admin.register(ProfessionalCredential)
class ProfessionalCredentialAdmin(admin.ModelAdmin):

    form = ProfessionalCredentialAdminForm

    list_display = (
        'name',
        'professional_profile',
        'credential_type',
        'issuing_institution',
        'review_status',
        'reviewed_by',
        'issue_date',
        'expiration_date',
        'created_at',
    )

    search_fields = (
        'name',
        'issuing_institution',
        'professional_profile__user__first_name',
        'professional_profile__user__last_name',
        'professional_profile__user__email',
        'professional_profile__user__rut',
    )

    list_filter = (
        'credential_type',
        'review_status',
        'issuing_institution',
        'created_at',
    )

    autocomplete_fields = (
        'professional_profile',
    )

    readonly_fields = (
        'reviewed_at',
        'reviewed_by',
        'created_at',
        'updated_at',
    )

    fieldsets = (
        (
            'Profesional',
            {
                'fields': (
                    'professional_profile',
                )
            },
        ),

        (
            'Acreditación',
            {
                'fields': (
                    'credential_type',
                    'name',
                    'issuing_institution',
                    'issue_date',
                    'expiration_date',
                    'document',
                )
            },
        ),

        (
            'Revisión administrativa',
            {
                'fields': (
                    'review_status',
                    'rejection_reason',
                    'reviewed_at',
                    'reviewed_by',
                )
            },
        ),

        (
            'Sistema',
            {
                'fields': (
                    'created_at',
                    'updated_at',
                )
            },
        ),
    )

    def has_add_permission(
        self,
        request
    ):
        """
        Las acreditaciones deben ser aportadas
        por el profesional y no creadas manualmente
        por el administrador.
        """

        return False

    def save_model(
        self,
        request,
        obj,
        form,
        change
    ):
        """
        Registra automáticamente quién revisó
        la acreditación y cuándo.

        Si un Perfil Profesional verificado pierde
        su última acreditación válida, se suspende
        automáticamente.
        """

        previous_status = None

        if change and obj.pk:

            previous_status = (
                ProfessionalCredential.objects
                .filter(
                    pk=obj.pk
                )
                .values_list(
                    'review_status',
                    flat=True,
                )
                .first()
            )

        status_changed = (
            previous_status
            != obj.review_status
        )

        # -------------------------------------------------
        # CAMBIO DE ESTADO
        # -------------------------------------------------

        if status_changed:

            if (
                obj.review_status
                == ProfessionalCredential
                .ReviewStatus
                .PENDING
            ):

                obj.reviewed_at = None
                obj.reviewed_by = None

                obj.rejection_reason = ''

            else:

                obj.reviewed_at = (
                    timezone.now()
                )

                obj.reviewed_by = (
                    request.user
                )

                if (
                    obj.review_status
                    == ProfessionalCredential
                    .ReviewStatus
                    .VERIFIED
                ):

                    obj.rejection_reason = ''

        super().save_model(
            request,
            obj,
            form,
            change
        )

        # -------------------------------------------------
        # COMPROBAR INTEGRIDAD DEL PERFIL
        # -------------------------------------------------

        professional_profile = (
            obj.professional_profile
        )

        if (
            professional_profile.verification_status
            == ProfessionalProfile
            .VerificationStatus
            .VERIFIED
        ):

            has_verified_credential = (
                professional_profile
                .credentials
                .filter(
                    review_status=(
                        ProfessionalCredential
                        .ReviewStatus
                        .VERIFIED
                    )
                )
                .exists()
            )

            if not has_verified_credential:

                professional_profile.verification_status = (
                    ProfessionalProfile
                    .VerificationStatus
                    .SUSPENDED
                )

                professional_profile.is_public = False

                professional_profile.reviewed_at = (
                    timezone.now()
                )

                professional_profile.reviewed_by = (
                    request.user
                )

                professional_profile.save(
                    update_fields=[
                        'verification_status',
                        'is_public',
                        'reviewed_at',
                        'reviewed_by',
                        'updated_at',
                    ]
                )

                self.message_user(
                    request,
                    (
                        'El Perfil Profesional fue suspendido '
                        'automáticamente porque ya no posee '
                        'ninguna acreditación verificada.'
                    ),
                    level=messages.WARNING,
                )


# =========================================================
# SERVICIOS PROFESIONALES
# =========================================================

@admin.register(ProfessionalService)
class ProfessionalServiceAdmin(admin.ModelAdmin):
    """
    Administración y supervisión de los servicios
    creados por Profesionales verificados.
    """

    list_display = (
        'name',
        'professional_profile',
        'mode',
        'duration_minutes',
        'price',
        'publication_status',
        'created_at',
    )

    search_fields = (
        'name',
        'description',
        'professional_profile__user__first_name',
        'professional_profile__user__last_name',
        'professional_profile__user__email',
        'professional_profile__professional_title',
    )

    list_filter = (
        'publication_status',
        'mode',
        'created_at',
    )

    autocomplete_fields = (
        'professional_profile',
    )

    readonly_fields = (
        'created_at',
        'updated_at',
    )

    fieldsets = (
        (
            'Profesional',
            {
                'fields': (
                    'professional_profile',
                )
            },
        ),

        (
            'Información del servicio',
            {
                'fields': (
                    'name',
                    'description',
                    'mode',
                    'duration_minutes',
                    'price',
                )
            },
        ),

        (
            'Publicación',
            {
                'fields': (
                    'publication_status',
                )
            },
        ),

        (
            'Sistema',
            {
                'fields': (
                    'created_at',
                    'updated_at',
                )
            },
        ),
    )

    def has_add_permission(
        self,
        request
    ):
        """
        Los servicios deben ser creados desde
        el Centro Profesional.
        """

        return False