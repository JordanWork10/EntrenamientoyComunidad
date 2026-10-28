"""Política comercial de cancelación de espacios, versión 1 (sandbox).

Se aplica únicamente a pagos cuya aceptación quedó guardada en Payment.
No reinterpreta pagos antiguos registrados bajo LEGACY_PRE_POLICY.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone


SPACE_POLICY_VERSION = 'SPACE_CANCELLATION_V1'
SPACE_GRACE_HOURS = Decimal('2')
SPACE_GRACE_MIN_HOURS_BEFORE_START = Decimal('24')


@dataclass(frozen=True)
class SpaceCancellationDecision:
    policy_version: str
    bucket: str
    hours_before_service: Decimal
    refund_percent: Decimal
    original_amount_clp: int
    refund_amount_clp: int
    retained_amount_clp: int


def _aware(value):
    if not isinstance(value, datetime):
        raise TypeError('La fecha debe incluir día y hora.')
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def calculate_space_member_cancellation(
    amount_clp, service_start, *, cancelled_at=None, paid_at=None,
):
    """100 % ≥48 h, 50 % [24,48) h, 0 % <24 h.

    Excepción de buena fe: 100 % durante las dos primeras horas tras
    aprobación del pago, solo si faltan al menos 24 h para el servicio.
    El servicio que ya empezó NO debe cancelarse automáticamente.
    """
    amount_clp = int(amount_clp)
    if amount_clp <= 0:
        raise ValueError('El importe original debe ser positivo.')
    service_start = _aware(service_start)
    cancelled_at = _aware(cancelled_at or timezone.now())
    raw_hours = Decimal(str((service_start - cancelled_at).total_seconds())) / Decimal('3600')
    if raw_hours <= 0:
        raise ValueError('Un arriendo iniciado requiere una incidencia administrativa.')

    if raw_hours >= Decimal('48'):
        bucket, rate = 'at_least_48h', Decimal('100.00')
    elif raw_hours >= Decimal('24'):
        bucket, rate = 'between_24h_and_48h', Decimal('50.00')
    else:
        bucket, rate = 'less_than_24h', Decimal('0.00')

    if paid_at is not None:
        approved_at = _aware(paid_at)
        since_payment = Decimal(str((cancelled_at - approved_at).total_seconds())) / Decimal('3600')
        if (
            Decimal('0') <= since_payment <= SPACE_GRACE_HOURS
            and raw_hours >= SPACE_GRACE_MIN_HOURS_BEFORE_START
        ):
            bucket, rate = 'grace_after_payment', Decimal('100.00')

    refunded = int((Decimal(amount_clp) * rate / Decimal('100')).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP,
    ))
    return SpaceCancellationDecision(
        policy_version=SPACE_POLICY_VERSION,
        bucket=bucket,
        hours_before_service=raw_hours.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        refund_percent=rate,
        original_amount_clp=amount_clp,
        refund_amount_clp=refunded,
        retained_amount_clp=amount_clp - refunded,
    )
