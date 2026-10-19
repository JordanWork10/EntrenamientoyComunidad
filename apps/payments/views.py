from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.activities.models import Activity, ActivityRegistration

from .models import Payment, Settlement
from .services.cancellation_policy import PAYMENTS_POLICY_VERSION
from .services.commissions import apply_payment_commission_snapshot
from .services.settlements import (
    SettlementProcessingError,
    calculate_settlement_eligible_at,
    refresh_payment_settlement_status,
    settle_activity_settlement,
    sync_activity_settlement,
)
from .services.refunds import (
    RefundProcessingError,
    preview_member_activity_cancellation,
    process_member_activity_cancellation,
)


def _paid_activity_queryset():
    return (
        Activity.objects
        .select_related(
            'organizer',
            'category',
            'professional_profile',
            'professional_profile__user',
            'commune',
        )
        .filter(
            activity_type=Activity.ActivityType.PROFESSIONAL,
            status=Activity.Status.PUBLISHED,
            price__gt=0,
        )
    )


def _sandbox_enabled():
    return bool(
        getattr(
            settings,
            'PAYMENTS_SANDBOX',
            False,
        )
    )


def _activity_service_end(activity):
    service_end = datetime.combine(
        activity.date,
        activity.end_time,
    )

    # Si en el futuro permitimos actividades que terminan después de
    # medianoche, el fin pertenece al día siguiente.
    if activity.end_time <= activity.start_time:
        service_end += timedelta(days=1)

    if timezone.is_naive(service_end):
        service_end = timezone.make_aware(
            service_end,
            timezone.get_current_timezone(),
        )

    return service_end


@login_required(login_url='accounts:login')
def checkout(
    request,
    activity_id,
):
    activity = get_object_or_404(
        _paid_activity_queryset(),
        pk=activity_id,
    )

    if activity.organizer_id == request.user.id:
        messages.info(
            request,
            (
                'Tú organizas esta actividad; '
                'no necesitas realizar un pago.'
            ),
        )
        return redirect(
            'activities:detail',
            activity_id=activity.pk,
        )

    if activity.date < timezone.localdate():
        messages.error(
            request,
            'Esta actividad ya ocurrió y no admite pagos.',
        )
        return redirect(
            'activities:detail',
            activity_id=activity.pk,
        )

    active_registration = (
        ActivityRegistration.objects
        .filter(
            activity=activity,
            member=request.user,
            status=ActivityRegistration.Status.REGISTERED,
        )
        .first()
    )

    if active_registration:
        approved_payment = (
            Payment.objects
            .filter(
                payer=request.user,
                activity=activity,
                status=Payment.Status.APPROVED,
            )
            .order_by('-approved_at')
            .first()
        )

        if approved_payment:
            return redirect(
                'payments:receipt',
                payment_id=approved_payment.public_id,
            )

        messages.info(
            request,
            'Ya estás inscrito en esta actividad.',
        )
        return redirect(
            'activities:detail',
            activity_id=activity.pk,
        )

    if activity.is_full:
        messages.error(
            request,
            'La actividad ya no tiene cupos disponibles.',
        )
        return redirect(
            'activities:detail',
            activity_id=activity.pk,
        )

    with transaction.atomic():
        (
            Payment.objects
            .filter(
                payer=request.user,
                activity=activity,
                status=Payment.Status.PENDING,
            )
            .exclude(
                amount_clp=activity.price,
            )
            .update(
                status=Payment.Status.CANCELLED,
                failure_reason=(
                    'El precio cambió antes de completar el pago.'
                ),
            )
        )

        payment = (
            Payment.objects
            .filter(
                payer=request.user,
                activity=activity,
                status=Payment.Status.PENDING,
                amount_clp=activity.price,
            )
            .order_by('-created_at')
            .first()
        )

        if payment is None:
            payment = Payment(
                payer=request.user,
                activity=activity,
                amount_clp=activity.price,
                currency='CLP',
                provider=Payment.Provider.SANDBOX,
                status=Payment.Status.PENDING,
            )
            payment.full_clean()
            payment.save()

    return render(
        request,
        'payments/checkout.html',
        {
            'activity': activity,
            'payment': payment,
            'sandbox_enabled': _sandbox_enabled(),
        },
    )


