from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import Payment, Settlement


INCIDENT_WINDOW_HOURS = 24


def calculate_settlement_eligible_at(service_end):
    if timezone.is_naive(service_end):
        service_end = timezone.make_aware(
            service_end,
            timezone.get_current_timezone(),
        )

    return service_end + timedelta(hours=INCIDENT_WINDOW_HOURS)


def refresh_payment_settlement_status(
    payment,
    service_end,
    now=None,
    save=True,
):
    """
    Actualiza únicamente el calendario económico del pago.

    ON_HOLD y SETTLED se respetan y no se pisan automáticamente.
    """
    now = now or timezone.now()
    eligible_at = calculate_settlement_eligible_at(service_end)

    payment.settlement_eligible_at = eligible_at

    if payment.settlement_status not in {
        Payment.SettlementStatus.ON_HOLD,
        Payment.SettlementStatus.SETTLED,
    }:
        if now >= eligible_at:
            payment.settlement_status = Payment.SettlementStatus.ELIGIBLE
        else:
            payment.settlement_status = Payment.SettlementStatus.PENDING

    if save:
        payment.save(
            update_fields=[
                'settlement_eligible_at',
                'settlement_status',
                'updated_at',
            ]
        )

    return payment.settlement_status


def put_payment_on_hold(payment, reason, save=True):
    payment.settlement_status = Payment.SettlementStatus.ON_HOLD
    payment.settlement_hold_reason = reason

    if save:
        payment.save(
            update_fields=[
                'settlement_status',
                'settlement_hold_reason',
                'updated_at',
            ]
        )


def release_payment_hold(payment, service_end, now=None, save=True):
    payment.settlement_hold_reason = ''
    payment.settlement_status = Payment.SettlementStatus.PENDING

    status = refresh_payment_settlement_status(
        payment,
        service_end=service_end,
        now=now,
        save=False,
    )

    if save:
        payment.save(
            update_fields=[
                'settlement_status',
                'settlement_hold_reason',
                'settlement_eligible_at',
                'updated_at',
            ]
        )

    return status


@transaction.atomic
def sync_activity_settlement(activity, service_end, now=None):
    """
    Agrupa los pagos económicos de una actividad en UNA liquidación.

    La vista futura de Pagos utilizará esta entidad para mostrar una tarjeta por
    actividad en lugar de una fila por participante.
    """
    now = now or timezone.now()
    eligible_at = calculate_settlement_eligible_at(service_end)

    payments = (
        Payment.objects
        .select_for_update()
        .filter(
            activity=activity,
            status__in=[
                Payment.Status.APPROVED,
                Payment.Status.PARTIALLY_REFUNDED,
                Payment.Status.REFUNDED,
            ],
        )
    )

    totals = payments.aggregate(
        gross=Sum('amount_clp'),
        refunded=Sum('refunded_amount_clp'),
        commission_base=Sum('commission_base_clp'),
        commission=Sum('commission_amount_clp'),
        net=Sum('net_amount_clp'),
    )

    defaults = {
        'beneficiary': activity.organizer,
        'gross_amount_clp': totals['gross'] or 0,
        'refunded_amount_clp': totals['refunded'] or 0,
        'commission_base_clp': totals['commission_base'] or 0,
        'commission_amount_clp': totals['commission'] or 0,
        'net_amount_clp': totals['net'] or 0,
        'eligible_at': eligible_at,
    }

    settlement, _ = Settlement.objects.select_for_update().get_or_create(
        scope_type=Settlement.ScopeType.ACTIVITY,
        activity=activity,
        defaults={
            **defaults,
            'status': (
                Settlement.Status.ELIGIBLE
                if now >= eligible_at
                else Settlement.Status.PENDING
            ),
        },
    )

    for field, value in defaults.items():
        setattr(settlement, field, value)

    if settlement.status not in {
        Settlement.Status.ON_HOLD,
        Settlement.Status.SETTLED,
    }:
        settlement.status = (
            Settlement.Status.ELIGIBLE
            if now >= eligible_at
            else Settlement.Status.PENDING
        )

    settlement.full_clean()
    settlement.save()

    payments.exclude(settlement=settlement).update(settlement=settlement)

    for payment in payments:
        if payment.settlement_status not in {
            Payment.SettlementStatus.ON_HOLD,
            Payment.SettlementStatus.SETTLED,
        }:
            payment.settlement_eligible_at = eligible_at
            payment.settlement_status = (
                Payment.SettlementStatus.ELIGIBLE
                if now >= eligible_at
                else Payment.SettlementStatus.PENDING
            )
            payment.save(
                update_fields=[
                    'settlement_eligible_at',
                    'settlement_status',
                    'updated_at',
                ]
            )

    return settlement
