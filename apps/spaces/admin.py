from django import forms
from django.contrib import admin
from django.utils import timezone

from .models import (
    Space,
    SpaceAmenity,
    SpaceEquipment,
    SpaceHistory,
    SpaceImage,
    SpaceProviderProfile,
    SpaceProviderProfileHistory,
    SpaceType,
)


class SpaceProviderProfileAdminForm(forms.ModelForm):
    """
    Evita aprobar perfiles incompletos desde
    la administración y presenta la infraestructura
    de forma legible.
    """

    managed_infrastructure_types = forms.MultipleChoiceField(
        label='Tipos de infraestructura administrada',
        choices=(
            SpaceProviderProfile
            .INFRASTRUCTURE_TYPE_CHOICES
        ),
        required=True,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = SpaceProviderProfile
        fields = '__all__'

    def __init__(
        self,
        *args,
        **kwargs
    ):
        super().__init__(
            *args,
            **kwargs
        )

        if (
            self.instance
            and self.instance.pk
        ):
            self.fields[
                'managed_infrastructure_types'
            ].initial = (
                self.instance
                .managed_infrastructure_types
            )

    def clean(self):

        cleaned_data = super().clean()

        verification_status = (
            cleaned_data.get(
                'verification_status'
            )
        )

        provider_type = cleaned_data.get(
            'provider_type'
        )

        required_data = [
            provider_type,
            cleaned_data.get(
                'base_commune'
            ),
            cleaned_data.get(
                'base_address'
            ),
            cleaned_data.get(
                'description'
            ),
            cleaned_data.get(
                'managed_infrastructure_types'
            ),
            cleaned_data.get(
                'information_declaration_accepted'
            ),
        ]

        if (
            provider_type
            == SpaceProviderProfile
            .ProviderType
            .ORGANIZATION
        ):

            required_data.extend([
                cleaned_data.get(
                    'public_name'
                ),
                cleaned_data.get(
                    'business_legal_name'
                ),
                cleaned_data.get(
                    'business_rut'
                ),
            ])

        if (
            verification_status
            == SpaceProviderProfile
            .VerificationStatus
            .VERIFIED
            and not all(required_data)
        ):

            raise forms.ValidationError(
                (
                    'No puedes verificar este Perfil Proveedor '
                    'porque la solicitud todavía está incompleta.'
                )
            )

        if (
            verification_status
            == SpaceProviderProfile
            .VerificationStatus
            .REJECTED
            and not cleaned_data.get(
                'rejection_reason'
            )
        ):

            self.add_error(
                'rejection_reason',
                (
                    'Debes registrar un motivo '
                    'para rechazar la solicitud.'
                )
            )

        return cleaned_data


@admin.register(SpaceProviderProfile)
class SpaceProviderProfileAdmin(admin.ModelAdmin):

    form = SpaceProviderProfileAdminForm

    list_display = (
        'id',
        'display_name',
        'provider_type',
        'base_commune',
        'verification_status',
        'is_public',
        'requested_at',
    )

    list_display_links = (
        'display_name',
    )

    list_filter = (
        'provider_type',
        'verification_status',
        'is_public',
    )

    search_fields = (
        'user__first_name',
        'user__last_name',
        'user__email',
        'public_name',
        'business_legal_name',
        'business_rut',
        'base_address',
    )

    readonly_fields = (
        'is_public',
        'reviewed_at',
        'requested_at',
        'created_at',
        'updated_at',
        'information_declaration_accepted_at',
    )

    fieldsets = (
        (
            'Cuenta asociada',
            {
                'fields': (
                    'user',
                    'provider_type',
                )
            }
        ),
        (
            'Identidad pública o comercial',
            {
                'fields': (
                    'public_name',
                    'business_legal_name',
                    'business_rut',
                    'provider_image',
                    'website',
                )
            }
        ),
        (
            'Ubicación y presentación',
            {
                'fields': (
                    'base_commune',
                    'base_address',
                    'description',
                    'managed_infrastructure_types',
                )
            }
        ),
        (
            'Declaración',
            {
                'fields': (
                    'information_declaration_accepted',
                    'information_declaration_accepted_at',
                )
            }
        ),
        (
            'Verificación',
            {
                'fields': (
                    'verification_status',
                    'rejection_reason',
                    'is_public',
                    'reviewed_at',
                )
            }
        ),
        (
            'Trazabilidad',
            {
                'fields': (
                    'requested_at',
                    'created_at',
                    'updated_at',
                )
            }
        ),
    )

    def has_add_permission(
        self,
        request
    ):
        """
        Los Perfiles Proveedor solo se crean desde
        la Cuenta Única mediante la solicitud pública.
        """
        return False

    def has_delete_permission(
        self,
        request,
        obj=None
    ):
        """
        Se conserva la trazabilidad del Perfil Proveedor.
        Los perfiles no se eliminan desde administración.
        """
        return False

    def save_model(
        self,
        request,
        obj,
        form,
        change
    ):

        previous_data = {}

        previous_status = None

        if change and obj.pk:

            previous_obj = (
                SpaceProviderProfile.objects
                .filter(
                    pk=obj.pk
                )
                .first()
            )

            if previous_obj:

                previous_data = (
                    previous_obj.audit_snapshot()
                )

                previous_status = (
                    previous_obj
                    .verification_status
                )

        if (
            obj.verification_status
            == SpaceProviderProfile
            .VerificationStatus
            .VERIFIED
        ):

            obj.is_public = True

        elif (
            obj.verification_status
            in (
                SpaceProviderProfile
                .VerificationStatus
                .REJECTED,

                SpaceProviderProfile
                .VerificationStatus
                .SUSPENDED,
            )
        ):

            obj.is_public = False

        if (
            previous_status
            != obj.verification_status
            and obj.verification_status
            != SpaceProviderProfile
            .VerificationStatus
            .PENDING
        ):

            obj.reviewed_at = (
                timezone.now()
            )

        super().save_model(
            request,
            obj,
            form,
            change
        )

        action = None

        if (
            previous_status
            != obj.verification_status
        ):

            if (
                previous_status
                == SpaceProviderProfile
                .VerificationStatus
                .SUSPENDED
                and obj.verification_status
                == SpaceProviderProfile
                .VerificationStatus
                .VERIFIED
            ):

                action = (
                    SpaceProviderProfileHistory
                    .Action
                    .REACTIVATED
                )

            elif (
                obj.verification_status
                == SpaceProviderProfile
                .VerificationStatus
                .VERIFIED
            ):

                action = (
                    SpaceProviderProfileHistory
                    .Action
                    .VERIFIED
                )

            elif (
                obj.verification_status
                == SpaceProviderProfile
                .VerificationStatus
                .REJECTED
            ):

                action = (
                    SpaceProviderProfileHistory
                    .Action
                    .REJECTED
                )

            elif (
                obj.verification_status
                == SpaceProviderProfile
                .VerificationStatus
                .SUSPENDED
            ):

                action = (
                    SpaceProviderProfileHistory
                    .Action
                    .SUSPENDED
                )

        elif change:

            action = (
                SpaceProviderProfileHistory
                .Action
                .UPDATED
            )

        if action:

            SpaceProviderProfileHistory.objects.create(
                provider_profile=obj,
                action=action,
                previous_data=previous_data,
                new_data=obj.audit_snapshot(),
                changed_by=request.user,
                reason=(
                    obj.rejection_reason
                    if obj.rejection_reason
                    else (
                        'Cambio realizado desde '
                        'la administración.'
                    )
                ),
            )


@admin.register(SpaceProviderProfileHistory)
class SpaceProviderProfileHistoryAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'provider_profile',
        'action',
        'changed_by',
        'created_at',
    )

    list_filter = (
        'action',
        'created_at',
    )

    search_fields = (
        'provider_profile__public_name',
        'provider_profile__user__first_name',
        'provider_profile__user__last_name',
        'reason',
    )

    readonly_fields = (
        'provider_profile',
        'action',
        'previous_data',
        'new_data',
        'changed_by',
        'reason',
        'created_at',
    )

    def has_add_permission(
        self,
        request
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None
    ):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None
    ):
        return False


