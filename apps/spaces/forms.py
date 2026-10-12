from django import forms

from django.utils import timezone



from apps.accounts.models import (

    normalize_rut,

    validate_rut,

)

from apps.locations.models import (

    Commune,

    Region,

)



from .models import (

    Space,

    SpaceAmenity,

    SpaceAvailability,

    SpaceAvailabilityException,

    SpaceBooking,

    SpaceEquipment,

    SpaceProviderProfile,

    SpaceType,

)





class SpaceProviderProfileRequestForm(forms.ModelForm):

    """

    Solicitud completa de Perfil de Proveedor de Espacios.

    """



    provider_type = forms.ChoiceField(

        label='Tipo de proveedor',

        choices=(

            SpaceProviderProfile

            .ProviderType

            .choices

        ),

        required=True,

    )



    public_name = forms.CharField(

        label='Nombre público o comercial',

        max_length=180,

        required=False,

        widget=forms.TextInput(

            attrs={

                'placeholder': (

                    'Ej: Centro Deportivo Buin'

                ),

            }

        ),

        help_text=(

            'Si eres persona natural puedes dejarlo vacío '

            'y utilizaremos tu nombre de Cuenta Única.'

        ),

    )



    business_legal_name = forms.CharField(

        label='Razón social',

        max_length=200,

        required=False,

        widget=forms.TextInput(

            attrs={

                'placeholder': (

                    'Ej: Centro Deportivo Buin SpA'

                ),

            }

        ),

    )



    business_rut = forms.CharField(

        label='RUT de la organización',

        max_length=12,

        required=False,

        widget=forms.TextInput(

            attrs={

                'placeholder': (

                    'Ej: 76123456-7'

                ),

            }

        ),

    )



    base_region = forms.ModelChoiceField(

        label='Región base',

        queryset=Region.objects.none(),

        required=True,

        empty_label='Selecciona una región',

    )



    base_commune = forms.ModelChoiceField(

        label='Comuna base',

        queryset=Commune.objects.none(),

        required=True,

        empty_label='Selecciona una comuna',

    )



    base_address = forms.CharField(

        label='Dirección base o comercial',

        max_length=255,

        required=True,

        widget=forms.TextInput(

            attrs={

                'placeholder': (

                    'Ej: Av. Principal 123'

                ),

            }

        ),

        help_text=(

            'Corresponde a tu base de operación. '

            'Cada espacio tendrá posteriormente su propia dirección.'

        ),

    )



    description = forms.CharField(

        label='Descripción del proveedor',

        required=True,

        widget=forms.Textarea(

            attrs={

                'rows': 7,

                'placeholder': (

                    'Describe quién administra los espacios, '

                    'tu experiencia y el tipo de infraestructura '

                    'que gestionas.'

                ),

            }

        ),

    )



    managed_infrastructure_types = (

        forms.MultipleChoiceField(

            label='Tipo de infraestructura que administras',

            choices=(

                SpaceProviderProfile

                .INFRASTRUCTURE_TYPE_CHOICES

            ),

            required=True,

            widget=forms.CheckboxSelectMultiple,

        )

    )



    provider_image = forms.ImageField(

        label='Logo o imagen del proveedor',

        required=False,

        help_text=(

            'JPG, JPEG, PNG o WEBP. Máximo 5 MB.'

        ),

    )



    website = forms.URLField(

        label='Sitio web',

        required=False,

        widget=forms.URLInput(

            attrs={

                'placeholder': (

                    'https://www.ejemplo.cl'

                ),

            }

        ),

        help_text='Opcional.',

    )



    information_declaration_accepted = (

        forms.BooleanField(

            label=(

                'Declaro que la información proporcionada '

                'es correcta y que cuento con autorización '

                'para administrar o representar los espacios '

                'que posteriormente publique.'

            ),

            required=True,

        )

    )



    class Meta:

        model = SpaceProviderProfile



        fields = [

            'provider_type',

            'public_name',

            'business_legal_name',

            'business_rut',

            'base_commune',

            'base_address',

            'description',

            'managed_infrastructure_types',

            'provider_image',

            'website',

            'information_declaration_accepted',

        ]



    def __init__(

        self,

        *args,

        **kwargs

    ):



        super().__init__(

            *args,

            **kwargs

        )



        self.fields['base_region'].queryset = (

            Region.objects

            .filter(

                is_active=True

            )

            .order_by(

                'name'

            )

        )



        self.fields['base_commune'].queryset = (

            Commune.objects.none()

        )



        if self.is_bound:



            region_id = self.data.get(

                'base_region'

            )



            if region_id:



                self.fields[

                    'base_commune'

                ].queryset = (

                    Commune.objects

                    .filter(

                        region_id=region_id,

                        is_active=True,

                    )

                    .order_by(

                        'name'

                    )

                )



        elif (

            self.instance

            and self.instance.pk

            and self.instance.base_commune_id

        ):



            commune = (

                self.instance.base_commune

            )



            self.fields[

                'base_region'

            ].initial = (

                commune.region_id

            )



            self.fields[

                'base_commune'

            ].queryset = (

                Commune.objects

                .filter(

                    region_id=commune.region_id,

                    is_active=True,

                )

                .order_by(

                    'name'

                )

            )



            self.fields[

                'base_commune'

            ].initial = commune



            self.fields[

                'managed_infrastructure_types'

            ].initial = (

                self.instance

                .managed_infrastructure_types

            )



    def clean_public_name(self):



        return (

            self.cleaned_data

            .get(

                'public_name',

                ''

            )

            .strip()

        )



    def clean_business_legal_name(self):



        return (

            self.cleaned_data

            .get(

                'business_legal_name',

                ''

            )

            .strip()

        )



    def clean_business_rut(self):



        business_rut = (

            self.cleaned_data

            .get(

                'business_rut',

                ''

            )

            .strip()

        )



        if not business_rut:

            return ''



        business_rut = normalize_rut(

            business_rut

        )



        validate_rut(

            business_rut

        )



        return business_rut



    def clean_description(self):



        description = (

            self.cleaned_data

            .get(

                'description',

                ''

            )

            .strip()

        )



        if len(description) < 40:



            raise forms.ValidationError(

                (

                    'La descripción debe contener al menos '

                    '40 caracteres.'

                )

            )



        return description



    def clean_provider_image(self):



        image = self.cleaned_data.get(

            'provider_image'

        )



        if (

            image

            and image.size > 5 * 1024 * 1024

        ):



            raise forms.ValidationError(

                (

                    'La imagen no puede superar los 5 MB.'

                )

            )



        return image



    def clean(self):



        cleaned_data = super().clean()



        provider_type = cleaned_data.get(

            'provider_type'

        )



        public_name = cleaned_data.get(

            'public_name',

            ''

        )



        business_legal_name = (

            cleaned_data.get(

                'business_legal_name',

                ''

            )

        )



        business_rut = cleaned_data.get(

            'business_rut',

            ''

        )



        region = cleaned_data.get(

            'base_region'

        )



        commune = cleaned_data.get(

            'base_commune'

        )



        if (

            provider_type

            == SpaceProviderProfile

            .ProviderType

            .INDIVIDUAL

        ):



            cleaned_data[

                'business_legal_name'

            ] = ''



            cleaned_data[

                'business_rut'

            ] = ''





        if (

            provider_type

            == SpaceProviderProfile

            .ProviderType

            .ORGANIZATION

        ):



            if not public_name:



                self.add_error(

                    'public_name',

                    (

                        'Para una organización o negocio '

                        'debes indicar el nombre público '

                        'o comercial.'

                    )

                )



            if not business_legal_name:



                self.add_error(

                    'business_legal_name',

                    (

                        'Debes indicar la razón social '

                        'de la organización.'

                    )

                )



            if not business_rut:



                self.add_error(

                    'business_rut',

                    (

                        'Debes indicar el RUT '

                        'de la organización.'

                    )

                )



        if (

            region

            and commune

            and commune.region_id

            != region.id

        ):



            self.add_error(

                'base_commune',

                (

                    'La comuna seleccionada no pertenece '

                    'a la región indicada.'

                )

            )



        return cleaned_data







