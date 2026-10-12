from django import forms

from django.core.exceptions import ValidationError
from django.db.models import Q

from django.utils import timezone



from apps.locations.models import Commune, Region
from apps.spaces.models import SpaceBooking



from .models import Activity, ActivityCategory, ActivityRegistration





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





def build_activity_time_choices():

    """

    Genera horarios cada 30 minutos.

    """



    choices = [

        ('', 'Selecciona una hora'),

    ]



    for hour in range(24):

        for minute in (0, 30):

            value = f'{hour:02d}:{minute:02d}'

            choices.append(

                (

                    value,

                    value,

                )

            )



    return choices





ACTIVITY_TIME_CHOICES = build_activity_time_choices()





class CommuneChoiceField(forms.ModelChoiceField):

    """

    Muestra solamente el nombre de la comuna.



    La región ya se selecciona en un campo separado,

    por lo que no necesitamos repetirla.

    """



    def label_from_instance(self, obj):

        return obj.name





class CommunityActivityForm(forms.ModelForm):

    """

    Formulario para crear y editar

    actividades comunitarias.

    """



    region = forms.ModelChoiceField(

        label='Región',

        queryset=Region.objects.none(),

        required=True,

        empty_label='Selecciona una región',

        widget=forms.Select(

            attrs={

                'class': 'activities-form-control',

            }

        ),

    )



    commune = CommuneChoiceField(

        label='Comuna',

        queryset=Commune.objects.none(),

        required=True,

        empty_label='Primero selecciona una región',

        widget=forms.Select(

            attrs={

                'class': 'activities-form-control',

            }

        ),

    )



    date = forms.DateField(

        label='Fecha',

        required=True,

        widget=forms.SelectDateWidget(

            years=range(

                timezone.localdate().year,

                timezone.localdate().year + 3,

            ),

            months=SPANISH_MONTHS,

            empty_label=(

                'Año',

                'Mes',

                'Día',

            ),

            attrs={

                'class': (

                    'activities-form-control '

                    'activities-date-select'

                ),

            },

        ),

    )



    start_time = forms.TimeField(

        label='Hora de inicio',

        required=True,

        input_formats=[

            '%H:%M',

            '%H:%M:%S',

        ],

        widget=forms.Select(

            choices=ACTIVITY_TIME_CHOICES,

            attrs={

                'class': 'activities-form-control',

            },

        ),

    )



    end_time = forms.TimeField(

        label='Hora de término',

        required=True,

        input_formats=[

            '%H:%M',

            '%H:%M:%S',

        ],

        widget=forms.Select(

            choices=ACTIVITY_TIME_CHOICES,

            attrs={

                'class': 'activities-form-control',

            },

        ),

    )



    class Meta:

        model = Activity



        fields = [

            'category',

            'title',

            'description',

            'image',

            'date',

            'start_time',

            'end_time',

            'capacity',

            'level',

            'region',

            'commune',

            'meeting_point',

            'location_reference',

            'route_or_destination',

            'requirements',

        ]



        widgets = {

            'category': forms.Select(

                attrs={

                    'class': 'activities-form-control',

                }

            ),



            'title': forms.TextInput(

                attrs={

                    'class': 'activities-form-control',

                    'placeholder': (

                        'Ej: Salida en bicicleta — '

                        'Ruta Buin a Paine'

                    ),

                    'maxlength': 140,

                }

            ),



            'description': forms.Textarea(

                attrs={

                    'class': (

                        'activities-form-control '

                        'activities-form-textarea'

                    ),

                    'rows': 5,

                    'placeholder': (

                        'Cuenta brevemente qué harán, '

                        'el ritmo esperado y qué debería '

                        'saber alguien antes de unirse.'

                    ),

                }

            ),



            'image': forms.ClearableFileInput(

                attrs={

                    'class': (

                        'activities-form-control '

                        'activities-form-file'

                    ),

                    'accept': 'image/*',

                }

            ),



            'capacity': forms.NumberInput(

                attrs={

                    'class': 'activities-form-control',

                    'min': 1,

                    'max': 100,

                    'step': 1,

                    'placeholder': 'Ej: 8',

                }

            ),



            'level': forms.Select(

                attrs={

                    'class': 'activities-form-control',

                }

            ),



            'meeting_point': forms.TextInput(

                attrs={

                    'class': 'activities-form-control',

                    'placeholder': 'Ej: Plaza de Buin',

                    'maxlength': 180,

                }

            ),



            'location_reference': forms.TextInput(

                attrs={

                    'class': 'activities-form-control',

                    'placeholder': (

                        'Ej: Frente a la municipalidad'

                    ),

                    'maxlength': 255,

                }

            ),



            'route_or_destination': forms.TextInput(

                attrs={

                    'class': 'activities-form-control',

                    'placeholder': (

                        'Ej: Buin → Paine → Buin'

                    ),

                    'maxlength': 255,

                }

            ),



            'requirements': forms.Textarea(

                attrs={

                    'class': (

                        'activities-form-control '

                        'activities-form-textarea'

                    ),

                    'rows': 4,

                    'placeholder': (

                        'Ej: Bicicleta en buen estado, '

                        'casco obligatorio y llevar agua.'

                    ),

                }

            ),

        }



    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)



        self.fields['category'].queryset = (

            ActivityCategory.objects

            .filter(

                is_active=True,

            )

            .order_by(

                'name',

            )

        )



        self.fields['region'].queryset = (

            Region.objects

            .filter(

                is_active=True,

            )

            .order_by(

                'name',

            )

        )



        self.fields['commune'].queryset = (

            Commune.objects.none()

        )



        self.fields['category'].empty_label = (

            'Selecciona una categoría'

        )



        selected_region_id = None

        selected_commune = None



        # ==========================================

        # EDICIÓN

        # ==========================================



        if (

            self.instance

            and self.instance.pk

        ):



            if self.instance.commune_id:

                selected_commune = (

                    self.instance.commune

                )



                selected_region_id = (

                    selected_commune.region_id

                )



                self.fields['region'].initial = (

                    selected_region_id

                )



                self.fields['commune'].initial = (

                    selected_commune.pk

                )



            # Importante:

            # los valores del Select usan HH:MM,

            # mientras TimeField puede entregar HH:MM:SS.

            # Los normalizamos para que aparezcan

            # seleccionados correctamente al editar.



            if (

                not self.is_bound

                and self.instance.start_time

            ):

                self.initial['start_time'] = (

                    self.instance

                    .start_time

                    .strftime('%H:%M')

                )



            if (

                not self.is_bound

                and self.instance.end_time

            ):

                self.initial['end_time'] = (

                    self.instance

                    .end_time

                    .strftime('%H:%M')

                )



        # ==========================================

        # POST

        # ==========================================



        if self.is_bound:

            selected_region_id = (

                self.data.get('region')

            )



        # ==========================================

        # CREACIÓN CON INITIAL

        # ==========================================



        elif not self.instance.pk:



            initial_region = (

                self.initial.get('region')

            )



            if isinstance(

                initial_region,

                Region,

            ):

                selected_region_id = (

                    initial_region.pk

                )



            elif initial_region:

                selected_region_id = (

                    initial_region

                )



        # ==========================================

        # COMUNAS SEGÚN REGIÓN

        # ==========================================



        if selected_region_id:



            self.fields['commune'].queryset = (

                Commune.objects

                .filter(

                    region_id=selected_region_id,

                    is_active=True,

                )

                .select_related(

                    'region',

                )

                .order_by(

                    'name',

                )

            )



            self.fields[

                'commune'

            ].empty_label = (

                'Selecciona una comuna'

            )



            self.fields[

                'commune'

            ].widget.attrs.pop(

                'disabled',

                None,

            )



            if selected_commune:

                self.fields[

                    'commune'

                ].initial = (

                    selected_commune.pk

                )



        else:



            self.fields[

                'commune'

            ].widget.attrs[

                'disabled'

            ] = True



    def clean_date(self):

        activity_date = (

            self.cleaned_data.get('date')

        )



        if (

            activity_date is not None

            and activity_date

            < timezone.localdate()

        ):

            raise ValidationError(

                'La actividad no puede realizarse '

                'en una fecha pasada.'

            )



        return activity_date



    def clean_capacity(self):

        capacity = (

            self.cleaned_data.get(

                'capacity'

            )

        )



        if capacity is None:

            return capacity



        if capacity < 1:

            raise ValidationError(

                'La actividad debe permitir '

                'al menos 1 participante.'

            )



        if capacity > 100:

            raise ValidationError(

                'Por ahora una actividad comunitaria '

                'puede tener hasta 100 cupos.'

            )



        if (

            self.instance

            and self.instance.pk

        ):



            active_registrations = (

                ActivityRegistration.objects

                .filter(

                    activity=self.instance,

                    status=(

                        ActivityRegistration

                        .Status

                        .REGISTERED

                    ),

                )

                .count()

            )



            if (

                capacity

                < active_registrations

            ):

                raise ValidationError(

                    'No puedes dejar menos cupos '

                    'que personas actualmente inscritas.'

                )



        return capacity



    def clean(self):

        cleaned_data = super().clean()



        start_time = (

            cleaned_data.get(

                'start_time'

            )

        )



        end_time = (

            cleaned_data.get(

                'end_time'

            )

        )



        region = (

            cleaned_data.get(

                'region'

            )

        )



        commune = (

            cleaned_data.get(

                'commune'

            )

        )



        if (

            start_time is not None

            and end_time is not None

            and end_time <= start_time

        ):

            self.add_error(

                'end_time',

                (

                    'La hora de término debe ser '

                    'posterior a la hora de inicio.'

                ),

            )



        if (

            region is not None

            and commune is not None

            and commune.region_id

            != region.id

        ):

            self.add_error(

                'commune',

                (

                    'La comuna seleccionada no '

                    'pertenece a la región indicada.'

                ),

            )



        return cleaned_data

