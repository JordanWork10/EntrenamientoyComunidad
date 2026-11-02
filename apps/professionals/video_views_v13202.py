"""Destino: apps/professionals/video_views_v13202.py

V132.02: gestión y moderación de videos demostrativos, streaming local.
NO es un módulo de registros médicos. No se usan URLs directas al archivo.
"""

import os
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.http import (
    FileResponse, Http404, HttpResponse, HttpResponseForbidden,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import ProfessionalProfile
from .professional_video_quota_v13200 import (
    get_professional_video_quota,
    validate_professional_video_upload,
)
from .video_forms_v13202 import ProfessionalVideoReviewForm, ProfessionalVideoUploadForm
from .video_models_v13200 import ProfessionalPortfolioVideo
from .video_upload_service_v13201 import create_professional_portfolio_video


def _error_text(exc):
    if hasattr(exc, 'messages'):
        return ' '.join(exc.messages)
    return str(exc)


def _professional_profile(user):
    try:
        profile = user.professional_profile
    except (AttributeError, ProfessionalProfile.DoesNotExist):
        return None
    if profile.verification_status != ProfessionalProfile.VerificationStatus.VERIFIED:
        return None
    return profile


@login_required
@require_http_methods(['GET', 'POST'])
def portfolio_manager(request):
    profile = _professional_profile(request.user)
    if profile is None:
        return HttpResponseForbidden('Se requiere un perfil profesional verificado.')

    if request.method == 'POST':
        form = ProfessionalVideoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            values = form.cleaned_data
            try:
                create_professional_portfolio_video(
                    request.user,
                    uploaded_file=values['video'],
                    title=values['title'],
                    description=values['description'],
                    category=values['category'],
                    rights_confirmed=values['rights_confirmed'],
                )
            except ValidationError as exc:
                form.add_error(None, _error_text(exc))
            else:
                messages.success(
                    request,
                    'Video recibido correctamente. Quedó pendiente de revisión.',
                )
                return redirect('professionals:portfolio_manager')
    else:
        form = ProfessionalVideoUploadForm()

    videos = list(profile.portfolio_videos.order_by('-created_at', '-pk'))
    occupied = [v for v in videos if v.video_file or v.external_asset_id]
    quota = get_professional_video_quota(request.user)
    return render(request, 'professionals/video_portfolio_manager_v13202.html', {
        'form': form,
        'videos': videos,
        'quota': quota,
        'used_count': len(occupied),
        'used_seconds': sum(v.duration_seconds or 0 for v in occupied),
    })


@login_required
@require_POST
def portfolio_delete(request, public_id):
    profile = _professional_profile(request.user)
    if profile is None:
        return HttpResponseForbidden('Se requiere un perfil profesional verificado.')

    with transaction.atomic():
        ProfessionalProfile.objects.select_for_update().get(pk=profile.pk)
        video = get_object_or_404(
            ProfessionalPortfolioVideo.objects.select_for_update(),
            public_id=public_id, professional_profile_id=profile.pk,
        )
        saved_name = video.video_file.name if video.video_file else None
        storage = video.video_file.storage
        video.delete()
        if saved_name:
            transaction.on_commit(
                lambda name=saved_name, store=storage: store.delete(name)
            )

    messages.success(request, 'Video eliminado del portafolio.')
    return redirect('professionals:portfolio_manager')


@login_required
@require_GET
def portfolio_review_queue(request):
    if not request.user.is_staff:
        return HttpResponseForbidden('Solo administración puede revisar videos.')

    videos = ProfessionalPortfolioVideo.objects.filter(
        status=ProfessionalPortfolioVideo.Status.PENDING_REVIEW,
    ).select_related('professional_profile__user').order_by('created_at', 'pk')[:100]
    return render(request, 'professionals/video_review_queue_v13202.html', {
        'videos': videos,
        'review_form': ProfessionalVideoReviewForm(),
    })


@login_required
@require_POST
def portfolio_review_decide(request, public_id):
    if not request.user.is_staff:
        return HttpResponseForbidden('Solo administración puede revisar videos.')

    form = ProfessionalVideoReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Decisión inválida. Al rechazar debes indicar el motivo.')
        return redirect('professionals:portfolio_review_queue')

    try:
        with transaction.atomic():
            initial = get_object_or_404(
                ProfessionalPortfolioVideo.objects.only('professional_profile_id'),
                public_id=public_id,
            )
            profile = ProfessionalProfile.objects.select_for_update().get(
                pk=initial.professional_profile_id,
            )
            video = get_object_or_404(
                ProfessionalPortfolioVideo.objects.select_for_update(),
                pk=initial.pk, professional_profile=profile,
            )
            if video.status != ProfessionalPortfolioVideo.Status.PENDING_REVIEW:
                raise ValidationError('Este video ya fue revisado.')

            video.review_notes = form.cleaned_data['notes'].strip()
            if form.cleaned_data['decision'] == 'approve':
                if profile.verification_status != ProfessionalProfile.VerificationStatus.VERIFIED:
                    raise ValidationError('El profesional ya no está verificado.')
                if video.storage_backend != ProfessionalPortfolioVideo.StorageBackend.LOCAL:
                    raise ValidationError('La revisión de proveedores externos no está habilitada.')
                if not video.video_file or not video.video_file.storage.exists(video.video_file.name):
                    raise ValidationError('No se encontró el archivo privado original.')
                if video.video_file.size != video.file_size_bytes:
                    raise ValidationError('El tamaño del video cambió desde la carga.')

                other = ProfessionalPortfolioVideo.objects.filter(
                    professional_profile=profile,
                ).exclude(pk=video.pk).filter(
                    ~Q(video_file='') | ~Q(external_asset_id=''),
                )
                usage = other.aggregate(total=Sum('duration_seconds'))
                validate_professional_video_upload(
                    profile.user,
                    duration_seconds=video.duration_seconds,
                    file_size_bytes=video.file_size_bytes,
                    existing_count=other.count(),
                    existing_total_seconds=usage['total'] or 0,
                )
                video.status = ProfessionalPortfolioVideo.Status.APPROVED
                video.published_at = timezone.now()
            else:
                video.status = ProfessionalPortfolioVideo.Status.REJECTED
                video.published_at = None

            video.full_clean()
            video.save(update_fields=[
                'status', 'review_notes', 'published_at', 'updated_at',
            ])
    except ValidationError as exc:
        messages.error(request, _error_text(exc))
    else:
        messages.success(request, 'La revisión del video quedó registrada.')

    return redirect('professionals:portfolio_review_queue')


def _stream_bytes(file_handle, start, end, chunk_size=256 * 1024):
    try:
        file_handle.seek(start)
        remaining = end - start + 1
        while remaining:
            data = file_handle.read(min(chunk_size, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data
    finally:
        file_handle.close()


@require_GET
def portfolio_stream(request, public_id):
    video = get_object_or_404(
        ProfessionalPortfolioVideo.objects.select_related('professional_profile'),
        public_id=public_id,
    )
    profile = video.professional_profile
    is_owner = (
        request.user.is_authenticated and profile.user_id == request.user.pk
    )
    is_staff = request.user.is_authenticated and request.user.is_staff
    is_public = (
        video.status == ProfessionalPortfolioVideo.Status.APPROVED
        and profile.verification_status == ProfessionalProfile.VerificationStatus.VERIFIED
        and profile.is_public
    )
    if not (is_owner or is_staff or is_public):
        raise Http404('Video no disponible.')
    if video.storage_backend != ProfessionalPortfolioVideo.StorageBackend.LOCAL:
        raise Http404('El proveedor externo no está integrado.')
    if not video.video_file:
        raise Http404('Video sin archivo local.')

    filename = video.video_file.name
    storage = video.video_file.storage
    if not storage.exists(filename):
        raise Http404('Archivo no encontrado.')

    extension = os.path.splitext(filename)[1].lower()
    content_type = {'.mp4': 'video/mp4', '.webm': 'video/webm'}.get(extension)
    if not content_type:
        raise Http404('Formato no admitido.')

    total = storage.size(filename)
    if total <= 0:
        raise Http404('Video vacío.')

    range_value = request.headers.get('Range', '')
    if range_value:
        if len(range_value) > 80:
            response = HttpResponse(status=416)
            response['Content-Range'] = f'bytes */{total}'
            return response
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_value.strip())
        if not match or not (match.group(1) or match.group(2)):
            response = HttpResponse(status=416)
            response['Content-Range'] = f'bytes */{total}'
            return response

        start_text, end_text = match.groups()
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else total - 1
            end = min(end, total - 1)
        else:
            suffix_length = int(end_text)
            start = max(0, total - suffix_length)
            end = total - 1

        if start >= total or start > end or (not start_text and int(end_text) == 0):
            response = HttpResponse(status=416)
            response['Content-Range'] = f'bytes */{total}'
            return response

        response = StreamingHttpResponse(
            _stream_bytes(storage.open(filename, 'rb'), start, end),
            status=206,
            content_type=content_type,
        )
        response['Content-Range'] = f'bytes {start}-{end}/{total}'
        response['Content-Length'] = str(end - start + 1)
    else:
        response = FileResponse(storage.open(filename, 'rb'), content_type=content_type)
        response['Content-Length'] = str(total)

    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Disposition'] = 'inline'
    return response