class MultipleFileInput(forms.ClearableFileInput):
    """
    Input de archivos que permite seleccionar varias imágenes
    en una sola acción.
    """

    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """
    Campo de imágenes múltiples compatible con MultiValueDict.
    """

    widget = MultipleFileInput

    def clean(self, data, initial=None):

        single_clean = super().clean

        if not data:
            return []

        if isinstance(data, (list, tuple)):
            return [
                single_clean(item, initial)
                for item in data
            ]

        return [
            single_clean(data, initial)
        ]


class SpaceCreateForm(forms.ModelForm):



    region = forms.ModelChoiceField(

        label='Región',

        queryset=Region.objects.none(),

        required=True,

        empty_label='Selecciona una región',

    )



    commune = forms.ModelChoiceField(

        label='Comuna',

        queryset=Commune.objects.none(),

        required=True,

        empty_label='Selecciona una comuna',

    )



    space_type = forms.ModelChoiceField(

        label='Tipo de espacio',

        queryset=SpaceType.objects.none(),

        required=True,

        empty_label='Selecciona un tipo de espacio',

    )



    environment = forms.ChoiceField(

        label='Entorno',

        required=False,

        choices=(

            (

                '',

                'Selecciona un entorno',

            ),

        )

        + tuple(

            Space.Environment.choices

        ),

    )



    equipments = forms.ModelMultipleChoiceField(

        label='Equipamiento disponible',

        queryset=SpaceEquipment.objects.none(),

        required=False,

        widget=forms.CheckboxSelectMultiple,

    )



    amenities = forms.ModelMultipleChoiceField(

        label='Comodidades y servicios',

        queryset=SpaceAmenity.objects.none(),

        required=False,

        widget=forms.CheckboxSelectMultiple,

    )



    cover_image = forms.ImageField(

        label='Fotografía principal',

        required=False,

        help_text='JPG, JPEG, PNG o WEBP. Máximo 5 MB.',

    )



    gallery_images = MultipleImageField(

        label='Fotografías adicionales',

        required=False,

        widget=MultipleFileInput(

            attrs={

                'accept': 'image/jpeg,image/png,image/webp',

            }

        ),

        help_text=(

            'Puedes seleccionar hasta 6 imágenes. '

            'JPG, JPEG, PNG o WEBP. Máximo 5 MB cada una.'

        ),

    )



    class Meta:

        model = Space

        fields = [

            'space_type',

            'name',

            'description',

            'commune',

            'address',

            'location_reference',

            'capacity',

            'surface_m2',

            'environment',

            'surface_type',

            'allowed_uses',

            'hourly_price_clp',

            'equipments',

            'amenities',

            'rules',

            'access_instructions',

            'additional_features',

        ]

        widgets = {

            'name': forms.TextInput(attrs={'placeholder': 'Ej: Sala de danza Ñuñoa'}),

            'description': forms.Textarea(attrs={'rows': 6}),

            'address': forms.TextInput(attrs={'placeholder': 'Ej: Av. Principal 123'}),

            'location_reference': forms.TextInput(attrs={'placeholder': 'Ej: Segundo piso'}),

            'capacity': forms.NumberInput(attrs={'min': 1}),

            'surface_m2': forms.NumberInput(attrs={'min': 1, 'step': '0.01'}),

            'surface_type': forms.TextInput(

                attrs={

                    'placeholder': (

                        'Ej: Pasto sintético, cemento, madera, arcilla...'

                    ),

                }

            ),

            'allowed_uses': forms.Textarea(

                attrs={

                    'rows': 4,

                    'placeholder': (

                        'Ej: Futbolito, partidos recreativos, '

                        'entrenamientos grupales y clases deportivas.'

                    ),

                }

            ),

            'hourly_price_clp': forms.NumberInput(attrs={'min': 1, 'step': '1'}),

            'rules': forms.Textarea(attrs={'rows': 5}),

            'access_instructions': forms.Textarea(

                attrs={

                    'rows': 4,

                    'placeholder': (

                        'Indicaciones útiles para llegar o ingresar al recinto.'

                    ),

                }

            ),

            'additional_features': forms.Textarea(

                attrs={

                    'rows': 4,

                    'placeholder': (

                        'Ej: iluminación natural, techo alto, '

                        'acceso independiente, piso amortiguado...'

                    ),

                }

            ),

        }



    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)



        self.fields['region'].queryset = (

            Region.objects.filter(is_active=True).order_by('name')

        )



        self.fields['space_type'].queryset = (

            SpaceType.objects.filter(is_active=True)

            .order_by('display_order', 'name')

        )



        self.fields['equipments'].queryset = (

            SpaceEquipment.objects.filter(is_active=True)

            .order_by('display_order', 'name')

        )



        self.fields['amenities'].queryset = (

            SpaceAmenity.objects.filter(is_active=True)

            .order_by('display_order', 'name')

        )



        self.fields['commune'].queryset = Commune.objects.none()



        if self.is_bound:

            region_id = self.data.get('region')



            if region_id:

                self.fields['commune'].queryset = (

                    Commune.objects.filter(

                        region_id=region_id,

                        is_active=True,

                    ).order_by('name')

                )



        elif (

            self.instance

            and self.instance.pk

            and self.instance.commune_id

        ):

            commune = self.instance.commune



            self.fields['region'].initial = (

                commune.region_id

            )



            self.fields['commune'].queryset = (

                Commune.objects.filter(

                    region_id=commune.region_id,

                    is_active=True,

                ).order_by('name')

            )



            self.fields['commune'].initial = (

                commune

            )



    def clean_description(self):

        description = self.cleaned_data.get('description', '').strip()

        if len(description) < 40:

            raise forms.ValidationError(

                'La descripción debe contener al menos 40 caracteres.'

            )

        return description



    def clean_cover_image(self):

        image = self.cleaned_data.get('cover_image')

        if image and image.size > 5 * 1024 * 1024:

            raise forms.ValidationError(

                'La fotografía no puede superar los 5 MB.'

            )

        return image



    def clean_gallery_images(self):

        images = self.cleaned_data.get(

            'gallery_images',

            []

        )

        if len(images) > 6:

            raise forms.ValidationError(

                'Puedes cargar un máximo de 6 fotografías adicionales.'

            )

        for image in images:

            if image.size > 5 * 1024 * 1024:

                raise forms.ValidationError(

                    'Cada fotografía adicional debe pesar 5 MB o menos.'

                )

        return images



    def clean(self):

        cleaned_data = super().clean()

        region = cleaned_data.get('region')

        commune = cleaned_data.get('commune')



        if region and commune and commune.region_id != region.id:

            self.add_error(

                'commune',

                'La comuna seleccionada no pertenece a la región indicada.'

            )



        return cleaned_data





