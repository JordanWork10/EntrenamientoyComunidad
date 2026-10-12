from datetime import time

from django import forms

from apps.locations.models import Commune, Region

from .models import (
    ProfessionalCategory,
    ProfessionalCredential,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalSpecialty,
)


# =========================================================
# HORARIOS DISPONIBLES EN INTERVALOS DE 15 MINUTOS
# =========================================================

TIME_SLOT_CHOICES = [
    (
        f'{minutes // 60:02d}:{minutes % 60:02d}',
        f'{minutes // 60:02d}:{minutes % 60:02d}',
    )
    for minutes in range(
        0,
        24 * 60,
        15,
    )
]


def time_from_choice(value):
    """
    Convierte HH:MM a datetime.time.
    """

    hour, minute = value.split(':')

    return time(
        hour=int(hour),
        minute=int(minute),
    )


class ProfessionalProfileRequestForm(forms.ModelForm):
    """
    Formulario de solicitud de Perfil Profesional.
    """

    category = forms.ModelChoiceField(
        label='Categoría profesional',
        queryset=ProfessionalCategory.objects.none(),
        required=True,
        empty_label='Selecciona una categoría',
    )

    specialty = forms.ModelChoiceField(
        label='Especialidad principal',
        queryset=ProfessionalSpecialty.objects.none(),
        required=True,
        empty_label='Selecciona una especialidad',
    )

    region = forms.ModelChoiceField(
        label='Región principal de cobertura',
        queryset=Region.objects.none(),
        required=False,
        empty_label='Selecciona una región',
    )

    coverage_communes = forms.ModelMultipleChoiceField(
        label='Comunas de cobertura',
        queryset=Commune.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    offers_in_person = forms.BooleanField(
        label='Atención presencial',
        required=False,
    )

    offers_online = forms.BooleanField(
        label='Atención online',
        required=False,
    )

    class Meta:
        model = ProfessionalProfile

        fields = [
            'category',
            'specialty',
            'professional_title',
            'years_experience',
            'bio',
            'offers_in_person',
            'offers_online',
            'coverage_communes',
        ]

        labels = {
            'professional_title': (
                'Título profesional o denominación'
            ),
            'years_experience': (
                'Años de experiencia'
            ),
            'bio': (
                'Descripción profesional'
            ),
        }

        widgets = {
            'professional_title': forms.TextInput(
                attrs={
                    'placeholder': (
                        'Ej: Entrenador personal certificado'
                    ),
                }
            ),

            'years_experience': forms.NumberInput(
                attrs={
                    'min': 0,
                    'max': 60,
                }
            ),

            'bio': forms.Textarea(
                attrs={
                    'rows': 6,
                    'placeholder': (
                        'Describe tu experiencia, enfoque '
                        'profesional y áreas de trabajo.'
                    ),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['category'].queryset = (
            ProfessionalCategory.objects
            .filter(is_active=True)
            .order_by(
                'display_order',
                'name',
            )
        )

        self.fields['region'].queryset = (
            Region.objects
            .filter(is_active=True)
            .order_by('name')
        )

        if self.is_bound:

            category_id = self.data.get(
                'category'
            )

            if category_id:

                self.fields['specialty'].queryset = (
                    ProfessionalSpecialty.objects
                    .filter(
                        category_id=category_id,
                        is_active=True,
                    )
                    .order_by(
                        'display_order',
                        'name',
                    )
                )

            region_id = self.data.get(
                'region'
            )

            if region_id:

                self.fields[
                    'coverage_communes'
                ].queryset = (
                    Commune.objects
                    .filter(
                        region_id=region_id,
                        is_active=True,
                    )
                    .order_by('name')
                )

    def clean(self):

        cleaned_data = super().clean()

        category = cleaned_data.get(
            'category'
        )

        specialty = cleaned_data.get(
            'specialty'
        )

        offers_in_person = cleaned_data.get(
            'offers_in_person'
        )

        offers_online = cleaned_data.get(
            'offers_online'
        )

        if (
            category
            and specialty
            and specialty.category_id
            != category.id
        ):

            self.add_error(
                'specialty',
                (
                    'La especialidad seleccionada no '
                    'pertenece a la categoría indicada.'
                )
            )

        if (
            not offers_in_person
            and not offers_online
        ):

            raise forms.ValidationError(
                (
                    'Debes seleccionar al menos una modalidad '
                    'de atención: presencial u online.'
                )
            )

        if (
            offers_in_person
            and not cleaned_data.get(
                'coverage_communes'
            )
        ):

            self.add_error(
                'coverage_communes',
                (
                    'Si atiendes presencialmente debes '
                    'seleccionar al menos una comuna de cobertura.'
                )
            )

        return cleaned_data


class ProfessionalCredentialForm(forms.ModelForm):
    """
    Formulario para adjuntar la primera acreditación
    durante la solicitud del Perfil Profesional.
    """

    credential_type = forms.ChoiceField(
        label='Tipo de acreditación',
        choices=(
            ProfessionalCredential
            .CredentialType
            .choices
        ),
        required=True,
    )

    name = forms.CharField(
        label='Nombre de la acreditación',
        max_length=180,
        required=True,
        widget=forms.TextInput(
            attrs={
                'placeholder': (
                    'Ej: Título de Preparador Físico'
                ),
            }
        ),
    )

    issuing_institution = forms.CharField(
        label='Institución emisora',
        max_length=180,
        required=True,
        widget=forms.TextInput(
            attrs={
                'placeholder': (
                    'Ej: INACAP, universidad, federación...'
                ),
            }
        ),
    )

    issue_date = forms.DateField(
        label='Fecha de emisión',
        required=True,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
            }
        ),
    )

    expiration_date = forms.DateField(
        label='Fecha de vencimiento',
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
            }
        ),
    )

    document = forms.FileField(
        label='Documento de respaldo',
        required=True,
        help_text=(
            'Formatos permitidos: PDF, JPG, JPEG o PNG.'
        ),
    )

    class Meta:
        model = ProfessionalCredential

        fields = [
            'credential_type',
            'name',
            'issuing_institution',
            'issue_date',
            'expiration_date',
            'document',
        ]

    def clean(self):

        cleaned_data = super().clean()

        issue_date = cleaned_data.get(
            'issue_date'
        )

        expiration_date = cleaned_data.get(
            'expiration_date'
        )

        if (
            issue_date
            and expiration_date
            and expiration_date < issue_date
        ):

            self.add_error(
                'expiration_date',
                (
                    'La fecha de vencimiento no puede '
                    'ser anterior a la fecha de emisión.'
                )
            )

        return cleaned_data


