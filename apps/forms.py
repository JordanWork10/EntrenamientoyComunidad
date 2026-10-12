from django import forms
from django.contrib.auth.forms import UserCreationForm

from apps.locations.models import Commune, Region

from .models import (
    MemberProfile,
    PlatformInterest,
    User,
    normalize_rut,
    validate_rut,
)


class RegisterForm(UserCreationForm):
    """
    Formulario de Cuenta Única Universal.
    """

    first_name = forms.CharField(
        label='Nombres',
        max_length=150,
        required=True,
    )

    last_name = forms.CharField(
        label='Apellidos',
        max_length=150,
        required=True,
    )

    rut = forms.CharField(
        label='RUT',
        max_length=12,
        required=True,
        help_text='Ejemplo: 12345678-9',
    )

    email = forms.EmailField(
        label='Correo electrónico',
        required=True,
    )

    phone = forms.CharField(
        label='Teléfono',
        max_length=20,
        required=True,
    )

    birth_date = forms.DateField(
        label='Fecha de nacimiento',
        required=True,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
            }
        ),
    )

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

    activity_level = forms.ChoiceField(
        label='Nivel de actividad física',
        choices=[
            ('', 'Selecciona tu nivel'),
            *MemberProfile.ActivityLevel.choices,
        ],
        required=True,
    )

    interests = forms.ModelMultipleChoiceField(
        label='¿Qué te interesa?',
        queryset=PlatformInterest.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    emergency_contact_name = forms.CharField(
        label='Nombre del contacto de emergencia',
        max_length=150,
        required=True,
    )

    emergency_contact_relationship = forms.CharField(
        label='Relación o parentesco',
        max_length=80,
        required=True,
    )

    emergency_contact_phone = forms.CharField(
        label='Teléfono de emergencia',
        max_length=20,
        required=True,
    )

    fitness_declaration_accepted = forms.BooleanField(
        label=(
            'Declaro que la información proporcionada es correcta '
            'y que conozco mi condición física para participar '
            'en actividades deportivas.'
        ),
        required=True,
    )

    protected_payment_accepted = forms.BooleanField(
        label=(
            'Acepto las condiciones asociadas al sistema '
            'de reservas y pagos protegidos de la plataforma.'
        ),
        required=True,
    )

    terms_accepted = forms.BooleanField(
        label='Acepto los términos y condiciones.',
        required=True,
    )

    privacy_accepted = forms.BooleanField(
        label='Acepto la política de privacidad.',
        required=True,
    )

    class Meta:
        model = User

        fields = [
            'first_name',
            'last_name',
            'rut',
            'email',
            'phone',
            'birth_date',
            'commune',
            'password1',
            'password2',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['region'].queryset = Region.objects.filter(
            is_active=True
        ).order_by('name')

        self.fields['interests'].queryset = (
            PlatformInterest.objects.filter(
                is_active=True
            ).order_by(
                'display_order',
                'name',
            )
        )

        if self.is_bound:
            region_id = self.data.get('region')

            if region_id:
                self.fields['commune'].queryset = (
                    Commune.objects.filter(
                        region_id=region_id,
                        is_active=True,
                    ).order_by('name')
                )

        elif self.instance.pk and self.instance.commune:
            self.fields['commune'].queryset = (
                Commune.objects.filter(
                    region=self.instance.commune.region,
                    is_active=True,
                ).order_by('name')
            )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()

        if User.objects.filter(
            email__iexact=email
        ).exists():
            raise forms.ValidationError(
                'Ya existe una cuenta asociada a este correo.'
            )

        return email

    def clean_rut(self):
        rut = normalize_rut(
            self.cleaned_data['rut']
        )

        validate_rut(rut)

        if User.objects.filter(rut=rut).exists():
            raise forms.ValidationError(
                'Ya existe una cuenta asociada a este RUT.'
            )

        return rut

    def clean(self):
        cleaned_data = super().clean()

        region = cleaned_data.get('region')
        commune = cleaned_data.get('commune')

        if (
            region
            and commune
            and commune.region_id != region.id
        ):
            self.add_error(
                'commune',
                'La comuna seleccionada no pertenece a la región indicada.'
            )

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)

        user.email = self.cleaned_data['email']
        user.username = self.cleaned_data['email']

        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']

        user.rut = self.cleaned_data['rut']
        user.phone = self.cleaned_data['phone']
        user.birth_date = self.cleaned_data['birth_date']
        user.commune = self.cleaned_data['commune']

        user.terms_accepted = (
            self.cleaned_data['terms_accepted']
        )

        user.privacy_accepted = (
            self.cleaned_data['privacy_accepted']
        )

        if commit:
            user.save()

        return user