class PublicSpaceFilterForm(forms.Form):

    """

    Filtros del catálogo público de espacios.

    """



    q = forms.CharField(

        label='¿Qué estás buscando?',

        required=False,

        widget=forms.TextInput(

            attrs={

                'placeholder': (

                    'Ej: gimnasio, sala de danza, cancha...'

                ),

            }

        ),

    )



    space_type = forms.ModelChoiceField(

        label='Tipo de espacio',

        queryset=SpaceType.objects.none(),

        required=False,

        empty_label='Todos los tipos',

    )



    region = forms.ModelChoiceField(

        label='Región',

        queryset=Region.objects.none(),

        required=False,

        empty_label='Todas las regiones',

    )



    commune = forms.ModelChoiceField(

        label='Comuna',

        queryset=Commune.objects.none(),

        required=False,

        empty_label='Todas las comunas',

    )



    min_capacity = forms.IntegerField(

        label='Capacidad mínima',

        required=False,

        min_value=1,

        widget=forms.NumberInput(

            attrs={

                'placeholder': 'Ej: 10',

            }

        ),

    )



    max_price = forms.IntegerField(

        label='Precio máximo por hora',

        required=False,

        min_value=1,

        widget=forms.NumberInput(

            attrs={

                'placeholder': 'Ej: 25000',

            }

        ),

    )



    equipments = forms.ModelMultipleChoiceField(

        label='Equipamiento',

        queryset=SpaceEquipment.objects.none(),

        required=False,

        widget=forms.CheckboxSelectMultiple,

    )



    amenities = forms.ModelMultipleChoiceField(

        label='Comodidades',

        queryset=SpaceAmenity.objects.none(),

        required=False,

        widget=forms.CheckboxSelectMultiple,

    )



    def __init__(

        self,

        *args,

        **kwargs

    ):

        super().__init__(

            *args,

            **kwargs

        )



        self.fields['space_type'].queryset = (

            SpaceType.objects

            .filter(

                is_active=True

            )

            .order_by(

                'display_order',

                'name',

            )

        )



        self.fields['region'].queryset = (

            Region.objects

            .filter(

                is_active=True

            )

            .order_by(

                'name'

            )

        )



        self.fields['equipments'].queryset = (

            SpaceEquipment.objects

            .filter(

                is_active=True

            )

            .order_by(

                'display_order',

                'name',

            )

        )



        self.fields['amenities'].queryset = (

            SpaceAmenity.objects

            .filter(

                is_active=True

            )

            .order_by(

                'display_order',

                'name',

            )

        )



        self.fields['commune'].queryset = (

            Commune.objects

            .filter(

                is_active=True

            )

            .select_related(

                'region'

            )

            .order_by(

                'name'

            )

        )



        region_id = (

            self.data.get('region')

            if self.is_bound

            else None

        )



        if region_id:

            self.fields['commune'].queryset = (

                Commune.objects

                .filter(

                    region_id=region_id,

                    is_active=True,

                )

                .select_related(

                    'region'

                )

                .order_by(

                    'name'

                )

            )