@admin.register(SpaceType)
class SpaceTypeAdmin(admin.ModelAdmin):

    list_display = (
        'name',
        'slug',
        'display_order',
        'is_active',
    )

    list_editable = (
        'display_order',
        'is_active',
    )

    search_fields = (
        'name',
        'slug',
    )

    ordering = (
        'display_order',
        'name',
    )


@admin.register(SpaceEquipment)
class SpaceEquipmentAdmin(admin.ModelAdmin):

    list_display = (
        'name',
        'slug',
        'display_order',
        'is_active',
    )

    list_editable = (
        'display_order',
        'is_active',
    )

    search_fields = (
        'name',
        'slug',
    )

    ordering = (
        'display_order',
        'name',
    )


@admin.register(SpaceAmenity)
class SpaceAmenityAdmin(admin.ModelAdmin):

    list_display = (
        'name',
        'slug',
        'display_order',
        'is_active',
    )

    list_editable = (
        'display_order',
        'is_active',
    )

    search_fields = (
        'name',
        'slug',
    )

    ordering = (
        'display_order',
        'name',
    )


class SpaceImageInline(admin.TabularInline):

    model = SpaceImage

    extra = 0

    fields = (
        'image',
        'caption',
        'is_cover',
        'display_order',
        'created_at',
    )

    readonly_fields = (
        'created_at',
    )

    can_delete = False


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'name',
        'provider_profile',
        'space_type',
        'commune',
        'publication_status',
        'hourly_price_clp',
        'created_at',
    )

    list_display_links = (
        'name',
    )

    list_filter = (
        'publication_status',
        'space_type',
        'commune__region',
    )

    search_fields = (
        'name',
        'description',
        'address',
        'provider_profile__public_name',
        'provider_profile__user__first_name',
        'provider_profile__user__last_name',
    )

    readonly_fields = (
        'published_at',
        'created_at',
        'updated_at',
    )

    filter_horizontal = (
        'equipments',
        'amenities',
    )

    inlines = (
        SpaceImageInline,
    )

    fieldsets = (
        (
            'Proveedor y clasificación',
            {
                'fields': (
                    'provider_profile',
                    'space_type',
                    'name',
                    'description',
                )
            }
        ),
        (
            'Ubicación',
            {
                'fields': (
                    'commune',
                    'address',
                    'location_reference',
                )
            }
        ),
        (
            'Capacidad y precio',
            {
                'fields': (
                    'capacity',
                    'surface_m2',
                    'hourly_price_clp',
                )
            }
        ),
        (
            'Equipamiento y comodidades',
            {
                'fields': (
                    'equipments',
                    'amenities',
                )
            }
        ),
        (
            'Uso y acceso',
            {
                'fields': (
                    'rules',
                    'access_instructions',
                )
            }
        ),
        (
            'Publicación',
            {
                'fields': (
                    'publication_status',
                    'published_at',
                )
            }
        ),
        (
            'Trazabilidad',
            {
                'fields': (
                    'created_at',
                    'updated_at',
                )
            }
        ),
    )

    def has_add_permission(
        self,
        request
    ):
        """
        Los espacios se crearán desde el Centro de Espacios.
        """
        return False

    def has_delete_permission(
        self,
        request,
        obj=None
    ):
        """
        Conservamos los recintos para trazabilidad.
        """
        return False


@admin.register(SpaceHistory)
class SpaceHistoryAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'space',
        'action',
        'changed_by',
        'created_at',
    )

    list_filter = (
        'action',
        'created_at',
    )

    search_fields = (
        'space__name',
        'reason',
        'changed_by__first_name',
        'changed_by__last_name',
        'changed_by__email',
    )

    readonly_fields = (
        'space',
        'action',
        'previous_data',
        'new_data',
        'changed_by',
        'reason',
        'created_at',
    )

    def has_add_permission(
        self,
        request
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None
    ):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None
    ):
        return False

