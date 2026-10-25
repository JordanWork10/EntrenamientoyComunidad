"""Liquidaciones profesionales y de jornadas de espacios (V131.46).

La rama de espacios es exclusivamente contable y sandbox. No transfiere dinero
ni habilita por sí misma un botón o endpoint de liquidación.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.spaces.models import Space

from ..models import Payment, Refund, Settlement


INCIDENT_WINDOW_HOURS = 24


class SettlementProcessingError(Exception):
    pass


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

    payments.exclude(settlement=settlement).update(
        settlement=settlement,
    )

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


@transaction.atomic
def settle_activity_settlement(
    settlement,
    now=None,
    provider_reference=None,
):
    """
    Cierra una liquidación elegible y marca todos sus pagos económicos
    como liquidados.

    En V107 el movimiento es sandbox. En producción esta función se
    conectará al proveedor de pagos antes de marcar SETTLED.
    """
    now = now or timezone.now()

    locked_settlement = (
        Settlement.objects
        .select_for_update()
        .get(pk=settlement.pk)
    )

    if locked_settlement.scope_type != Settlement.ScopeType.ACTIVITY:
        raise SettlementProcessingError(
            'Esta liquidación no corresponde a una actividad profesional.'
        )

    if locked_settlement.status == Settlement.Status.SETTLED:
        return locked_settlement

    if locked_settlement.status == Settlement.Status.ON_HOLD:
        raise SettlementProcessingError(
            'La liquidación se encuentra en revisión.'
        )

    if locked_settlement.status != Settlement.Status.ELIGIBLE:
        raise SettlementProcessingError(
            'La liquidación todavía no es elegible.'
        )

    if locked_settlement.net_amount_clp <= 0:
        raise SettlementProcessingError(
            'No existe monto neto por liquidar.'
        )

    if (
        locked_settlement.eligible_at
        and now < locked_settlement.eligible_at
    ):
        raise SettlementProcessingError(
            'Todavía no se cumple la fecha de liquidación.'
        )

    payments = (
        Payment.objects
        .select_for_update()
        .filter(
            settlement=locked_settlement,
            status__in=[
                Payment.Status.APPROVED,
                Payment.Status.PARTIALLY_REFUNDED,
                Payment.Status.REFUNDED,
            ],
        )
    )

    if payments.filter(
        settlement_status=Payment.SettlementStatus.ON_HOLD,
    ).exists():
        raise SettlementProcessingError(
            'Existe al menos un pago en revisión.'
        )

    locked_settlement.status = Settlement.Status.SETTLED
    locked_settlement.settled_at = now
    locked_settlement.hold_reason = ''
    locked_settlement.provider_reference = (
        provider_reference
        or f'SET-SBX-{str(locked_settlement.public_id).split("-")[0].upper()}'
    )
    locked_settlement.full_clean()
    locked_settlement.save(
        update_fields=[
            'status',
            'settled_at',
            'hold_reason',
            'provider_reference',
            'updated_at',
        ]
    )

    payments.update(
        settlement_status=Payment.SettlementStatus.SETTLED,
        settled_at=now,
        settlement_hold_reason='',
        updated_at=now,
    )

    return locked_settlement


# ============================================================================
# V131.46 - JORNADAS DE ESPACIOS (SIN TRANSFERENCIAS REALES)
# ============================================================================

_SPACE_FINANCIAL_STATUSES = (
    Payment.Status.APPROVED,
    Payment.Status.PARTIALLY_REFUNDED,
    Payment.Status.REFUNDED,
)

_SPACE_UNRESOLVED_REFUND_STATUSES = (
    Refund.Status.REQUESTED,
    Refund.Status.APPROVED,
    Refund.Status.FAILED,
)


def _space_booking_end(booking):
    """Finalización local del arriendo, incluso si cruza medianoche."""
    end = datetime.combine(booking.session_date, booking.end_time)
    if booking.end_time <= booking.start_time:
        end += timedelta(days=1)
    return timezone.make_aware(end, timezone.get_current_timezone())


def _space_day_payments(space, reference_date, *, lock=False):
    """Pagos económicos del recinto y fecha; excluye intentos pendientes."""
    query = Payment.objects.filter(
        space_booking__space=space,
        space_booking__session_date=reference_date,
        space_booking__isnull=False,
        activity__isnull=True,
        economic_scope=Payment.EconomicScope.SPACE_BOOKING,
        status__in=_SPACE_FINANCIAL_STATUSES,
    ).select_related('space_booking')
    if lock:
        # Solo bloqueamos Payment; el ForeignKey space_booking es nullable.
        # Evita FOR UPDATE sobre el lado nullable de un OUTER JOIN.
        query = query.select_for_update(of=('self',))
    return list(query.order_by('pk'))


def _space_day_review(payments, *, space):
    """Valida negocio y devuelve (fecha_elegible, bloqueos, falta_completar).

    No cambia estados. Los bloqueos manuales no se liberan aquí.
    """
    if not payments:
        raise SettlementProcessingError(
            'La jornada no tiene pagos aprobados o reembolsados.'
        )

    eligible_at = None
    blockers = []
    awaiting_completion = False
    payment_ids = [p.pk for p in payments]
    unresolved = set(
        Refund.objects.filter(
            payment_id__in=payment_ids,
            status__in=_SPACE_UNRESOLVED_REFUND_STATUSES,
        ).values_list('payment_id', flat=True)
    )

    processed_totals = {
        row["payment_id"]: row["total"]
        for row in (Refund.objects.filter(
            payment_id__in=payment_ids, status=Refund.Status.PROCESSED,
        ).values("payment_id").annotate(total=Sum("amount_clp")))
    }

    for payment in payments:
        booking = payment.space_booking
        if booking.space_id != space.pk:
            raise SettlementProcessingError('El pago no pertenece al recinto.')
        if booking.provider_profile_id != space.provider_profile_id:
            blockers.append('El proveedor de una reserva no coincide con el dueño actual del recinto.')
        if payment.payer_id != booking.booked_by_id:
            blockers.append('Existe un pago con titular distinto al miembro que reservó.')
        if (
            payment.commission_base_clp != payment.amount_clp - payment.refunded_amount_clp
            or payment.net_amount_clp + payment.commission_amount_clp != payment.commission_base_clp
        ):
            blockers.append('Existen importes económicos inconsistentes que requieren revisión.')
        if processed_totals.get(payment.pk, 0) != payment.refunded_amount_clp:
            blockers.append('El total de reembolsos procesados no coincide con el pago.')
        if payment.pk in unresolved:
            blockers.append('Existe una solicitud de reembolso sin resolución definitiva.')
        if payment.settlement_status == Payment.SettlementStatus.ON_HOLD:
            blockers.append('Existe un pago retenido para revisión.')
        if payment.settlement_status == Payment.SettlementStatus.SETTLED:
            blockers.append('Un pago de la jornada ya fue liquidado.')
        if payment.settlement_id and (
            payment.settlement.scope_type != Settlement.ScopeType.SPACE_DAY
            or payment.settlement.space_id != space.pk
            or payment.settlement.reference_date != booking.session_date
        ):
            blockers.append('Un pago está asociado a otra liquidación.')

        # Los pagos totalmente devueltos no generan saldo a liquidar.
        if payment.net_amount_clp > 0:
            if booking.status == 'confirmed':
                awaiting_completion = True
            elif booking.status != 'completed':
                blockers.append(
                    'Existe un pago con saldo pendiente para una reserva no realizada.'
                )

        end_eligible = calculate_settlement_eligible_at(_space_booking_end(booking))
        if eligible_at is None or end_eligible > eligible_at:
            eligible_at = end_eligible

    return eligible_at, list(dict.fromkeys(blockers)), awaiting_completion


def _space_day_totals(payments):
    return {
        'gross_amount_clp': sum(p.amount_clp for p in payments),
        'refunded_amount_clp': sum(p.refunded_amount_clp for p in payments),
        'commission_base_clp': sum(p.commission_base_clp for p in payments),
        'commission_amount_clp': sum(p.commission_amount_clp for p in payments),
        'net_amount_clp': sum(p.net_amount_clp for p in payments),
    }


@transaction.atomic
def sync_space_day_settlement(space, reference_date):
    """Crea/actualiza la agrupación contable por recinto y fecha.

    Usa el reloj real. Una jornada no completada se mantiene PENDING;
    cualquier retención u operación de reembolso abierta la bloquea.
    No realiza liquidaciones, anticipos ni transferencias.
    """
    now = timezone.now()
    locked_space = Space.objects.select_for_update().get(pk=space.pk)
    payments = _space_day_payments(locked_space, reference_date, lock=True)
    eligible_at, blockers, awaiting_completion = _space_day_review(
        payments, space=locked_space,
    )
    totals = _space_day_totals(payments)
    beneficiary_id = locked_space.provider_profile.user_id

    settlement, _created = Settlement.objects.select_for_update().get_or_create(
        scope_type=Settlement.ScopeType.SPACE_DAY,
        space=locked_space,
        reference_date=reference_date,
        defaults={
            'beneficiary_id': beneficiary_id,
            'activity': None,
            'status': Settlement.Status.PENDING,
            'eligible_at': eligible_at,
            **totals,
        },
    )

    if settlement.beneficiary_id != beneficiary_id:
        raise SettlementProcessingError(
            'El beneficiario registrado no coincide con el proveedor del recinto.'
        )

    if settlement.status == Settlement.Status.SETTLED:
        # Una liquidación cerrada no debe recalcularse ni incorporar pagos.
        if (
            any(p.settlement_id != settlement.pk for p in payments)
            or any(getattr(settlement, name) != value for name, value in totals.items())
        ):
            raise SettlementProcessingError(
                'Una liquidación cerrada tiene nuevos movimientos o cambios económicos. '
                'Requiere un ajuste con trazabilidad separado.'
            )
        return settlement

    for p in payments:
        if p.settlement_id not in (None, settlement.pk):
            raise SettlementProcessingError(
                'Un pago ya pertenece a otra liquidación.'
            )

    for name, value in totals.items():
        setattr(settlement, name, value)
    settlement.eligible_at = eligible_at

    if settlement.status != Settlement.Status.ON_HOLD:
        if blockers:
            settlement.status = Settlement.Status.ON_HOLD
            settlement.hold_reason = '; '.join(blockers)[:255]
        elif (
            totals['net_amount_clp'] > 0
            and not awaiting_completion
            and now >= eligible_at
        ):
            settlement.status = Settlement.Status.ELIGIBLE
            settlement.hold_reason = ''
        else:
            settlement.status = Settlement.Status.PENDING
            settlement.hold_reason = ''

    settlement.full_clean()
    settlement.save()

    for payment in payments:
        changes = []
        if payment.settlement_id is None:
            payment.settlement = settlement
            changes.append('settlement')
        if payment.settlement_eligible_at != eligible_at:
            payment.settlement_eligible_at = eligible_at
            changes.append('settlement_eligible_at')
        if payment.settlement_status not in {
            Payment.SettlementStatus.ON_HOLD,
            Payment.SettlementStatus.SETTLED,
        }:
            target = (
                Payment.SettlementStatus.ELIGIBLE
                if settlement.status == Settlement.Status.ELIGIBLE
                else Payment.SettlementStatus.PENDING
            )
            if payment.settlement_status != target:
                payment.settlement_status = target
                changes.append('settlement_status')
        if changes:
            payment.save(update_fields=[*changes, 'updated_at'])

    return settlement


@transaction.atomic
def settle_space_day_settlement(
    settlement,
    *,
    reviewed_by,
    provider_reference=None,
):
    """Cierra una jornada SOLO en sandbox y por un operador autorizado.

    NO acepta reloj simulado. La integración con vistas requiere método POST,
    CSRF y autorización del operador además de estas validaciones de servicio.
    No hace ninguna transferencia de dinero.
    """
    if not getattr(settings, 'PAYMENTS_SANDBOX', False):
        raise SettlementProcessingError(
            'La liquidación de espacios todavía no está habilitada fuera de sandbox.'
        )
    if (
        not reviewed_by
        or not reviewed_by.is_authenticated
        or not reviewed_by.is_active
        or not reviewed_by.is_staff
        or not reviewed_by.has_perm('payments.change_settlement')
    ):
        raise SettlementProcessingError(
            'La liquidación requiere revisión explícita de un administrador autorizado.'
        )

    now = timezone.now()
    current = Settlement.objects.select_for_update().get(pk=settlement.pk)
    if current.scope_type != Settlement.ScopeType.SPACE_DAY or not current.space_id:
        raise SettlementProcessingError('La liquidación no corresponde a una jornada de espacio.')
    if current.status == Settlement.Status.SETTLED:
        return current
    if current.status == Settlement.Status.ON_HOLD:
        raise SettlementProcessingError('La jornada está retenida para revisión.')
    if current.status != Settlement.Status.ELIGIBLE:
        raise SettlementProcessingError('La jornada todavía no es elegible.')
    if not current.reference_date or not current.eligible_at or now < current.eligible_at:
        raise SettlementProcessingError('No se han cumplido las 24 horas posteriores al servicio.')
    if current.net_amount_clp <= 0:
        raise SettlementProcessingError('No existe saldo neto positivo por liquidar.')

    space = Space.objects.select_related('provider_profile').get(pk=current.space_id)
    if current.beneficiary_id != space.provider_profile.user_id:
        raise SettlementProcessingError('El beneficiario no corresponde al proveedor del recinto.')

    payments = _space_day_payments(space, current.reference_date, lock=True)
    expected_at, blockers, awaiting_completion = _space_day_review(
        payments, space=space,
    )
    if awaiting_completion:
        raise SettlementProcessingError(
            'Una o más reservas todavía no están marcadas como completadas.'
        )
    if blockers:
        raise SettlementProcessingError('; '.join(blockers))
    if expected_at != current.eligible_at or now < expected_at:
        raise SettlementProcessingError('El período de elegibilidad cambió o todavía no se cumple.')
    if any(p.settlement_id != current.pk for p in payments):
        raise SettlementProcessingError('Existen pagos de la jornada sin agrupar correctamente.')
    if any(getattr(current, key) != val for key, val in _space_day_totals(payments).items()):
        raise SettlementProcessingError('Los importes de la jornada cambiaron. Revisa el resumen.')

    current.status = Settlement.Status.SETTLED
    current.settled_at = now
    current.hold_reason = ''
    current.provider_reference = (
        provider_reference
        or f'SET-SPC-SBX-{str(current.public_id).split("-")[0].upper()}'
    )
    current.full_clean()
    current.save(
        update_fields=[
            'status', 'settled_at', 'hold_reason', 'provider_reference', 'updated_at',
        ]
    )
    Payment.objects.filter(pk__in=[p.pk for p in payments]).update(
        settlement_status=Payment.SettlementStatus.SETTLED,
        settled_at=now,
        settlement_hold_reason='',
        updated_at=now,
    )
    return current
