"""
V132.06.4A: cuotas del portafolio audiovisual profesional.

Destino:
apps/professionals/professional_video_quota_v13200.py

Mantiene los beneficios comerciales de Profesional Básico y Profesional Pro.

Cuando se utiliza almacenamiento local:
- Profesional Básico: máximo 100 MB por archivo.
- Profesional Pro: máximo 200 MB por archivo.

Cuando se utiliza Supabase:
- Se aplica el menor valor entre el límite del plan profesional
  y el límite técnico configurado para Supabase.
- El límite técnico se define mediante:
  SUPABASE_VIDEO_S3_MAX_FILE_MB

Solo corresponde a videos demostrativos publicables.
No se permiten registros clínicos ni material privado de pacientes.

La duración y el tamaño deben verificarse desde el servidor.
"""

import os
from dataclasses import dataclass, replace

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone

from apps.subscriptions.models import SubscriptionPlan, UserSubscription
from apps.subscriptions.services import get_effective_subscription


MEGABYTE = 1024 * 1024


@dataclass(frozen=True)
class ProfessionalVideoQuota:
    code: str
    label: str
    max_videos: int
    max_seconds_per_video: int
    max_total_seconds: int
    max_file_bytes: int


NO_ACCESS = ProfessionalVideoQuota(
    'unverified',
    'No habilitado',
    0,
    0,
    0,
    0,
)

BASIC_QUOTA = ProfessionalVideoQuota(
    'professional_base',
    'Profesional Básico',
    3,
    120,
    360,
    100 * MEGABYTE,
)

PRO_QUOTA = ProfessionalVideoQuota(
    'professional_pro',
    'Profesional Pro',
    20,
    300,
    6000,
    200 * MEGABYTE,
)


PRO_VIDEO_PLAN_CODES = frozenset({
    SubscriptionPlan.Code.PROFESSIONAL_PRO,
    SubscriptionPlan.Code.PRO_INTEGRAL,
})

PRO_VIDEO_SUBSCRIPTION_STATUSES = frozenset({
    UserSubscription.Status.TRIAL,
    UserSubscription.Status.ACTIVE,
    UserSubscription.Status.CANCEL_AT_PERIOD_END,
})


def _quota_for_active_storage(quota):
    """
    Aplica el límite técnico del almacenamiento activo.

    En modo local:
        Conserva las cuotas originales de 100 MB y 200 MB.

    En modo Supabase:
        Utiliza el menor valor entre el límite comercial del plan
        y el máximo configurado para Supabase Storage.

    Esta función no modifica las constantes originales.
    """

    configured_mode = getattr(
        settings,
        'PROFESSIONAL_VIDEO_STORAGE_MODE',
        None,
    )

    if configured_mode is None:
        mode = os.getenv(
            'PROFESSIONAL_VIDEO_STORAGE_MODE',
            'local',
        )
    else:
        mode = configured_mode

    mode = str(mode).strip().lower()

    if mode != 'supabase':
        return quota

    if quota.max_file_bytes == 0:
        return quota

    configured_limit = os.getenv(
        'SUPABASE_VIDEO_S3_MAX_FILE_MB',
        '50',
    ).strip()

    try:
        limit_mb = int(configured_limit)
    except ValueError as exc:
        raise ImproperlyConfigured(
            'SUPABASE_VIDEO_S3_MAX_FILE_MB debe ser un entero positivo.'
        ) from exc

    if limit_mb <= 0:
        raise ImproperlyConfigured(
            'SUPABASE_VIDEO_S3_MAX_FILE_MB debe ser un entero positivo.'
        )

    storage_limit_bytes = limit_mb * MEGABYTE

    effective_limit = min(
        quota.max_file_bytes,
        storage_limit_bytes,
    )

    return replace(
        quota,
        max_file_bytes=effective_limit,
    )


def get_professional_video_quota(user, *, at=None):
    """
    Obtiene las cuotas del profesional según su perfil y suscripción.

    Reglas:
    - Un profesional no verificado no puede publicar videos.
    - Profesional Básico conserva 3 videos y 360 segundos totales.
    - Profesional Pro conserva 20 videos y 6000 segundos totales.
    - Miembro Plus y Espacios Pro no habilitan Profesional Pro.
    - Las suscripciones vencidas no mantienen sus beneficios.
    - El límite técnico de Supabase se aplica solamente
      cuando el almacenamiento remoto está activo.
    """

    if not user or not getattr(user, 'is_authenticated', False):
        return NO_ACCESS

    profile = getattr(
        user,
        'professional_profile',
        None,
    )

    if (
        profile is None
        or profile.verification_status != 'verified'
    ):
        return NO_ACCESS

    at = at or timezone.now()

    subscription = get_effective_subscription(
        user,
        at=at,
    )

    if subscription is None:
        return _quota_for_active_storage(BASIC_QUOTA)

    if subscription.plan.code not in PRO_VIDEO_PLAN_CODES:
        return _quota_for_active_storage(BASIC_QUOTA)

    if subscription.status not in PRO_VIDEO_SUBSCRIPTION_STATUSES:
        return _quota_for_active_storage(BASIC_QUOTA)

    period_end = (
        subscription.trial_ends_at
        if subscription.status == UserSubscription.Status.TRIAL
        else subscription.current_period_end
    )

    if period_end is None or period_end <= at:
        return _quota_for_active_storage(BASIC_QUOTA)

    return _quota_for_active_storage(PRO_QUOTA)


def validate_professional_video_upload(
    user,
    *,
    duration_seconds,
    file_size_bytes,
    existing_count,
    existing_total_seconds,
    at=None,
):
    """
    Valida que un video respete las cuotas permitidas.

    Se comprueba:
    - Verificación del profesional.
    - Duración válida.
    - Tamaño válido.
    - Cantidad máxima de videos.
    - Duración individual.
    - Duración acumulada.
    - Límite de archivo según plan y almacenamiento activo.

    El servicio de subida debe repetir esta validación dentro
    de una transacción para evitar conflictos por cargas simultáneas.
    """

    quota = get_professional_video_quota(
        user,
        at=at,
    )

    if quota.max_videos == 0:
        raise ValidationError(
            'Necesitas un perfil profesional verificado.'
        )

    if (
        not isinstance(duration_seconds, int)
        or isinstance(duration_seconds, bool)
        or duration_seconds <= 0
    ):
        raise ValidationError(
            'La duración del video no es válida.'
        )

    if (
        not isinstance(file_size_bytes, int)
        or isinstance(file_size_bytes, bool)
        or file_size_bytes <= 0
    ):
        raise ValidationError(
            'El tamaño del archivo no es válido.'
        )

    if existing_count < 0 or existing_total_seconds < 0:
        raise ValidationError(
            'El uso actual del portafolio no es válido.'
        )

    if existing_count >= quota.max_videos:
        raise ValidationError(
            f'Tu plan permite un máximo de {quota.max_videos} videos.'
        )

    if duration_seconds > quota.max_seconds_per_video:
        raise ValidationError(
            'El video supera la duración individual permitida por tu plan.'
        )

    if (
        existing_total_seconds + duration_seconds
        > quota.max_total_seconds
    ):
        raise ValidationError(
            'Los videos superarían la duración total de tu plan.'
        )

    if file_size_bytes > quota.max_file_bytes:
        raise ValidationError(
            'El archivo supera el tamaño máximo permitido '
            'por tu plan o por el almacenamiento activo.'
        )

    return quota