from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone


PAYMENTS_POLICY_VERSION = 'PAYMENTS_POLICY_V1'

FULL_REFUND_PERCENT = Decimal('100.00')
MID_REFUND_PERCENT = Decimal('75.00')
LATE_REFUND_PERCENT = Decimal('50.00')
NO_REFUND_PERCENT = Decimal('0.00')


@dataclass(frozen=True)
class CancellationDecision:
    policy_version: str
    bucket: str
    hours_before_service: Decimal
    refund_percent: Decimal
    original_amount_clp: int
    refund_amount_clp: int
    retained_amount_clp: int


def _round_clp(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _normalize_datetime(value):
    if not isinstance(value, datetime):
        raise TypeError('Se esperaba una fecha y hora válida.')

    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())

    return value


def calculate_member_cancellation(
    amount_clp,
    service_start,
    cancelled_at=None,
):
    """
    Política comercial V1:

    - 48 horas o más: 100%.
    - Desde 24 hasta menos de 48 horas: 75%.
    - Menos de 24 horas, pero antes del inicio: 50%.
    - Desde el inicio del servicio en adelante: 0%.
    """
    amount_clp = int(amount_clp)
    if amount_clp <= 0:
        raise ValueError('El monto pagado debe ser mayor que cero.')

    service_start = _normalize_datetime(service_start)
    cancelled_at = _normalize_datetime(cancelled_at or timezone.now())

    hours = Decimal(
        str((service_start - cancelled_at).total_seconds() / 3600)
    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    if hours >= Decimal('48'):
        refund_percent = FULL_REFUND_PERCENT
        bucket = 'at_least_48h'
    elif hours >= Decimal('24'):
        refund_percent = MID_REFUND_PERCENT
        bucket = 'between_24h_and_48h'
    elif hours > Decimal('0'):
        refund_percent = LATE_REFUND_PERCENT
        bucket = 'less_than_24h'
    else:
        refund_percent = NO_REFUND_PERCENT
        bucket = 'service_started_or_no_show'

    refund_amount = _round_clp(
        Decimal(amount_clp) * refund_percent / Decimal('100')
    )
    retained_amount = amount_clp - refund_amount

    return CancellationDecision(
        policy_version=PAYMENTS_POLICY_VERSION,
        bucket=bucket,
        hours_before_service=hours,
        refund_percent=refund_percent,
        original_amount_clp=amount_clp,
        refund_amount_clp=refund_amount,
        retained_amount_clp=retained_amount,
    )


def calculate_forced_full_refund(amount_clp):
    """
    Para cancelación del Profesional/Proveedor, servicio no realizado o
    problema atribuible a plataforma. La clasificación del motivo se guarda
    posteriormente en Refund.
    """
    amount_clp = int(amount_clp)
    if amount_clp <= 0:
        raise ValueError('El monto pagado debe ser mayor que cero.')

    return CancellationDecision(
        policy_version=PAYMENTS_POLICY_VERSION,
        bucket='forced_full_refund',
        hours_before_service=Decimal('0.00'),
        refund_percent=FULL_REFUND_PERCENT,
        original_amount_clp=amount_clp,
        refund_amount_clp=amount_clp,
        retained_amount_clp=0,
    )