@login_required(login_url='accounts:login')
def receipt(
    request,
    payment_id,
):
    payment = get_object_or_404(
        Payment.objects
        .select_related(
            'activity',
            'activity__organizer',
            'registration',
        )
        .prefetch_related(
            'refunds',
        ),
        public_id=payment_id,
        payer=request.user,
    )

    latest_refund = (
        payment.refunds
        .filter(status='processed')
        .order_by('-processed_at', '-requested_at')
        .first()
    )

    return render(
        request,
        'payments/receipt.html',
        {
            'payment': payment,
            'activity': payment.activity,
            'sandbox_enabled': _sandbox_enabled(),
            'latest_refund': latest_refund,
            'retained_amount_clp': max(
                payment.amount_clp - payment.refunded_amount_clp,
                0,
            ),
        },
    )


@login_required(login_url='accounts:login')
def sandbox_approve(
    request,
    payment_id,
):
    if request.method != 'POST':
        return redirect(
            'payments:receipt',
            payment_id=payment_id,
        )

    if not _sandbox_enabled():
        raise Http404(
            'La simulación de pagos no está habilitada.'
        )

    with transaction.atomic():
        payment = get_object_or_404(
            Payment.objects
            .select_for_update(),
            public_id=payment_id,
            payer=request.user,
        )

        if payment.status == Payment.Status.APPROVED:
            messages.info(
                request,
                'Este pago ya se encuentra aprobado.',
            )
            return redirect(
                'payments:receipt',
                payment_id=payment.public_id,
            )

        if payment.status != Payment.Status.PENDING:
            messages.error(
                request,
                (
                    'Este intento de pago ya no está pendiente. '
                    'Inicia un nuevo pago desde la actividad.'
                ),
            )
            return redirect(
                'payments:receipt',
                payment_id=payment.public_id,
            )

        if request.POST.get('accept_policy') != '1':
            messages.error(
                request,
                (
                    'Debes aceptar la política de cancelación y '
                    'reembolsos antes de confirmar el pago.'
                ),
            )
            return redirect(
                'payments:checkout',
                activity_id=payment.activity_id,
            )

        activity = get_object_or_404(
            Activity.objects.select_for_update(),
            pk=payment.activity_id,
        )

        if (
            activity.status != Activity.Status.PUBLISHED
            or activity.activity_type
            != Activity.ActivityType.PROFESSIONAL
            or activity.price <= 0
        ):
            payment.status = Payment.Status.CANCELLED
            payment.failure_reason = (
                'La actividad ya no está disponible para pago.'
            )
            payment.save(
                update_fields=[
                    'status',
                    'failure_reason',
                    'updated_at',
                ]
            )

            messages.error(
                request,
                payment.failure_reason,
            )
            return redirect(
                'payments:receipt',
                payment_id=payment.public_id,
            )

        if activity.organizer_id == request.user.id:
            payment.status = Payment.Status.CANCELLED
            payment.failure_reason = (
                'El organizador no paga por su propia actividad.'
            )
            payment.save(
                update_fields=[
                    'status',
                    'failure_reason',
                    'updated_at',
                ]
            )

            messages.error(
                request,
                payment.failure_reason,
            )
            return redirect(
                'payments:receipt',
                payment_id=payment.public_id,
            )

        if activity.date < timezone.localdate():
            payment.status = Payment.Status.CANCELLED
            payment.failure_reason = (
                'La actividad ya ocurrió.'
            )
            payment.save(
                update_fields=[
                    'status',
                    'failure_reason',
                    'updated_at',
                ]
            )

            messages.error(
                request,
                payment.failure_reason,
            )
            return redirect(
                'payments:receipt',
                payment_id=payment.public_id,
            )

        if payment.amount_clp != activity.price:
            payment.status = Payment.Status.CANCELLED
            payment.failure_reason = (
                'El precio de la actividad cambió. '
                'Inicia un nuevo pago con el valor actualizado.'
            )
            payment.save(
                update_fields=[
                    'status',
                    'failure_reason',
                    'updated_at',
                ]
            )

            messages.error(
                request,
                payment.failure_reason,
            )
            return redirect(
                'activities:detail',
                activity_id=activity.pk,
            )

        registration = (
            ActivityRegistration.objects
            .select_for_update()
            .filter(
                activity=activity,
                member=request.user,
            )
            .first()
        )

        already_registered = (
            registration is not None
            and registration.status
            == ActivityRegistration.Status.REGISTERED
        )

        if not already_registered:
            active_count = (
                ActivityRegistration.objects
                .filter(
                    activity=activity,
                    status=ActivityRegistration.Status.REGISTERED,
                )
                .count()
            )

            if active_count >= activity.capacity:
                payment.status = Payment.Status.FAILED
                payment.failure_reason = (
                    'No quedan cupos disponibles para completar '
                    'esta inscripción.'
                )
                payment.save(
                    update_fields=[
                        'status',
                        'failure_reason',
                        'updated_at',
                    ]
                )

                messages.error(
                    request,
                    payment.failure_reason,
                )
                return redirect(
                    'payments:receipt',
                    payment_id=payment.public_id,
                )

            if registration is None:
                registration = ActivityRegistration(
                    activity=activity,
                    member=request.user,
                    status=ActivityRegistration.Status.REGISTERED,
                )
                registration.full_clean()
                registration.save()

            else:
                registration.status = (
                    ActivityRegistration.Status.REGISTERED
                )
                registration.registered_at = timezone.now()
                registration.full_clean()
                registration.save(
                    update_fields=[
                        'status',
                        'registered_at',
                        'updated_at',
                    ]
                )

        approved_at = timezone.now()
        service_end = _activity_service_end(activity)

        payment.registration = registration
        payment.economic_scope = (
            Payment.EconomicScope.PROFESSIONAL_ACTIVITY
        )
        payment.status = Payment.Status.APPROVED
        payment.approved_at = approved_at
        payment.provider_reference = (
            f'SBX-{str(payment.public_id).split("-")[0].upper()}'
        )
        payment.failure_reason = ''

        # V103: la política y las condiciones económicas se congelan
        # cuando el pago queda aprobado. Estos datos son internos y
        # permiten mantener la trazabilidad histórica de la operación.
        payment.policy_version = PAYMENTS_POLICY_VERSION
        payment.policy_accepted_at = approved_at

        apply_payment_commission_snapshot(
            payment,
            at=approved_at,
            save=False,
        )

        refresh_payment_settlement_status(
            payment,
            service_end=service_end,
            now=approved_at,
            save=False,
        )

        try:
            payment.full_clean()
            payment.save(
                update_fields=[
                    'registration',
                    'economic_scope',
                    'status',
                    'approved_at',
                    'provider_reference',
                    'failure_reason',
                    'plan_code_snapshot',
                    'commission_rate_percent',
                    'commission_base_clp',
                    'commission_amount_clp',
                    'net_amount_clp',
                    'policy_version',
                    'policy_accepted_at',
                    'settlement_status',
                    'settlement_eligible_at',
                    'updated_at',
                ]
            )
        except IntegrityError:
            messages.error(
                request,
                (
                    'Ya existe un pago aprobado para esta actividad.'
                ),
            )
            return redirect(
                'activities:detail',
                activity_id=activity.pk,
            )

        # V103: mantenemos una liquidación agregada por actividad.
        # La pantalla agrupada se conectará a esta entidad más adelante.
        sync_activity_settlement(
            activity,
            service_end=service_end,
            now=approved_at,
        )

    messages.success(
        request,
        (
            'Pago aprobado en sandbox. '
            'Tu cupo quedó reservado correctamente.'
        ),
    )

    return redirect(
        'payments:receipt',
        payment_id=payment.public_id,
    )