class SpaceBookingSelect(forms.Select):
    """
    Agrega metadatos a cada reserva confirmada para que
    el formulario pueda precargar fecha, horario y ubicación.
    """

    def create_option(
        self,
        name,
        value,
        label,
        selected,
        index,
        subindex=None,
        attrs=None,
    ):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )

        booking = getattr(
            value,
            'instance',
            None,
        )

        if booking is not None:
            option['attrs']['data-date'] = (
                booking.session_date.isoformat()
            )
            option['attrs']['data-start'] = (
                booking.start_time.strftime('%H:%M')
            )
            option['attrs']['data-end'] = (
                booking.end_time.strftime('%H:%M')
            )
            option['attrs']['data-region'] = (
                booking.space.commune.region_id
            )
            option['attrs']['data-commune'] = (
                booking.space.commune_id
            )
            option['attrs']['data-meeting'] = (
                booking.space_name_snapshot
                or booking.space.name
            )
            option['attrs']['data-reference'] = (
                booking.address_snapshot
                or booking.space.address
            )

        return option


class SpaceBookingChoiceField(forms.ModelChoiceField):
    """
    Presenta una reserva de espacio con fecha,
    horario y nombre del recinto.
    """

    def label_from_instance(self, obj):
        return (
            f'{obj.session_date:%d/%m/%Y} · '
            f'{obj.start_time:%H:%M}–{obj.end_time:%H:%M} · '
            f'{obj.space_name_snapshot}'
        )


