from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from apps.subscriptions.services import (
    get_professional_commission_snapshot,
    get_space_commission_snapshot,
)

from ..models import Payment


@dataclass(frozen=True)
class EconomicCalculation:
    gross_amount_clp: int
    refunded_amount_clp: int
    commission_base_clp: int
    commission_rate_percent: Decimal
    commission_amount_clp: int
    net_amount_clp: int


def percentage_amount(amount_clp, rate_percent):
    value = (
        Decimal(int(amount_clp))
        * Decimal(rate_percent)
        / Decimal('100')
    )
    return int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def calculate_economic_amounts(
    amount_clp,
    commission_rate_percent,
    refunded_amount_clp=0,
):
    amount_clp = int(amount_clp)
    refunded_amount_clp = int(refunded_amount_clp)

    if amount_clp < 0:
        raise ValueError('El monto bruto no puede ser negativo.')

    if refunded_amount_clp < 0:
        raise ValueError('El monto reembolsado no puede ser negativo.')

    if refunded_amount_clp > amount_clp:
        raise ValueError('El reembolso no puede superar el monto pagado.')

    rate = Decimal(commission_rate_percent)
    if rate < 0 or rate > 100:
        raise ValueError('La comisión debe estar entre 0% y 100%.')

    commission_base = amount_clp - refunded_amount_clp
    commission_amount = percentage_amount(commission_base, rate)
    net_amount = commission_base - commission_amount

    return EconomicCalculation(
        gross_amount_clp=amount_clp,
        refunded_amount_clp=refunded_amount_clp,
        commission_base_clp=commission_base,
        commission_rate_percent=rate,
        commission_amount_clp=commission_amount,
        net_amount_clp=net_amount,
    )


def get_payment_commission_snapshot(payment, at=None):
    """
    Resuelve el plan y la comisión para una NUEVA operación.

    Actividades profesionales: usa al organizador.
    Arriendos de espacios: usa al propietario/proveedor de la reserva.
    El resultado se guarda como snapshot al aprobar el pago.
    """
    if payment.economic_scope in {
        Payment.EconomicScope.PROFESSIONAL_ACTIVITY,
        Payment.EconomicScope.PROFESSIONAL_SERVICE,
    }:
        if not payment.activity_id or payment.space_booking_id:
            raise ValueError(
                'El pago profesional debe estar asociado solamente a una actividad.'
            )

        beneficiary = payment.activity.organizer
        return get_professional_commission_snapshot(beneficiary, at=at)

    if payment.economic_scope == Payment.EconomicScope.SPACE_BOOKING:
        if not payment.space_booking_id or payment.activity_id:
            raise ValueError(
                'El pago de arriendo debe estar asociado solamente a una reserva de espacio.'
            )

        beneficiary = payment.space_booking.provider_profile.user
        return get_space_commission_snapshot(beneficiary, at=at)

    raise ValueError('Origen económico de pago no reconocido.')


def apply_payment_commission_snapshot(payment, at=None, save=True):
    """
    Congela plan + porcentaje en el pago y recalcula sus montos económicos.

    Debe utilizarse cuando una operación queda aprobada por primera vez.
    No debe volver a ejecutarse para cambiar retroactivamente pagos históricos.
    """
    snapshot = get_payment_commission_snapshot(payment, at=at)

    payment.plan_code_snapshot = snapshot.plan_code
    payment.commission_rate_percent = snapshot.commission_rate_percent

    calculation = calculate_economic_amounts(
        amount_clp=payment.amount_clp,
        refunded_amount_clp=payment.refunded_amount_clp,
        commission_rate_percent=snapshot.commission_rate_percent,
    )

    payment.commission_base_clp = calculation.commission_base_clp
    payment.commission_amount_clp = calculation.commission_amount_clp
    payment.net_amount_clp = calculation.net_amount_clp

    if save:
        payment.save(
            update_fields=[
                'plan_code_snapshot',
                'commission_rate_percent',
                'commission_base_clp',
                'commission_amount_clp',
                'net_amount_clp',
                'updated_at',
            ]
        )

    return calculation


def recalculate_payment_after_refund(payment, save=True):
    """Recalcula montos usando SIEMPRE la comisión histórica ya guardada."""
    calculation = calculate_economic_amounts(
        amount_clp=payment.amount_clp,
        refunded_amount_clp=payment.refunded_amount_clp,
        commission_rate_percent=payment.commission_rate_percent,
    )

    payment.commission_base_clp = calculation.commission_base_clp
    payment.commission_amount_clp = calculation.commission_amount_clp
    payment.net_amount_clp = calculation.net_amount_clp

    if save:
        payment.save(
            update_fields=[
                'commission_base_clp',
                'commission_amount_clp',
                'net_amount_clp',
                'updated_at',
            ]
        )

    return calculation