@login_required(login_url='accounts:login')
def cancel_paid_activity(
    request,
    activity_id,
):
    payment = get_object_or_404(
        Payment.objects
        .select_related(
            'activity',
            'activity__organizer',
            'registration',
        ),
        payer=request.user,
        activity_id=activity_id,
        status=Payment.Status.APPROVED,
        registration__status=ActivityRegistration.Status.REGISTERED,
    )

    try:
        decision = preview_member_activity_cancellation(
            payment,
            cancelled_at=timezone.now(),
        )

        if (
            payment.policy_version != PAYMENTS_POLICY_VERSION
            or payment.policy_accepted_at is None
        ):
            raise RefundProcessingError(
                'Este pago fue realizado antes de la política automática vigente.'
            )

        if payment.settlement_status == Payment.SettlementStatus.SETTLED:
            raise RefundProcessingError(
                'Este pago ya fue liquidado y requiere una revisión especial.'
            )

        if decision.hours_before_service <= 0:
            raise RefundProcessingError(
                'La actividad ya comenzó. La cancelación automática ya no está disponible.'
            )

    except RefundProcessingError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            'activities:detail',
            activity_id=activity_id,
        )

    if request.method == 'POST':
        try:
            outcome = process_member_activity_cancellation(
                payment,
                request.user,
                cancelled_at=timezone.now(),
            )
        except RefundProcessingError as exc:
            messages.error(
                request,
                str(exc),
            )
            return redirect(
                'activities:detail',
                activity_id=activity_id,
            )

        messages.success(
            request,
            (
                'Cancelación procesada correctamente. '
                f'Se registró un reembolso de '
                f'${outcome.decision.refund_amount_clp:,.0f} CLP.'
            ).replace(',', '.'),
        )

        return redirect(
            'payments:receipt',
            payment_id=outcome.payment.public_id,
        )

    return render(
        request,
        'payments/cancel_activity.html',
        {
            'payment': payment,
            'activity': payment.activity,
            'decision': decision,
            'sandbox_enabled': _sandbox_enabled(),
        },
    )