class ProfessionalServiceForm(forms.ModelForm):
    """
    Formulario utilizado por un Profesional verificado
    para crear o editar un servicio desde su Centro Profesional.

    El Perfil Profesional no se selecciona manualmente.
    Será asignado desde el usuario autenticado.
    """

    name = forms.CharField(
        label='Nombre del servicio',
        max_length=180,
        required=True,
        widget=forms.TextInput(
            attrs={
                'placeholder': (
                    'Ej: Entrenamiento personalizado'
                ),
            }
        ),
    )

    description = forms.CharField(
        label='Descripción del servicio',
        required=True,
        widget=forms.Textarea(
            attrs={
                'rows': 7,
                'placeholder': (
                    'Describe en qué consiste el servicio, '
                    'a quién está dirigido y qué incluye.'
                ),
            }
        ),
    )

    mode = forms.ChoiceField(
        label='Modalidad',
        choices=[],
        required=True,
    )

    duration_minutes = forms.IntegerField(
        label='Duración',
        required=True,
        min_value=15,
        max_value=480,
        widget=forms.NumberInput(
            attrs={
                'min': 15,
                'max': 480,
                'step': 5,
                'placeholder': 'Ej: 60',
            }
        ),
        help_text=(
            'Duración del servicio en minutos.'
        ),
    )

    price = forms.IntegerField(
        label='Precio',
        required=True,
        min_value=0,
        widget=forms.NumberInput(
            attrs={
                'min': 0,
                'step': 1000,
                'placeholder': 'Ej: 25000',
            }
        ),
        help_text=(
            'Valor del servicio en pesos chilenos (CLP).'
        ),
    )

    in_person_location_type = forms.ChoiceField(
        label='Tipo de lugar de atención',
        required=False,
        choices=[],
        help_text=(
            'Solo se utiliza para servicios presenciales '
            'o híbridos.'
        ),
    )

    location_region = forms.ModelChoiceField(
        label='Región del lugar',
        queryset=Region.objects.none(),
        required=False,
        empty_label='Selecciona una región',
    )

    location_commune = forms.ModelChoiceField(
        label='Comuna del lugar',
        queryset=Commune.objects.none(),
        required=False,
        empty_label='Selecciona una comuna',
    )

    location_name = forms.CharField(
        label='Nombre o referencia del lugar',
        max_length=180,
        required=False,
        widget=forms.TextInput(
            attrs={
                'placeholder': (
                    'Ej: Consulta privada, gimnasio, estudio...'
                ),
            }
        ),
    )

    location_address = forms.CharField(
        label='Dirección del lugar',
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                'placeholder': (
                    'Ej: Av. Principal 1234'
                ),
            }
        ),
    )

    class Meta:
        model = ProfessionalService

        fields = [
            'name',
            'description',
            'mode',
            'duration_minutes',
            'price',
            'in_person_location_type',
            'location_name',
            'location_address',
            'location_commune',
        ]

    def __init__(
        self,
        *args,
        professional_profile=None,
        **kwargs
    ):

        super().__init__(
            *args,
            **kwargs
        )

        self.professional_profile = (
            professional_profile
        )

        # -------------------------------------------------
        # MODALIDADES DISPONIBLES
        # -------------------------------------------------

        mode_choices = []

        if professional_profile:

            if (
                professional_profile
                .offers_in_person
            ):

                mode_choices.append(
                    (
                        ProfessionalService
                        .ServiceMode
                        .IN_PERSON,

                        'Presencial',
                    )
                )

            if (
                professional_profile
                .offers_online
            ):

                mode_choices.append(
                    (
                        ProfessionalService
                        .ServiceMode
                        .ONLINE,

                        'Online',
                    )
                )

            if (
                professional_profile
                .offers_in_person
                and professional_profile
                .offers_online
            ):

                mode_choices.append(
                    (
                        ProfessionalService
                        .ServiceMode
                        .HYBRID,

                        'Presencial y online',
                    )
                )

        self.fields[
            'mode'
        ].choices = mode_choices

        # -------------------------------------------------
        # TIPOS DE LUGAR PRESENCIAL
        # -------------------------------------------------

        self.fields[
            'in_person_location_type'
        ].choices = [
            (
                '',
                'Selecciona un tipo de lugar',
            ),
            *ProfessionalService
            .InPersonLocationType
            .choices,
        ]

        # -------------------------------------------------
        # REGIONES
        # -------------------------------------------------

        self.fields[
            'location_region'
        ].queryset = (
            Region.objects
            .filter(is_active=True)
            .order_by('name')
        )

        # -------------------------------------------------
        # COMUNAS
        # -------------------------------------------------

        self.fields[
            'location_commune'
        ].queryset = (
            Commune.objects.none()
        )

        if self.is_bound:

            region_id = self.data.get(
                'location_region'
            )

            if region_id:

                self.fields[
                    'location_commune'
                ].queryset = (
                    Commune.objects
                    .filter(
                        region_id=region_id,
                        is_active=True,
                    )
                    .order_by('name')
                )

        elif (
            self.instance
            and self.instance.pk
            and self.instance.location_commune_id
        ):

            commune = (
                self.instance.location_commune
            )

            self.fields[
                'location_region'
            ].initial = commune.region_id

            self.fields[
                'location_commune'
            ].queryset = (
                Commune.objects
                .filter(
                    region_id=commune.region_id,
                    is_active=True,
                )
                .order_by('name')
            )

    def clean_name(self):

        name = (
            self.cleaned_data
            .get(
                'name',
                ''
            )
            .strip()
        )

        if len(name) < 5:

            raise forms.ValidationError(
                (
                    'El nombre del servicio debe contener '
                    'al menos 5 caracteres.'
                )
            )

        return name

    def clean_description(self):

        description = (
            self.cleaned_data
            .get(
                'description',
                ''
            )
            .strip()
        )

        if len(description) < 20:

            raise forms.ValidationError(
                (
                    'La descripción debe contener al menos '
                    '20 caracteres.'
                )
            )

        return description

    def clean(self):

        cleaned_data = super().clean()

        professional_profile = (
            self.professional_profile
        )

        if professional_profile is None:

            raise forms.ValidationError(
                (
                    'No se encontró un Perfil Profesional '
                    'asociado a esta cuenta.'
                )
            )

        if (
            professional_profile.verification_status
            != ProfessionalProfile
            .VerificationStatus
            .VERIFIED
        ):

            raise forms.ValidationError(
                (
                    'Solo un Profesional verificado puede '
                    'crear o editar servicios.'
                )
            )

        if not professional_profile.is_public:

            raise forms.ValidationError(
                (
                    'Tu Perfil Profesional debe encontrarse '
                    'habilitado públicamente para administrar '
                    'servicios.'
                )
            )

        mode = cleaned_data.get(
            'mode'
        )

        if (
            mode
            in (
                ProfessionalService
                .ServiceMode
                .IN_PERSON,

                ProfessionalService
                .ServiceMode
                .HYBRID,
            )
            and not professional_profile.offers_in_person
        ):

            self.add_error(
                'mode',
                (
                    'Tu Perfil Profesional no tiene '
                    'habilitada la atención presencial.'
                )
            )

        if (
            mode
            in (
                ProfessionalService
                .ServiceMode
                .ONLINE,

                ProfessionalService
                .ServiceMode
                .HYBRID,
            )
            and not professional_profile.offers_online
        ):

            self.add_error(
                'mode',
                (
                    'Tu Perfil Profesional no tiene '
                    'habilitada la atención online.'
                )
            )

        # -------------------------------------------------
        # LUGAR DE ATENCIÓN
        # -------------------------------------------------

        uses_in_person_mode = (
            mode
            in (
                ProfessionalService
                .ServiceMode
                .IN_PERSON,

                ProfessionalService
                .ServiceMode
                .HYBRID,
            )
        )

        location_type = cleaned_data.get(
            'in_person_location_type'
        )

        region = cleaned_data.get(
            'location_region'
        )

        commune = cleaned_data.get(
            'location_commune'
        )

        location_name = (
            cleaned_data.get(
                'location_name',
                ''
            )
            .strip()
        )

        location_address = (
            cleaned_data.get(
                'location_address',
                ''
            )
            .strip()
        )

        if uses_in_person_mode:

            # Un borrador puede quedar sin ubicación.
            # Si el profesional comienza a configurar
            # un lugar propio, debe completarlo.

            if (
                location_type
                == ProfessionalService
                .InPersonLocationType
                .PROFESSIONAL_PLACE
            ):

                if not location_name:
                    self.add_error(
                        'location_name',
                        (
                            'Indica el nombre o una referencia '
                            'del lugar de atención.'
                        )
                    )

                if not location_address:
                    self.add_error(
                        'location_address',
                        (
                            'Indica la dirección del lugar '
                            'de atención.'
                        )
                    )

                if not region:
                    self.add_error(
                        'location_region',
                        (
                            'Selecciona la región del lugar '
                            'de atención.'
                        )
                    )

                if not commune:
                    self.add_error(
                        'location_commune',
                        (
                            'Selecciona la comuna del lugar '
                            'de atención.'
                        )
                    )

                if (
                    region
                    and commune
                    and commune.region_id
                    != region.id
                ):

                    self.add_error(
                        'location_commune',
                        (
                            'La comuna seleccionada no '
                            'pertenece a la región indicada.'
                        )
                    )

            elif (
                location_type
                == ProfessionalService
                .InPersonLocationType
                .USER_HOME
            ):

                cleaned_data[
                    'location_name'
                ] = ''

                cleaned_data[
                    'location_address'
                ] = ''

                cleaned_data[
                    'location_commune'
                ] = None

            elif (
                location_type
                == ProfessionalService
                .InPersonLocationType
                .AGREED_PLACE
            ):

                cleaned_data[
                    'location_address'
                ] = ''

                cleaned_data[
                    'location_commune'
                ] = None

        else:

            cleaned_data[
                'in_person_location_type'
            ] = ''

            cleaned_data[
                'location_name'
            ] = ''

            cleaned_data[
                'location_address'
            ] = ''

            cleaned_data[
                'location_commune'
            ] = None

        return cleaned_data