SPANISH_MONTHS = {

    1: 'Enero',

    2: 'Febrero',

    3: 'Marzo',

    4: 'Abril',

    5: 'Mayo',

    6: 'Junio',

    7: 'Julio',

    8: 'Agosto',

    9: 'Septiembre',

    10: 'Octubre',

    11: 'Noviembre',

    12: 'Diciembre',

}





def build_time_choices():

    """

    Horarios cada 15 minutos en un selector legible.

    """

    choices = [

        (

            '',

            'Selecciona una hora',

        )

    ]



    for hour in range(24):

        for minute in (

            0,

            15,

            30,

            45,

        ):

            value = (

                f'{hour:02d}:'

                f'{minute:02d}'

            )



            choices.append(

                (

                    value,

                    value,

                )

            )



    return choices





FRIENDLY_TIME_CHOICES = build_time_choices()





class SpaceAvailabilityExceptionForm(forms.ModelForm):

    """

    Excepción amigable para una fecha concreta.

    """



    date = forms.DateField(

        label='Fecha específica',

        required=True,

        widget=forms.SelectDateWidget(

            months=SPANISH_MONTHS,

            empty_label=(

                'Año',

                'Mes',

                'Día',

            ),

        ),

    )



    exception_type = forms.ChoiceField(

        label='Qué quieres hacer',

        required=True,

        choices=(

            (

                SpaceAvailabilityException

                .ExceptionType

                .BLOCKED,

                'No estará disponible este día',

            ),

            (

                SpaceAvailabilityException

                .ExceptionType

                .SPECIAL_HOURS,

                'Usar un horario especial',

            ),

        ),

        widget=forms.RadioSelect,

    )



    start_time = forms.TimeField(

        label='Hora especial de inicio',

        required=False,

        input_formats=[

            '%H:%M',

        ],

        widget=forms.Select(

            choices=FRIENDLY_TIME_CHOICES,

        ),

    )



    end_time = forms.TimeField(

        label='Hora especial de término',

        required=False,

        input_formats=[

            '%H:%M',

        ],

        widget=forms.Select(

            choices=FRIENDLY_TIME_CHOICES,

        ),

    )



    reason = forms.CharField(

        label='Motivo',

        required=False,

        max_length=300,

        widget=forms.TextInput(

            attrs={

                'placeholder': (

                    'Ej: mantenimiento, feriado, evento privado...'

                ),

            }

        ),

    )



    class Meta:

        model = SpaceAvailabilityException



        fields = [

            'date',

            'exception_type',

            'start_time',

            'end_time',

            'reason',

        ]



    def __init__(

        self,

        *args,

        **kwargs

    ):

        super().__init__(

            *args,

            **kwargs

        )



        if not self.is_bound:

            self.fields['date'].initial = (

                timezone.localdate()

            )



    def clean_date(self):



        value = self.cleaned_data['date']



        if value < timezone.localdate():

            raise forms.ValidationError(

                'Selecciona una fecha de hoy en adelante.'

            )



        return value



    def clean(self):



        cleaned_data = super().clean()



        exception_type = cleaned_data.get(

            'exception_type'

        )



        start_time = cleaned_data.get(

            'start_time'

        )



        end_time = cleaned_data.get(

            'end_time'

        )



        if (

            exception_type

            == SpaceAvailabilityException

            .ExceptionType

            .BLOCKED

        ):

            cleaned_data['start_time'] = None

            cleaned_data['end_time'] = None



        elif (

            exception_type

            == SpaceAvailabilityException

            .ExceptionType

            .SPECIAL_HOURS

        ):

            if not start_time or not end_time:

                raise forms.ValidationError(

                    (

                        'Para usar un horario especial, '

                        'selecciona una hora de inicio y término.'

                    )

                )



        return cleaned_data