class ProfessionalActivityForm(forms.ModelForm):
    """
    Formulario para crear y editar actividades profesionales.

    Solo la vista decide qué Perfil Profesional será propietario.
    El formulario filtra reservas de espacio confirmadas que
    pertenecen a la cuenta autenticada.
    """

    region = forms.ModelChoiceField(
        label='Región',
        queryset=Region.objects.none(),
        required=False,
        empty_label='Selecciona una región',
        widget=forms.Select(
            attrs={
                'class': 'activities-form-control',
            }
        ),
    )

    commune = CommuneChoiceField(
        label='Comuna',
        queryset=Commune.objects.none(),
        required=False,
        empty_label='Primero selecciona una región',
        widget=forms.Select(
            attrs={
                'class': 'activities-form-control',
            }
        ),
    )

    space_booking = SpaceBookingChoiceField(
        label='Reserva de espacio confirmada',
        queryset=SpaceBooking.objects.none(),
        required=False,
        empty_label='Sin reserva asociada',
        widget=SpaceBookingSelect(
            attrs={
                'class': 'activities-form-control',
            }
        ),
    )

    date = forms.DateField(
        label='Fecha',
        required=True,
        widget=forms.SelectDateWidget(
            years=range(
                timezone.localdate().year,
                timezone.localdate().year + 3,
            ),
            months=SPANISH_MONTHS,
            empty_label=(
                'Año',
                'Mes',
                'Día',
            ),
            attrs={
                'class': (
                    'activities-form-control '
                    'activities-date-select'
                ),
            },
        ),
    )

    start_time = forms.TimeField(
        label='Hora de inicio',
        required=True,
        input_formats=[
            '%H:%M',
            '%H:%M:%S',
        ],
        widget=forms.Select(
            choices=ACTIVITY_TIME_CHOICES,
            attrs={
                'class': 'activities-form-control',
            },
        ),
    )

    end_time = forms.TimeField(
        label='Hora de término',
        required=True,
        input_formats=[
            '%H:%M',
            '%H:%M:%S',
        ],
        widget=forms.Select(
            choices=ACTIVITY_TIME_CHOICES,
            attrs={
                'class': 'activities-form-control',
            },
        ),
    )

    class Meta:
        model = Activity

        fields = [
            'category',
            'title',
            'description',
            'image',
            'modality',
            'date',
            'start_time',
            'end_time',
            'capacity',
            'level',
            'price',
            'space_booking',
            'region',
            'commune',
            'meeting_point',
            'location_reference',
            'requirements',
            'online_access_info',
        ]

        widgets = {
            'category': forms.Select(
                attrs={
                    'class': 'activities-form-control',
                }
            ),
            'title': forms.TextInput(
                attrs={
                    'class': 'activities-form-control',
                    'placeholder': (
                        'Ej: Clase grupal de entrenamiento funcional'
                    ),
                    'maxlength': 140,
                }
            ),
            'description': forms.Textarea(
                attrs={
                    'class': (
                        'activities-form-control '
                        'activities-form-textarea'
                    ),
                    'rows': 5,
                    'placeholder': (
                        'Explica qué trabajarán, a quién está dirigida '
                        'la actividad y qué puede esperar cada participante.'
                    ),
                }
            ),
            'image': forms.ClearableFileInput(
                attrs={
                    'class': (
                        'activities-form-control '
                        'activities-form-file'
                    ),
                    'accept': 'image/*',
                }
            ),
            'modality': forms.Select(
                attrs={
                    'class': 'activities-form-control',
                }
            ),
            'capacity': forms.NumberInput(
                attrs={
                    'class': 'activities-form-control',
                    'min': 1,
                    'max': 200,
                    'step': 1,
                    'placeholder': 'Ej: 10',
                }
            ),
            'level': forms.Select(
                attrs={
                    'class': 'activities-form-control',
                }
            ),
            'price': forms.NumberInput(
                attrs={
                    'class': 'activities-form-control',
                    'min': 0,
                    'max': 5000000,
                    'step': 500,
                    'placeholder': 'Ej: 8000',
                }
            ),
            'meeting_point': forms.TextInput(
                attrs={
                    'class': 'activities-form-control',
                    'placeholder': (
                        'Ej: Recepción del gimnasio o Sala 2'
                    ),
                    'maxlength': 180,
                }
            ),
            'location_reference': forms.TextInput(
                attrs={
                    'class': 'activities-form-control',
                    'placeholder': (
                        'Dirección o referencia de llegada'
                    ),
                    'maxlength': 255,
                }
            ),
            'requirements': forms.Textarea(
                attrs={
                    'class': (
                        'activities-form-control '
                        'activities-form-textarea'
                    ),
                    'rows': 4,
                    'placeholder': (
                        'Ej: Llevar agua, ropa deportiva '
                        'y llegar 10 minutos antes.'
                    ),
                }
            ),
            'online_access_info': forms.Textarea(
                attrs={
                    'class': (
                        'activities-form-control '
                        'activities-form-textarea'
                    ),
                    'rows': 4,
                    'placeholder': (
                        'Ej: El enlace de acceso se entregará '
                        'a las personas inscritas.'
                    ),
                }
            ),
        }

    def __init__(
        self,
        *args,
        user=None,
        professional_profile=None,
        **kwargs,
    ):
        self.user = user
        self.professional_profile = professional_profile

        super().__init__(
            *args,
            **kwargs,
        )

        self.fields['category'].queryset = (
            ActivityCategory.objects
            .filter(
                is_active=True,
            )
            .order_by(
                'name',
            )
        )

        self.fields['category'].empty_label = (
            'Selecciona una categoría'
        )

        self.fields['region'].queryset = (
            Region.objects
            .filter(
                is_active=True,
            )
            .order_by(
                'name',
            )
        )

        self.fields['commune'].queryset = (
            Commune.objects.none()
        )

        confirmed_bookings = (
            SpaceBooking.objects.none()
        )

        if self.user is not None:
            confirmed_bookings = (
                SpaceBooking.objects
                .filter(
                    booked_by=self.user,
                    status=(
                        SpaceBooking
                        .Status
                        .CONFIRMED
                    ),
                    session_date__gte=(
                        timezone.localdate()
                    ),
                )
                .select_related(
                    'space',
                    'space__commune',
                    'space__commune__region',
                )
                .order_by(
                    'session_date',
                    'start_time',
                )
            )

            if (
                self.instance
                and self.instance.pk
                and self.instance.space_booking_id
            ):
                confirmed_bookings = (
                    SpaceBooking.objects
                    .filter(
                        Q(
                            booked_by=self.user,
                            status=(
                                SpaceBooking
                                .Status
                                .CONFIRMED
                            ),
                            session_date__gte=(
                                timezone.localdate()
                            ),
                        )
                        | Q(
                            pk=(
                                self.instance
                                .space_booking_id
                            )
                        )
                    )
                    .select_related(
                        'space',
                        'space__commune',
                        'space__commune__region',
                    )
                    .distinct()
                    .order_by(
                        'session_date',
                        'start_time',
                    )
                )

        self.fields['space_booking'].queryset = (
            confirmed_bookings
        )

        selected_region_id = None
        selected_commune = None

        if (
            self.instance
            and self.instance.pk
        ):
            if self.instance.commune_id:
                selected_commune = (
                    self.instance.commune
                )
                selected_region_id = (
                    selected_commune.region_id
                )
                self.fields['region'].initial = (
                    selected_region_id
                )
                self.fields['commune'].initial = (
                    selected_commune.pk
                )

            if (
                not self.is_bound
                and self.instance.start_time
            ):
                self.initial['start_time'] = (
                    self.instance
                    .start_time
                    .strftime('%H:%M')
                )

            if (
                not self.is_bound
                and self.instance.end_time
            ):
                self.initial['end_time'] = (
                    self.instance
                    .end_time
                    .strftime('%H:%M')
                )

        if self.is_bound:
            selected_region_id = (
                self.data.get('region')
            )

        elif (
            not self.instance.pk
            and self.initial.get('region')
        ):
            initial_region = (
                self.initial.get('region')
            )

            if isinstance(
                initial_region,
                Region,
            ):
                selected_region_id = (
                    initial_region.pk
                )

            else:
                selected_region_id = (
                    initial_region
                )

        if selected_region_id:
            self.fields['commune'].queryset = (
                Commune.objects
                .filter(
                    region_id=selected_region_id,
                    is_active=True,
                )
                .select_related(
                    'region',
                )
                .order_by(
                    'name',
                )
            )

            self.fields['commune'].empty_label = (
                'Selecciona una comuna'
            )

            self.fields[
                'commune'
            ].widget.attrs.pop(
                'disabled',
                None,
            )

            if selected_commune:
                self.fields[
                    'commune'
                ].initial = (
                    selected_commune.pk
                )

        else:
            self.fields[
                'commune'
            ].widget.attrs[
                'disabled'
            ] = True

    def clean_date(self):
        activity_date = (
            self.cleaned_data.get(
                'date'
            )
        )

        if (
            activity_date is not None
            and activity_date
            < timezone.localdate()
        ):
            raise ValidationError(
                'La actividad no puede realizarse '
                'en una fecha pasada.'
            )

        return activity_date

    def clean_capacity(self):
        capacity = (
            self.cleaned_data.get(
                'capacity'
            )
        )

        if capacity is None:
            return capacity

        if capacity < 1:
            raise ValidationError(
                'La actividad debe permitir '
                'al menos 1 participante.'
            )

        if capacity > 200:
            raise ValidationError(
                'Por ahora una actividad profesional '
                'puede tener hasta 200 cupos.'
            )

        if (
            self.instance
            and self.instance.pk
        ):
            active_registrations = (
                ActivityRegistration.objects
                .filter(
                    activity=self.instance,
                    status=(
                        ActivityRegistration
                        .Status
                        .REGISTERED
                    ),
                )
                .count()
            )

            if capacity < active_registrations:
                raise ValidationError(
                    'No puedes dejar menos cupos '
                    'que personas actualmente inscritas.'
                )

        return capacity

    def clean_price(self):
        price = (
            self.cleaned_data.get(
                'price'
            )
        )

        if price is None:
            return 0

        if price < 0:
            raise ValidationError(
                'El precio no puede ser negativo.'
            )

        if price > 5000000:
            raise ValidationError(
                'Revisa el precio ingresado.'
            )

        return price

    def clean(self):
        cleaned_data = super().clean()

        modality = cleaned_data.get(
            'modality'
        )
        activity_date = cleaned_data.get(
            'date'
        )
        start_time = cleaned_data.get(
            'start_time'
        )
        end_time = cleaned_data.get(
            'end_time'
        )
        region = cleaned_data.get(
            'region'
        )
        commune = cleaned_data.get(
            'commune'
        )
        meeting_point = cleaned_data.get(
            'meeting_point'
        )
        online_access_info = cleaned_data.get(
            'online_access_info'
        )
        space_booking = cleaned_data.get(
            'space_booking'
        )

        if (
            start_time is not None
            and end_time is not None
            and end_time <= start_time
        ):
            self.add_error(
                'end_time',
                (
                    'La hora de término debe ser '
                    'posterior a la hora de inicio.'
                ),
            )

        if (
            region is not None
            and commune is not None
            and commune.region_id
            != region.id
        ):
            self.add_error(
                'commune',
                (
                    'La comuna seleccionada no '
                    'pertenece a la región indicada.'
                ),
            )

        if (
            modality
            in [
                Activity.Modality.IN_PERSON,
                Activity.Modality.HYBRID,
            ]
        ):
            if space_booking is None:
                if region is None:
                    self.add_error(
                        'region',
                        (
                            'Selecciona la región donde '
                            'se realizará la actividad.'
                        ),
                    )

                if commune is None:
                    self.add_error(
                        'commune',
                        (
                            'Selecciona la comuna donde '
                            'se realizará la actividad.'
                        ),
                    )

                if not meeting_point:
                    self.add_error(
                        'meeting_point',
                        (
                            'Indica un punto de encuentro '
                            'para la actividad.'
                        ),
                    )

        if modality == Activity.Modality.ONLINE:
            if space_booking is not None:
                self.add_error(
                    'space_booking',
                    (
                        'Una actividad online no necesita '
                        'una reserva de espacio.'
                    ),
                )

        if (
            modality
            in [
                Activity.Modality.ONLINE,
                Activity.Modality.HYBRID,
            ]
            and not online_access_info
        ):
            self.add_error(
                'online_access_info',
                (
                    'Indica cómo recibirán el acceso '
                    'online las personas inscritas.'
                ),
            )

        if space_booking is not None:

            if (
                self.user is None
                or space_booking.booked_by_id
                != self.user.id
            ):
                self.add_error(
                    'space_booking',
                    (
                        'La reserva seleccionada no '
                        'pertenece a tu cuenta.'
                    ),
                )

            if (
                space_booking.status
                != SpaceBooking.Status.CONFIRMED
            ):
                self.add_error(
                    'space_booking',
                    (
                        'Solo puedes utilizar una '
                        'reserva confirmada.'
                    ),
                )

            if (
                activity_date
                and activity_date
                != space_booking.session_date
            ):
                self.add_error(
                    'date',
                    (
                        'La fecha debe coincidir con '
                        'la reserva seleccionada.'
                    ),
                )

            if (
                start_time
                and start_time
                < space_booking.start_time
            ):
                self.add_error(
                    'start_time',
                    (
                        'La actividad no puede comenzar '
                        'antes de la reserva.'
                    ),
                )

            if (
                end_time
                and end_time
                > space_booking.end_time
            ):
                self.add_error(
                    'end_time',
                    (
                        'La actividad no puede terminar '
                        'después de la reserva.'
                    ),
                )

        return cleaned_data

    def save(self, commit=True):
        activity = super().save(
            commit=False
        )

        space_booking = (
            self.cleaned_data.get(
                'space_booking'
            )
        )

        if (
            activity.modality
            == Activity.Modality.ONLINE
        ):
            activity.space_booking = None
            activity.commune = None
            activity.meeting_point = ''
            activity.location_reference = ''
            activity.route_or_destination = ''

        elif space_booking is not None:
            activity.space_booking = (
                space_booking
            )
            activity.commune = (
                space_booking.space.commune
            )

            if not activity.meeting_point:
                activity.meeting_point = (
                    space_booking
                    .space_name_snapshot
                    or space_booking.space.name
                )

            if not activity.location_reference:
                activity.location_reference = (
                    space_booking
                    .address_snapshot
                    or space_booking.space.address
                )

        if commit:
            activity.save()

        return activity