@login_required(login_url='accounts:login')
def sandbox_reject(
    request,
    payment_id,
):
    if request.method != 'POST':
        return redirect(
            'payments:receipt',
            payment_id=payment_id,
        )

    if not _sandbox_enabled():
        raise Http404(
            'La simulación de pagos no está habilitada.'
        )

    with transaction.atomic():
        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            public_id=payment_id,
            payer=request.user,
        )

        if payment.status != Payment.Status.PENDING:
            messages.info(
                request,
                'Este intento de pago ya no está pendiente.',
            )
            return redirect(
                'payments:receipt',
                payment_id=payment.public_id,
            )

        payment.status = Payment.Status.FAILED
        payment.failure_reason = (
            'Pago rechazado por la simulación sandbox.'
        )
        payment.save(
            update_fields=[
                'status',
                'failure_reason',
                'updated_at',
            ]
        )

    messages.error(
        request,
        'El pago fue rechazado en la simulación.',
    )

    return redirect(
        'payments:receipt',
        payment_id=payment.public_id,
    )


@login_required(login_url='accounts:login')
def cancel_payment(
    request,
    payment_id,
):
    if request.method != 'POST':
        return redirect(
            'payments:receipt',
            payment_id=payment_id,
        )

    with transaction.atomic():
        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            public_id=payment_id,
            payer=request.user,
        )

        if payment.status != Payment.Status.PENDING:
            messages.info(
                request,
                'Este pago ya no puede cancelarse.',
            )
            return redirect(
                'payments:receipt',
                payment_id=payment.public_id,
            )

        payment.status = Payment.Status.CANCELLED
        payment.failure_reason = (
            'Pago cancelado por el Miembro antes de completarlo.'
        )
        payment.save(
            update_fields=[
                'status',
                'failure_reason',
                'updated_at',
            ]
        )

    messages.info(
        request,
        'El intento de pago fue cancelado.',
    )

    return redirect(
        'payments:receipt',
        payment_id=payment.public_id,
    )


@login_required(login_url='accounts:login')
def my_payments(
    request,
):
    payments = (
        Payment.objects
        .filter(
            payer=request.user,
        )
        .select_related(
            'activity',
            'activity__organizer',
            'registration',
        )
        .order_by(
            '-created_at',
        )
    )

    approved_total = (
        payments
        .filter(
            status=Payment.Status.APPROVED,
        )
        .aggregate(
            total=Sum('amount_clp'),
        )
        .get('total')
        or 0
    )

    return render(
        request,
        'payments/my_payments.html',
        {
            'payments': payments,
            'approved_total': approved_total,
        },
    )


def _economic_payment_statuses():
    return [
        Payment.Status.APPROVED,
        Payment.Status.PARTIALLY_REFUNDED,
        Payment.Status.REFUNDED,
    ]


def _activity_settlement_label(payments):
    statuses = {
        payment.settlement_status
        for payment in payments
    }

    if Payment.SettlementStatus.ON_HOLD in statuses:
        return {
            'code': 'on_hold',
            'label': 'En revisión',
        }

    if statuses and statuses == {Payment.SettlementStatus.SETTLED}:
        return {
            'code': 'settled',
            'label': 'Liquidado',
        }

    if Payment.SettlementStatus.ELIGIBLE in statuses:
        return {
            'code': 'eligible',
            'label': 'Elegible para liquidación',
        }

    return {
        'code': 'pending',
        'label': 'Pendiente de liquidación',
    }


