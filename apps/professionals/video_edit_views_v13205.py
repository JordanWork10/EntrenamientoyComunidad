"""V132.05: editar únicamente los metadatos de videos pendientes.

Destino: apps/professionals/video_edit_views_v13205.py
No cambia el archivo, la duración, las cuotas ni el estado de revisión.
"""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .models import ProfessionalProfile
from .video_models_v13200 import ProfessionalPortfolioVideo


class ProfessionalVideoMetadataForm(forms.Form):
    title = forms.CharField(
        label='Título',
        max_length=140,
        strip=True,
    )

    category = forms.ChoiceField(
        label='Tipo de video',
        choices=ProfessionalPortfolioVideo.Category.choices,
    )

    description = forms.CharField(
        label='Descripción',
        max_length=600,
        required=False,
        strip=True,
        widget=forms.Textarea(attrs={'rows': 4}),
    )


@login_required
@require_http_methods(['GET', 'POST'])
def portfolio_edit(request, public_id):
    profile = ProfessionalProfile.objects.filter(
        user=request.user,
        verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
    ).first()

    if profile is None:
        return HttpResponseForbidden(
            'Se requiere un perfil profesional verificado.'
        )

    video = get_object_or_404(
        ProfessionalPortfolioVideo,
        public_id=public_id,
        professional_profile=profile,
    )

    if video.status != ProfessionalPortfolioVideo.Status.PENDING_REVIEW:
        return HttpResponseForbidden(
            'Solo se puede editar la información de videos pendientes de revisión.'
        )

    if request.method == 'POST':
        form = ProfessionalVideoMetadataForm(request.POST)

        if form.is_valid():
            try:
                with transaction.atomic():
                    # Mantener el mismo orden de bloqueo que la moderación.
                    locked_profile = (
                        ProfessionalProfile.objects.select_for_update()
                        .filter(
                            pk=profile.pk,
                            verification_status=(
                                ProfessionalProfile.VerificationStatus.VERIFIED
                            ),
                        )
                        .first()
                    )

                    if locked_profile is None:
                        return HttpResponseForbidden(
                            'El perfil ya no está verificado.'
                        )

                    locked_video = (
                        ProfessionalPortfolioVideo.objects.select_for_update()
                        .filter(
                            pk=video.pk,
                            professional_profile=locked_profile,
                        )
                        .first()
                    )

                    if locked_video is None:
                        raise Http404('Video no encontrado.')

                    if (
                        locked_video.status
                        != ProfessionalPortfolioVideo.Status.PENDING_REVIEW
                    ):
                        return HttpResponseForbidden(
                            'El video ya fue revisado.'
                        )

                    locked_video.title = form.cleaned_data['title']
                    locked_video.category = form.cleaned_data['category']
                    locked_video.description = form.cleaned_data['description']

                    locked_video.full_clean()

                    locked_video.save(
                        update_fields=[
                            'title',
                            'category',
                            'description',
                            'updated_at',
                        ]
                    )

            except ValidationError as exc:
                form.add_error(None, ' '.join(exc.messages))
            else:
                messages.success(
                    request,
                    'La información del video quedó actualizada.',
                )

                return redirect('professionals:portfolio_manager')

    else:
        form = ProfessionalVideoMetadataForm(
            initial={
                'title': video.title,
                'category': video.category,
                'description': video.description,
            }
        )

    return render(
        request,
        'professionals/video_metadata_edit_v13205.html',
        {
            'form': form,
            'video': video,
        },
    )