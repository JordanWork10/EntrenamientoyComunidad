"""V132.00 (etapa 1): cuotas de portafolio audiovisual profesional.

Destino: apps/professionals/professional_video_quota_v13200.py

Integra los planes existentes en apps.subscriptions; no crea ni cobra planes.
Solo corresponde a VIDEOS DEMOSTRATIVOS publicables, nunca a registros
clínicos o material privado de pacientes.

IMPORTANTE: duración y tamaño deben provenir de un analizador de medios
confiable del servidor/proveedor, nunca de un campo enviado por el navegador.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
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


NO_ACCESS = ProfessionalVideoQuota('unverified', 'No habilitado', 0, 0, 0, 0)
BASIC_QUOTA = ProfessionalVideoQuota(
    'professional_base', 'Profesional Básico', 3, 120, 360, 100 * MEGABYTE,
)
PRO_QUOTA = ProfessionalVideoQuota(
    'professional_pro', 'Profesional Pro', 20, 300, 6000, 200 * MEGABYTE,
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


def get_professional_video_quota(user, *, at=None):
    """Obtiene la cuota a partir del perfil y la suscripción real.

    Miembro Plus y Espacios Pro NO incluyen video Profesional Pro.
    PAST_DUE NO otorga ampliación de videos. Se respeta la fecha de fin
    incluso si aún no se ejecutó el proceso de cierre de suscripciones.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return NO_ACCESS

    profile = getattr(user, 'professional_profile', None)
    if profile is None or profile.verification_status != 'verified':
        return NO_ACCESS

    at = at or timezone.now()
    subscription = get_effective_subscription(user, at=at)
    if subscription is None:
        return BASIC_QUOTA

    if subscription.plan.code not in PRO_VIDEO_PLAN_CODES:
        return BASIC_QUOTA
    if subscription.status not in PRO_VIDEO_SUBSCRIPTION_STATUSES:
        return BASIC_QUOTA

    period_end = (
        subscription.trial_ends_at
        if subscription.status == UserSubscription.Status.TRIAL
        else subscription.current_period_end
    )
    if period_end is None or period_end <= at:
        return BASIC_QUOTA

    return PRO_QUOTA


def validate_professional_video_upload(
    user,
    *,
    duration_seconds,
    file_size_bytes,
    existing_count,
    existing_total_seconds,
    at=None,
):
    """Valida la capacidad ANTES de hacer público el video.

    El backend debe repetirla bajo un bloqueo transaccional del propietario
    al confirmar un archivo procesado, evitando cargas simultáneas que
    excedan la cuota. Para ediciones debe excluir el video sustituido.
    """
    quota = get_professional_video_quota(user, at=at)

    if quota.max_videos == 0:
        raise ValidationError('Necesitas un perfil profesional verificado.')

    if (
        not isinstance(duration_seconds, int)
        or isinstance(duration_seconds, bool)
        or duration_seconds <= 0
    ):
        raise ValidationError('La duración del video no es válida.')

    if (
        not isinstance(file_size_bytes, int)
        or isinstance(file_size_bytes, bool)
        or file_size_bytes <= 0
    ):
        raise ValidationError('El tamaño del archivo no es válido.')

    if existing_count < 0 or existing_total_seconds < 0:
        raise ValidationError('El uso actual del portafolio no es válido.')

    if existing_count >= quota.max_videos:
        raise ValidationError(
            f'Tu plan permite un máximo de {quota.max_videos} videos.'
        )
    if duration_seconds > quota.max_seconds_per_video:
        raise ValidationError(
            'El video supera la duración individual permitida por tu plan.'
        )
    if existing_total_seconds + duration_seconds > quota.max_total_seconds:
        raise ValidationError(
            'Los videos superarían la duración total de tu plan.'
        )
    if file_size_bytes > quota.max_file_bytes:
        raise ValidationError(
            'El archivo supera el tamaño máximo permitido por tu plan.'
        )

    return quota