def _build_professional_activity_groups(payments):
    groups = {}

    for payment in payments:
        activity = payment.activity

        if activity.pk not in groups:
            groups[activity.pk] = {
                'activity': activity,
                'payments': [],
                'gross_total': 0,
                'refunded_total': 0,
                'commission_total': 0,
                'net_total': 0,
                'active_paid_count': 0,
                'refunded_count': 0,
                'eligible_at': None,
            }

        group = groups[activity.pk]
        group['payments'].append(payment)
        group['gross_total'] += payment.amount_clp
        group['refunded_total'] += payment.refunded_amount_clp
        group['commission_total'] += payment.commission_amount_clp
        group['net_total'] += payment.net_amount_clp

        if payment.refunded_amount_clp > 0:
            group['refunded_count'] += 1

        if (
            payment.registration
            and payment.registration.status
            == ActivityRegistration.Status.REGISTERED
            and payment.status
            in [
                Payment.Status.APPROVED,
                Payment.Status.PARTIALLY_REFUNDED,
            ]
        ):
            group['active_paid_count'] += 1

        if payment.settlement_eligible_at:
            if (
                group['eligible_at'] is None
                or payment.settlement_eligible_at > group['eligible_at']
            ):
                group['eligible_at'] = payment.settlement_eligible_at

    result = []

    for group in groups.values():
        settlement = _activity_settlement_label(group['payments'])
        group['settlement_code'] = settlement['code']
        group['settlement_label'] = settlement['label']
        result.append(group)

    result.sort(
        key=lambda item: (
            item['activity'].date,
            item['activity'].start_time,
            item['activity'].pk,
        ),
        reverse=True,
    )

    return result


@login_required(login_url='accounts:login')
def professional_income(
    request,
):
    professional_profile = getattr(
        request.user,
        'professional_profile',
        None,
    )

    if (
        professional_profile is None
        or professional_profile.verification_status != 'verified'
    ):
        messages.error(
            request,
            'Necesitas un Perfil Profesional verificado para revisar tus pagos.',
        )
        return redirect(
            'accounts:dashboard',
        )

    professional_payments = list(
        Payment.objects
        .filter(
            activity__organizer=request.user,
            activity__activity_type=Activity.ActivityType.PROFESSIONAL,
            status__in=_economic_payment_statuses(),
        )
        .select_related(
            'payer',
            'activity',
            'activity__category',
            'registration',
        )
        .order_by(
            '-activity__date',
            '-activity__start_time',
            '-approved_at',
            '-created_at',
        )
    )

    activity_groups = _build_professional_activity_groups(
        professional_payments,
    )

    to_settle_total = sum(
        payment.net_amount_clp
        for payment in professional_payments
        if payment.settlement_status
        in [
            Payment.SettlementStatus.PENDING,
            Payment.SettlementStatus.ELIGIBLE,
            Payment.SettlementStatus.ON_HOLD,
        ]
    )

    settled_total = sum(
        payment.net_amount_clp
        for payment in professional_payments
        if payment.settlement_status
        == Payment.SettlementStatus.SETTLED
    )

    refunded_total = sum(
        payment.refunded_amount_clp
        for payment in professional_payments
    )

    gross_total = sum(
        payment.amount_clp
        for payment in professional_payments
    )

    commission_total = sum(
        payment.commission_amount_clp
        for payment in professional_payments
    )

    return render(
        request,
        'payments/professional_income.html',
        {
            'professional_profile': professional_profile,
            'activity_groups': activity_groups,
            'to_settle_total': to_settle_total,
            'settled_total': settled_total,
            'refunded_total': refunded_total,
            'gross_total': gross_total,
            'commission_total': commission_total,
            'paid_activity_count': len(activity_groups),
        },
    )