class ProfessionalServiceAvailabilityForm(forms.ModelForm):
    """
    Formulario utilizado por un Profesional verificado para
    configurar bloques recurrentes de disponibilidad asociados
    a uno de sus servicios.

    El servicio no se selecciona manualmente: se recibe desde
    la vista y queda asociado al formulario.
    """

    weekday = forms.ChoiceField(
        label='Día de la semana',
        choices=ProfessionalServiceAvailability.Weekday.choices,
        required=True,
    )

    start_time = forms.ChoiceField(
        label='Disponible desde',
        required=True,
        choices=[
            (
                '',
                'Selecciona una hora',
            ),
            *TIME_SLOT_CHOICES,
        ],
    )

    end_time = forms.ChoiceField(
        label='Disponible hasta',
        required=True,
        choices=[
            (
                '',
                'Selecciona una hora',
            ),
            *TIME_SLOT_CHOICES,
        ],
    )

    valid_from = forms.DateField(
        label='Vigente desde',
        required=True,
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={
                'type': 'date',
            }
        ),
        help_text=(
            'Fecha desde la cual este horario estará disponible.'
        ),
    )

    valid_until = forms.DateField(
        label='Vigente hasta',
        required=False,
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={
                'type': 'date',
            }
        ),
        help_text=(
            'Opcional. Déjalo vacío si el horario no tiene '
            'una fecha de término definida.'
        ),
    )

    class Meta:
        model = ProfessionalServiceAvailability

        fields = [
            'weekday',
            'start_time',
            'end_time',
            'valid_from',
            'valid_until',
        ]

    def __init__(
        self,
        *args,
        service=None,
        **kwargs
    ):

        super().__init__(
            *args,
            **kwargs
        )

        self.service = service

        # Asignamos el servicio a la instancia antes de la
        # validación del ModelForm para que también se ejecuten
        # correctamente las reglas definidas en el modelo:
        # duración mínima y solapamientos.
        if service is not None:
            self.instance.service = service

        # En edición, convertimos las horas existentes del modelo
        # al formato HH:MM utilizado por los selectores.
        if (
            not self.is_bound
            and self.instance
            and self.instance.pk
        ):

            if self.instance.start_time:

                self.initial[
                    'start_time'
                ] = (
                    self.instance
                    .start_time
                    .strftime('%H:%M')
                )

            if self.instance.end_time:

                self.initial[
                    'end_time'
                ] = (
                    self.instance
                    .end_time
                    .strftime('%H:%M')
                )

    def clean_start_time(self):

        value = self.cleaned_data.get(
            'start_time'
        )

        if not value:
            return None

        return time_from_choice(
            value
        )

    def clean_end_time(self):

        value = self.cleaned_data.get(
            'end_time'
        )

        if not value:
            return None

        return time_from_choice(
            value
        )

    def clean(self):

        cleaned_data = super().clean()

        service = self.service

        if service is None:

            raise forms.ValidationError(
                (
                    'No se encontró el servicio profesional '
                    'asociado a esta disponibilidad.'
                )
            )

        # La propiedad del servicio se valida además desde la vista.
        # Aquí mantenemos una protección adicional para evitar que
        # una disponibilidad quede asociada a un servicio inválido.

        if not service.professional_profile_id:

            raise forms.ValidationError(
                (
                    'El servicio no tiene un Perfil Profesional '
                    'asociado correctamente.'
                )
            )

        start_time = cleaned_data.get(
            'start_time'
        )

        end_time = cleaned_data.get(
            'end_time'
        )

        valid_from = cleaned_data.get(
            'valid_from'
        )

        valid_until = cleaned_data.get(
            'valid_until'
        )

        if (
            start_time
            and end_time
            and end_time <= start_time
        ):

            self.add_error(
                'end_time',
                (
                    'Disponible hasta debe ser posterior '
                    'a Disponible desde.'
                )
            )

        if (
            valid_from
            and valid_until
            and valid_until < valid_from
        ):

            self.add_error(
                'valid_until',
                (
                    'La fecha de término no puede ser anterior '
                    'a la fecha de inicio.'
                )
            )

        return cleaned_data

