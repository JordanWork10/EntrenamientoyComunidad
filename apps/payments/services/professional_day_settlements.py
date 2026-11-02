"""V131.78: jornadas económicas de sesiones individuales (solo sandbox).

La preparación y el cierre son transacciones distintas. El cierre usa el reloj
real, requiere autorización del administrador y nunca transfiere dinero.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.bookings.models import (
    Booking,
    BookingSessionIncident,
    BookingSessionReview,
)
from apps.professionals.models import ProfessionalProfile

from .settlements import (
    SettlementProcessingError,
    calculate_settlement_eligible_at,
)
from ..models import Payment, Refund, Settlement


FINANCIAL_STATUSES = (
    Payment.Status.APPROVED,
    Payment.Status.PARTIALLY_REFUNDED,
    Payment.Status.REFUNDED,
)
UNRESOLVED_REFUNDS = (
    Refund.Status.REQUESTED,
    Refund.Status.APPROVED,
    Refund.Status.FAILED,
)


def _require_authorized_operator(user):
    if not getattr(settings, 'PAYMENTS_SANDBOX', False):
        raise SettlementProcessingError(
            'Las liquidaciones de sesiones no están habilitadas fuera de sandbox.'
        )
    if not (
        user
        and user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perm('payments.change_settlement')
    ):
        raise SettlementProcessingError(
            'Solo un administrador autorizado puede liquidar esta jornada.'
        )


def _booking_end(booking):
    value = datetime.combine(booking.session_date, booking.end_time)
    if booking.end_time <= booking.start_time:
        value += timedelta(days=1)
    return timezone.make_aware(value, timezone.get_current_timezone())


def _lock_profile(professional_user_id):
    try:
        return ProfessionalProfile.objects.select_for_update().get(
            user_id=professional_user_id,
        )
    except ProfessionalProfile.DoesNotExist as exc:
        raise SettlementProcessingError(
            'El beneficiario no posee un perfil profesional válido.'
        ) from exc


def _day_payments(profile, reference_date, *, lock=False):
    query = Payment.objects.filter(
        economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
        professional_booking__professional_profile=profile,
        professional_booking__session_date=reference_date,
        activity__isnull=True,
        space_booking__isnull=True,
        status__in=FINANCIAL_STATUSES,
    ).select_related('professional_booking', 'settlement')
    if lock:
        # Evita bloquear relaciones externas opcionales (OUTER JOIN).
        query = query.select_for_update(of=('self',))
    return list(query.order_by('pk'))


def _day_totals(payments):
    return {
        'gross_amount_clp': sum(p.amount_clp for p in payments),
        'refunded_amount_clp': sum(p.refunded_amount_clp for p in payments),
        'commission_base_clp': sum(p.commission_base_clp for p in payments),
        'commission_amount_clp': sum(p.commission_amount_clp for p in payments),
        'net_amount_clp': sum(p.net_amount_clp for p in payments),
    }


def _day_review(payments, *, profile, reference_date):
    """Devuelve (fecha_elegible, bloqueos, espera_completar); no escribe."""
    if not payments:
        raise SettlementProcessingError(
            'Esta jornada no tiene pagos aprobados o reembolsados.'
        )

    payment_ids = [payment.pk for payment in payments]
    booking_ids = [payment.professional_booking_id for payment in payments]
    processed = {
        row['payment_id']: row['total']
        for row in Refund.objects.filter(
            payment_id__in=payment_ids, status=Refund.Status.PROCESSED,
        ).values('payment_id').annotate(total=Sum('amount_clp'))
    }
    unresolved = set(Refund.objects.filter(
        payment_id__in=payment_ids, status__in=UNRESOLVED_REFUNDS,
    ).values_list('payment_id', flat=True))
    member_refunded = set(Refund.objects.filter(
        payment_id__in=payment_ids,
        status=Refund.Status.PROCESSED,
        reason=Refund.Reason.MEMBER_CANCELLATION,
    ).values_list('payment_id', flat=True))
    reviews = {
        row.booking_id: row
        for row in BookingSessionReview.objects.filter(
            booking_id__in=booking_ids,
        )
    }
    open_incidents = set(BookingSessionIncident.objects.filter(
        review__booking_id__in=booking_ids,
        status__in=(
            BookingSessionIncident.Status.OPEN,
            BookingSessionIncident.Status.IN_REVIEW,
        ),
    ).values_list('review__booking_id', flat=True))
    resolved_service_confirmed = set(BookingSessionIncident.objects.filter(
        review__booking_id__in=booking_ids,
        status=BookingSessionIncident.Status.RESOLVED,
        resolution_type=BookingSessionIncident.Resolution.SERVICE_CONFIRMED,
    ).values_list('review__booking_id', flat=True))

    eligible_at = None
    blockers = []
    awaiting_completion = False

    for payment in payments:
        booking = payment.professional_booking
        if (
            booking.professional_profile_id != profile.pk
            or booking.session_date != reference_date
        ):
            blockers.append('Un pago pertenece a otra jornada profesional.')
        if payment.payer_id != booking.booked_by_id:
            blockers.append('Un pago tiene un titular diferente al Miembro de la reserva.')
        if payment.amount_clp != booking.price_clp:
            blockers.append('El precio de un pago difiere del precio histórico de la reserva.')
        if (
            payment.commission_base_clp
            != payment.amount_clp - payment.refunded_amount_clp
            or payment.net_amount_clp + payment.commission_amount_clp
            != payment.commission_base_clp
        ):
            blockers.append('Existen importes económicos inconsistentes.')
        if processed.get(payment.pk, 0) != payment.refunded_amount_clp:
            blockers.append('Los reembolsos procesados no coinciden con el pago.')
        if payment.pk in unresolved:
            blockers.append('Existe un reembolso pendiente de resolución.')
        if payment.settlement_status == Payment.SettlementStatus.ON_HOLD:
            blockers.append('Existe un pago retenido para revisión.')
        if payment.settlement_status == Payment.SettlementStatus.SETTLED:
            blockers.append('Un pago de la jornada ya fue liquidado.')
        if payment.settlement_id and (
            payment.settlement.scope_type != Settlement.ScopeType.PROFESSIONAL_DAY
            or payment.settlement.beneficiary_id != profile.user_id
            or payment.settlement.reference_date != reference_date
        ):
            blockers.append('Un pago ya pertenece a otra liquidación.')
        if booking.pk in open_incidents:
            blockers.append('La jornada registra una incidencia sin resolver.')

        if payment.net_amount_clp > 0:
            if booking.status == Booking.Status.CONFIRMED:
                awaiting_completion = True
            elif booking.status == Booking.Status.CANCELLED:
                if (
                    payment.status != Payment.Status.PARTIALLY_REFUNDED
                    or payment.pk not in member_refunded
                ):
                    blockers.append(
                        'Una reserva cancelada retiene dinero sin reembolso válido del Miembro.'
                    )
            elif booking.status != Booking.Status.COMPLETED:
                blockers.append('Existe saldo para una sesión no completada ni cancelada válidamente.')

        candidate = calculate_settlement_eligible_at(_booking_end(booking))
        review = reviews.get(booking.pk)
        if (
            review
            and review.status == BookingSessionReview.Status.REPORTED
            and booking.pk not in resolved_service_confirmed
        ):
            blockers.append(
                'Hay una conformidad con problema reportado sin resolución favorable.'
            )
        if (
            review
            and review.status == BookingSessionReview.Status.PENDING
            and review.expires_at > candidate
        ):
            candidate = review.expires_at
        if eligible_at is None or candidate > eligible_at:
            eligible_at = candidate

    return eligible_at, list(dict.fromkeys(blockers)), awaiting_completion


@transaction.atomic
def sync_professional_day_settlement(professional_user, reference_date):
    """Prepara la jornada usando siempre la hora real; no liquida fondos."""
    if not getattr(settings, 'PAYMENTS_SANDBOX', False):
        raise SettlementProcessingError(
            'La preparación de jornadas profesionales solo está disponible en sandbox.'
        )
    now = timezone.now()
    profile = _lock_profile(professional_user.pk)
    payments = _day_payments(profile, reference_date, lock=True)
    eligible_at, blockers, awaiting_completion = _day_review(
        payments, profile=profile, reference_date=reference_date,
    )
    totals = _day_totals(payments)

    settlement, _created = Settlement.objects.select_for_update().get_or_create(
        scope_type=Settlement.ScopeType.PROFESSIONAL_DAY,
        beneficiary=profile.user,
        reference_date=reference_date,
        defaults={
            'activity': None,
            'space': None,
            'eligible_at': eligible_at,
            'status': Settlement.Status.PENDING,
            **totals,
        },
    )
    if settlement.status == Settlement.Status.SETTLED:
        if (
            any(payment.settlement_id != settlement.pk for payment in payments)
            or any(getattr(settlement, name) != value for name, value in totals.items())
        ):
            raise SettlementProcessingError(
                'La jornada ya liquidada presenta movimientos nuevos o modificados.'
            )
        return settlement

    for payment in payments:
        if payment.settlement_id not in (None, settlement.pk):
            raise SettlementProcessingError(
                'No se puede mover un pago asociado a otra liquidación.'
            )

    for field, value in totals.items():
        setattr(settlement, field, value)
    settlement.eligible_at = eligible_at
    if settlement.status != Settlement.Status.ON_HOLD:
        if blockers:
            settlement.status = Settlement.Status.ON_HOLD
            settlement.hold_reason = '; '.join(blockers)[:255]
        elif totals['net_amount_clp'] > 0 and not awaiting_completion and now >= eligible_at:
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
        if payment.settlement_status not in (
            Payment.SettlementStatus.ON_HOLD,
            Payment.SettlementStatus.SETTLED,
        ):
            status = (
                Payment.SettlementStatus.ELIGIBLE
                if settlement.status == Settlement.Status.ELIGIBLE
                else Payment.SettlementStatus.PENDING
            )
            if payment.settlement_status != status:
                payment.settlement_status = status
                changes.append('settlement_status')
        if changes:
            payment.save(update_fields=[*changes, 'updated_at'])

    return settlement


@transaction.atomic
def settle_professional_day_settlement(settlement, *, reviewed_by):
    """Cierra una jornada elegible con validación económica y operador real."""
    _require_authorized_operator(reviewed_by)
    now = timezone.now()

    identity = Settlement.objects.filter(pk=settlement.pk).values(
        'scope_type', 'beneficiary_id', 'reference_date',
    ).first()
    if not identity or identity['scope_type'] != Settlement.ScopeType.PROFESSIONAL_DAY:
        raise SettlementProcessingError('La liquidación no corresponde a sesiones profesionales.')
    if identity['reference_date'] is None:
        raise SettlementProcessingError('La jornada no tiene una fecha válida.')

    profile = _lock_profile(identity['beneficiary_id'])
    payments = _day_payments(profile, identity['reference_date'], lock=True)
    current = Settlement.objects.select_for_update().get(pk=settlement.pk)
    if current.status == Settlement.Status.SETTLED:
        return current
    if current.status == Settlement.Status.ON_HOLD:
        raise SettlementProcessingError('Esta jornada está retenida para revisión.')
    if current.status != Settlement.Status.ELIGIBLE:
        raise SettlementProcessingError('La jornada todavía no es elegible.')
    if current.net_amount_clp <= 0:
        raise SettlementProcessingError('No hay saldo neto positivo para liquidar.')

    expected_at, blockers, awaiting_completion = _day_review(
        payments, profile=profile, reference_date=current.reference_date,
    )
    if blockers:
        raise SettlementProcessingError('; '.join(blockers))
    if awaiting_completion:
        raise SettlementProcessingError('Una sesión pagada aún no figura como completada.')
    if (
        current.eligible_at != expected_at
        or not expected_at
        or now < expected_at
    ):
        raise SettlementProcessingError(
            'No se ha cumplido el plazo real de elegibilidad de la jornada.'
        )
    if any(payment.settlement_id != current.pk for payment in payments):
        raise SettlementProcessingError('Existen pagos sin agrupar en esta jornada.')
    if any(
        payment.settlement_status != Payment.SettlementStatus.ELIGIBLE
        for payment in payments
    ):
        raise SettlementProcessingError(
            'No todos los pagos de la jornada tienen estado económico elegible.'
        )
    if any(
        getattr(current, key) != value
        for key, value in _day_totals(payments).items()
    ):
        raise SettlementProcessingError('Los importes cambiaron. Prepara la jornada otra vez.')

    current.status = Settlement.Status.SETTLED
    current.settled_at = now
    current.settled_by = reviewed_by
    current.hold_reason = ''
    current.provider_reference = (
        f'SET-PRF-SBX-{str(current.public_id).split("-")[0].upper()}'
    )
    current.full_clean()
    current.save(update_fields=[
        'status', 'settled_at', 'settled_by', 'hold_reason',
        'provider_reference', 'updated_at',
    ])
    Payment.objects.filter(pk__in=[payment.pk for payment in payments]).update(
        settlement_status=Payment.SettlementStatus.SETTLED,
        settled_at=now,
        settlement_hold_reason='',
        updated_at=now,
    )
    return current


@transaction.atomic
def release_professional_day_hold(settlement, *, reviewed_by):
    """Libera una retención solo si ya no queda ningún impedimento vigente."""
    _require_authorized_operator(reviewed_by)
    now = timezone.now()
    identity = Settlement.objects.filter(pk=settlement.pk).values(
        'scope_type', 'beneficiary_id', 'reference_date',
    ).first()
    if not identity or identity['scope_type'] != Settlement.ScopeType.PROFESSIONAL_DAY:
        raise SettlementProcessingError('La liquidación no corresponde a sesiones profesionales.')
    if not identity['reference_date']:
        raise SettlementProcessingError('La jornada no tiene fecha de referencia.')

    profile = _lock_profile(identity['beneficiary_id'])
    payments = _day_payments(profile, identity['reference_date'], lock=True)
    current = Settlement.objects.select_for_update().get(pk=settlement.pk)
    if current.status != Settlement.Status.ON_HOLD:
        raise SettlementProcessingError('La jornada no está retenida.')

    eligible_at, blockers, awaiting_completion = _day_review(
        payments, profile=profile, reference_date=current.reference_date,
    )
    if blockers:
        raise SettlementProcessingError('; '.join(blockers))
    totals = _day_totals(payments)
    if any(
        getattr(current, key) != value for key, value in totals.items()
    ):
        raise SettlementProcessingError(
            'Los montos cambiaron. Debes revisar los movimientos antes de liberar.'
        )
    if any(payment.settlement_id != current.pk for payment in payments):
        raise SettlementProcessingError('Existen pagos sin agrupar en la jornada.')

    current.eligible_at = eligible_at
    current.hold_reason = ''
    current.status = (
        Settlement.Status.ELIGIBLE
        if totals['net_amount_clp'] > 0 and not awaiting_completion and now >= eligible_at
        else Settlement.Status.PENDING
    )
    current.full_clean()
    current.save(update_fields=[
        'status', 'hold_reason', 'eligible_at', 'updated_at',
    ])
    target = (
        Payment.SettlementStatus.ELIGIBLE
        if current.status == Settlement.Status.ELIGIBLE
        else Payment.SettlementStatus.PENDING
    )
    Payment.objects.filter(
        pk__in=[payment.pk for payment in payments],
        settlement_status__in=(
            Payment.SettlementStatus.PENDING,
            Payment.SettlementStatus.ELIGIBLE,
        ),
    ).update(
        settlement_status=target, settlement_eligible_at=eligible_at,
        updated_at=now,
    )
    return current