class SpaceAvailabilityForm(forms.ModelForm):

    """
    Ventana semanal recurrente basada en una primera fecha real.

    El usuario elige la primera fecha disponible y el sistema
    calcula automáticamente el día de la semana. De esta forma
    nunca pueden contradecirse la fecha y el día recurrente.
    """

    weekday = forms.ChoiceField(
        label='Día calculado',
        required=False,
        disabled=True,
        choices=tuple(
            SpaceAvailability
            .Weekday
            .choices
        ),
        widget=forms.Select(
            attrs={
                'data-auto-weekday': 'true',
                'aria-readonly': 'true',
                'tabindex': '-1',
            }
        ),
    )

    start_time = forms.TimeField(
        label='Hora de inicio',
        required=True,
        input_formats=[
            '%H:%M',
        ],
        widget=forms.Select(
            choices=FRIENDLY_TIME_CHOICES,
        ),
    )

    end_time = forms.TimeField(
        label='Hora de término',
        required=True,
        input_formats=[
            '%H:%M',
        ],
        widget=forms.Select(
            choices=FRIENDLY_TIME_CHOICES,
        ),
    )

    valid_from = forms.DateField(
        label='Primera fecha disponible',
        required=True,
        widget=forms.SelectDateWidget(
            months=SPANISH_MONTHS,
            empty_label=(
                'Año',
                'Mes',
                'Día',
            ),
        ),
    )

    valid_until = forms.DateField(
        label='Vigente hasta',
        required=False,
        widget=forms.SelectDateWidget(
            months=SPANISH_MONTHS,
            empty_label=(
                'Año',
                'Mes',
                'Día',
            ),
        ),
    )

    class Meta:
        model = SpaceAvailability

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
        **kwargs
    ):
        super().__init__(
            *args,
            **kwargs
        )

        if not self.is_bound:

            initial_date = None

            if (
                self.instance
                and self.instance.pk
                and self.instance.valid_from
            ):
                initial_date = (
                    self.instance.valid_from
                )

            if initial_date is None:
                initial_date = (
                    timezone.localdate()
                )

            self.fields['valid_from'].initial = (
                initial_date
            )

            self.fields['weekday'].initial = (
                initial_date.weekday()
            )

    def clean(self):

        cleaned_data = super().clean()

        valid_from = cleaned_data.get(
            'valid_from'
        )

        if valid_from:

            cleaned_data['weekday'] = (
                valid_from.weekday()
            )

        return cleaned_data


class SpaceBookingCreateForm(forms.Form):

    """

    Datos ocultos del bloque de 60 minutos seleccionado.

    """



    session_date = forms.DateField(

        widget=forms.HiddenInput,

        input_formats=[

            '%Y-%m-%d'

        ],

    )



    start_time = forms.TimeField(

        widget=forms.HiddenInput,

        input_formats=[

            '%H:%M'

        ],

    )



    end_time = forms.TimeField(

        widget=forms.HiddenInput,

        input_formats=[

            '%H:%M'

        ],

    )


