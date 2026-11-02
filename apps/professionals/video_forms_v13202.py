"""Destino: apps/professionals/video_forms_v13202.py"""

from django import forms

from .video_models_v13200 import ProfessionalPortfolioVideo


class ProfessionalVideoUploadForm(forms.Form):
    title = forms.CharField(label='Título', max_length=140, strip=True)
    category = forms.ChoiceField(
        label='Tipo de video',
        choices=ProfessionalPortfolioVideo.Category.choices,
    )
    description = forms.CharField(
        label='Descripción', required=False, max_length=600,
        widget=forms.Textarea(attrs={'rows': 3}),
    )
    video = forms.FileField(
        label='Archivo MP4 o WebM',
        widget=forms.ClearableFileInput(attrs={
            'accept': '.mp4,.webm,video/mp4,video/webm',
        }),
    )
    rights_confirmed = forms.BooleanField(
        label=(
            'Confirmo que tengo autorización para publicar este contenido '
            'y que no incluye datos personales o clínicos identificables.'
        ),
        required=True,
    )


class ProfessionalVideoReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=(('approve', 'Aprobar'), ('reject', 'Rechazar')),
    )
    notes = forms.CharField(
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={'rows': 2}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('decision') == 'reject' and not cleaned.get('notes', '').strip():
            self.add_error('notes', 'Explica al profesional el motivo del rechazo.')
        return cleaned
