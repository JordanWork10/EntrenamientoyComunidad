from datetime import date
from uuid import uuid4

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


# =========================================================
# VALIDACIÓN DE FOTO DE PERFIL
# =========================================================

PROFILE_IMAGE_MAX_SIZE = 5 * 1024 * 1024

ALLOWED_PROFILE_IMAGE_EXTENSIONS = (
    '.jpg',
    '.jpeg',
    '.png',
    '.webp',
)

ALLOWED_PROFILE_IMAGE_CONTENT_TYPES = {
    'image/jpeg',
    'image/png',
    'image/webp',
}


def validate_profile_image_file(image):
    """
    Valida la fotografía de perfil.

    Reglas:
    - Campo opcional.
    - Máximo 5 MB.
    - JPG, JPEG, PNG o WEBP.
    """

    if not image:
        return image

    image_name = getattr(
        image,
        'name',
        ''
    ).lower()

    if (
        image_name
        and not image_name.endswith(
            ALLOWED_PROFILE_IMAGE_EXTENSIONS
        )
    ):
        raise forms.ValidationError(
            (
                'La imagen debe estar en formato '
                'JPG, JPEG, PNG o WEBP.'
            )
        )

    image_size = getattr(
        image,
        'size',
        None
    )

    if (
        image_size is not None
        and image_size > PROFILE_IMAGE_MAX_SIZE
    ):
        raise forms.ValidationError(
            'La imagen de perfil no puede superar los 5 MB.'
        )

    content_type = getattr(
        image,
        'content_type',
        None
    )

    if (
        content_type
        and content_type not in ALLOWED_PROFILE_IMAGE_CONTENT_TYPES
    ):
        raise forms.ValidationError(
            (
                'El archivo seleccionado no corresponde '
                'a una imagen JPG, PNG o WEBP válida.'
            )
        )

    return image


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
        widget=forms.SelectDateWidget(
            years=range(
                date.today().year - 18,
                date.today().year - 101,
                -1
            ),
        ),
    )

    gender = forms.ChoiceField(
        label='Género (opcional)',
        choices=[
            (
                '',
                'Selecciona una opción (opcional)'
            ),
            *User.Gender.choices,
        ],
        required=False,
    )

    profile_image = forms.ImageField(
        label='Foto de perfil (opcional)',
        required=False,
        help_text=(
            'Formatos permitidos: JPG, JPEG, PNG o WEBP. '
            'Máximo 5 MB.'
        ),
        widget=forms.ClearableFileInput(
            attrs={
                'accept': (
                    '.jpg,.jpeg,.png,.webp,'
                    'image/jpeg,image/png,image/webp'
                ),
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
            'gender',
            'profile_image',
            'commune',
            'password1',
            'password2',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['region'].queryset = (
            Region.objects
            .filter(
                is_active=True
            )
            .order_by(
                'name'
            )
        )

        self.fields['interests'].queryset = (
            PlatformInterest.objects
            .filter(
                is_active=True
            )
            .order_by(
                'display_order',
                'name',
            )
        )

        if self.is_bound:
            region_id = self.data.get('region')

            if region_id:
                self.fields['commune'].queryset = (
                    Commune.objects
                    .filter(
                        region_id=region_id,
                        is_active=True,
                    )
                    .order_by(
                        'name'
                    )
                )

        elif self.instance.pk and self.instance.commune:
            self.fields['commune'].queryset = (
                Commune.objects
                .filter(
                    region=self.instance.commune.region,
                    is_active=True,
                )
                .order_by(
                    'name'
                )
            )

    def clean_email(self):
        email = (
            self.cleaned_data['email']
            .strip()
            .lower()
        )

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

        if User.objects.filter(
            rut=rut
        ).exists():
            raise forms.ValidationError(
                'Ya existe una cuenta asociada a este RUT.'
            )

        return rut

    def clean_profile_image(self):
        return validate_profile_image_file(
            self.cleaned_data.get(
                'profile_image'
            )
        )

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
                (
                    'La comuna seleccionada no pertenece '
                    'a la región indicada.'
                )
            )

        return cleaned_data

    def save(self, commit=True):
        user = super().save(
            commit=False
        )

        user.email = (
            self.cleaned_data['email']
        )

        # Identificador tecnico unico: no es correo ni RUT.
        # Permanece estable aunque la persona cambie su email.
        user.username = f'usuario_{uuid4().hex}'

        user.first_name = (
            self.cleaned_data['first_name']
        )

        user.last_name = (
            self.cleaned_data['last_name']
        )

        user.rut = (
            self.cleaned_data['rut']
        )

        user.phone = (
            self.cleaned_data['phone']
        )

        user.birth_date = (
            self.cleaned_data['birth_date']
        )

        user.gender = (
            self.cleaned_data.get(
                'gender',
                ''
            )
        )

        user.profile_image = (
            self.cleaned_data.get(
                'profile_image'
            )
        )

        user.commune = (
            self.cleaned_data['commune']
        )

        user.terms_accepted = (
            self.cleaned_data['terms_accepted']
        )

        user.privacy_accepted = (
            self.cleaned_data['privacy_accepted']
        )

        if commit:
            user.save()

        return user


class ProfileSettingsForm(forms.ModelForm):
    """
    Permite editar la información de la Cuenta Única Universal
    y del Perfil de Miembro.
    """

    gender = forms.ChoiceField(
        label='Género (opcional)',
        choices=[
            (
                '',
                'Selecciona una opción (opcional)'
            ),
            *User.Gender.choices,
        ],
        required=False,
    )

    profile_image = forms.ImageField(
        label='Foto de perfil (opcional)',
        required=False,
        help_text=(
            'Formatos permitidos: JPG, JPEG, PNG o WEBP. '
            'Máximo 5 MB.'
        ),
        widget=forms.ClearableFileInput(
            attrs={
                'accept': (
                    '.jpg,.jpeg,.png,.webp,'
                    'image/jpeg,image/png,image/webp'
                ),
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
        label='Intereses',
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

    class Meta:
        model = User

        fields = [
            'first_name',
            'last_name',
            'email',
            'phone',
            'birth_date',
            'gender',
            'profile_image',
        ]

        labels = {
            'first_name': 'Nombres',
            'last_name': 'Apellidos',
            'email': 'Correo electrónico',
            'phone': 'Teléfono',
            'birth_date': 'Fecha de nacimiento',
            'gender': 'Género (opcional)',
            'profile_image': 'Foto de perfil (opcional)',
        }

        widgets = {
            'birth_date': forms.SelectDateWidget(
                years=range(
                    date.today().year - 18,
                    date.today().year - 101,
                    -1
                ),
            ),
        }

    def __init__(
        self,
        *args,
        member_profile=None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.member_profile = member_profile

        self.fields['region'].queryset = (
            Region.objects
            .filter(is_active=True)
            .order_by('name')
        )

        self.fields['interests'].queryset = (
            PlatformInterest.objects
            .filter(is_active=True)
            .order_by(
                'display_order',
                'name',
            )
        )

        if self.is_bound:
            region_id = self.data.get('region')

            if region_id:
                self.fields['commune'].queryset = (
                    Commune.objects
                    .filter(
                        region_id=region_id,
                        is_active=True,
                    )
                    .order_by('name')
                )

        elif self.instance.pk and self.instance.commune:
            self.fields['region'].initial = (
                self.instance.commune.region
            )

            self.fields['commune'].queryset = (
                Commune.objects
                .filter(
                    region=self.instance.commune.region,
                    is_active=True,
                )
                .order_by('name')
            )

            self.fields['commune'].initial = (
                self.instance.commune
            )

        if self.member_profile:
            self.fields['activity_level'].initial = (
                self.member_profile.activity_level
            )

            self.fields['interests'].initial = (
                self.member_profile.interests.all()
            )

            self.fields['emergency_contact_name'].initial = (
                self.member_profile.emergency_contact_name
            )

            self.fields[
                'emergency_contact_relationship'
            ].initial = (
                self.member_profile
                .emergency_contact_relationship
            )

            self.fields['emergency_contact_phone'].initial = (
                self.member_profile.emergency_contact_phone
            )

    def clean_email(self):
        email = (
            self.cleaned_data['email']
            .strip()
            .lower()
        )

        existing_user = (
            User.objects
            .filter(email__iexact=email)
            .exclude(pk=self.instance.pk)
            .exists()
        )

        if existing_user:
            raise forms.ValidationError(
                'Ya existe otra cuenta asociada a este correo.'
            )

        return email

    def clean_profile_image(self):
        return validate_profile_image_file(
            self.cleaned_data.get(
                'profile_image'
            )
        )

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
                (
                    'La comuna seleccionada no pertenece '
                    'a la región indicada.'
                )
            )

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)

        # El correo puede cambiar, pero el username tecnico no.
        user.email = self.cleaned_data['email']
        user.commune = self.cleaned_data['commune']

        if commit:
            user.save()

            if self.member_profile:
                self.member_profile.activity_level = (
                    self.cleaned_data['activity_level']
                )

                self.member_profile.emergency_contact_name = (
                    self.cleaned_data[
                        'emergency_contact_name'
                    ]
                )

                self.member_profile.emergency_contact_relationship = (
                    self.cleaned_data[
                        'emergency_contact_relationship'
                    ]
                )

                self.member_profile.emergency_contact_phone = (
                    self.cleaned_data[
                        'emergency_contact_phone'
                    ]
                )

                self.member_profile.save()

                self.member_profile.interests.set(
                    self.cleaned_data['interests']
                )

        return user