@login_required(login_url='accounts:login')
def activity_payments(
    request,
    activity_id,
):
    activity = get_object_or_404(
        Activity.objects.select_related(
            'organizer',
            'professional_profile',
        ),
        pk=activity_id,
        organizer=request.user,
        activity_type=Activity.ActivityType.PROFESSIONAL,
        price__gt=0,
    )

    payments = list(
        Payment.objects
        .filter(
            activity=activity,
        )
        .select_related(
            'payer',
            'registration',
        )
        .order_by(
            '-created_at',
        )
    )

    economic_payments = [
        payment
        for payment in payments
        if payment.status in _economic_payment_statuses()
    ]

    gross_total = sum(
        payment.amount_clp
        for payment in economic_payments
    )

    refunded_total = sum(
        payment.refunded_amount_clp
        for payment in economic_payments
    )

    commission_total = sum(
        payment.commission_amount_clp
        for payment in economic_payments
    )

    net_total = sum(
        payment.net_amount_clp
        for payment in economic_payments
    )

    active_paid_count = sum(
        1
        for payment in economic_payments
        if (
            payment.registration
            and payment.registration.status
            == ActivityRegistration.Status.REGISTERED
            and payment.status
            in [
                Payment.Status.APPROVED,
                Payment.Status.PARTIALLY_REFUNDED,
            ]
        )
    )

    refunded_count = sum(
        1
        for payment in economic_payments
        if payment.refunded_amount_clp > 0
    )

    settlement = _activity_settlement_label(
        economic_payments,
    )

    eligible_dates = [
        payment.settlement_eligible_at
        for payment in economic_payments
        if payment.settlement_eligible_at
    ]

    eligible_at = max(eligible_dates) if eligible_dates else None

    return render(
        request,
        'payments/activity_payments.html',
        {
            'activity': activity,
            'payments': payments,
            'gross_total': gross_total,
            'refunded_total': refunded_total,
            'commission_total': commission_total,
            'net_total': net_total,
            'active_paid_count': active_paid_count,
            'refunded_count': refunded_count,
            'settlement_code': settlement['code'],
            'settlement_label': settlement['label'],
            'eligible_at': eligible_at,
            'activity_settlement': (
                Settlement.objects
                .filter(
                    scope_type=Settlement.ScopeType.ACTIVITY,
                    activity=activity,
                )
                .first()
            ),
            'sandbox_enabled': _sandbox_enabled(),
        },
    )


@login_required(login_url='accounts:login')
def sandbox_make_activity_settlement_eligible(
    request,
    activity_id,
):
    if request.method != 'POST':
        return redirect(
            'payments:activity_payments',
            activity_id=activity_id,
        )

    if not _sandbox_enabled():
        raise Http404(
            'La simulación de liquidaciones no está habilitada.'
        )

    activity = get_object_or_404(
        Activity,
        pk=activity_id,
        organizer=request.user,
        activity_type=Activity.ActivityType.PROFESSIONAL,
    )

    service_end = _activity_service_end(activity)
    eligible_at = calculate_settlement_eligible_at(service_end)

    settlement = sync_activity_settlement(
        activity,
        service_end=service_end,
        now=eligible_at,
    )

    if settlement.net_amount_clp <= 0:
        messages.info(
            request,
            'Esta actividad no tiene monto por liquidar.',
        )
    elif settlement.status == Settlement.Status.ELIGIBLE:
        messages.success(
            request,
            (
                'Sandbox: se simuló el cumplimiento de la ventana '
                'de 24 horas. La liquidación ya es elegible.'
            ),
        )
    else:
        messages.info(
            request,
            f'Estado actual: {settlement.get_status_display()}.',
        )

    return redirect(
        'payments:activity_payments',
        activity_id=activity.pk,
    )


@login_required(login_url='accounts:login')
def sandbox_settle_activity(
    request,
    activity_id,
):
    if request.method != 'POST':
        return redirect(
            'payments:activity_payments',
            activity_id=activity_id,
        )

    if not _sandbox_enabled():
        raise Http404(
            'La simulación de liquidaciones no está habilitada.'
        )

    activity = get_object_or_404(
        Activity,
        pk=activity_id,
        organizer=request.user,
        activity_type=Activity.ActivityType.PROFESSIONAL,
    )

    settlement = get_object_or_404(
        Settlement,
        scope_type=Settlement.ScopeType.ACTIVITY,
        activity=activity,
        beneficiary=request.user,
    )

    try:
        # En sandbox usamos eligible_at como reloj simulado.
        simulated_now = (
            settlement.eligible_at
            if settlement.eligible_at
            else timezone.now()
        )

        settlement = settle_activity_settlement(
            settlement,
            now=simulated_now,
        )
    except SettlementProcessingError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            'payments:activity_payments',
            activity_id=activity.pk,
        )

    messages.success(
        request,
        (
            'Liquidación sandbox completada correctamente. '
            f'Monto neto: ${settlement.net_amount_clp:,.0f} CLP.'
        ).replace(',', '.'),
    )

    return redirect(
        'payments:activity_payments',
        activity_id=activity.pk,
    )
