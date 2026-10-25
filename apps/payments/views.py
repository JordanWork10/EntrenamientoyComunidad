from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import Http404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.activities.models import Activity, ActivityRegistration
from apps.spaces.models import Space, SpaceBooking, SpaceProviderProfile

from .models import Payment, Settlement
from .services.cancellation_policy import PAYMENTS_POLICY_VERSION
from .services.commissions import apply_payment_commission_snapshot
from .services.settlements import (
    SettlementProcessingError,
    calculate_settlement_eligible_at,
    refresh_payment_settlement_status,
    settle_activity_settlement,
    sync_activity_settlement,
    sync_space_day_settlement,
    settle_space_day_settlement,
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
        activity__isnull=False,
        space_booking__isnull=True,
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
            activity__isnull=False,
            space_booking__isnull=True,
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
            activity__isnull=False,
            space_booking__isnull=True,
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
            activity__isnull=False,
            space_booking__isnull=True,
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
            'space_booking',
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


# ============================================================================
# V131 — PAGOS SANDBOX PARA ARRIENDOS DE ESPACIOS
# Las funciones anteriores de actividades profesionales se mantienen intactas.
# ============================================================================




@login_required(login_url='accounts:login')
def space_income(request):
    """V131.24: consulta de ingresos sandbox por recinto, solo para su dueño.

    No crea pagos, reembolsos ni liquidaciones. Los importes se derivan de
    snapshots históricos guardados en Payment, no de reservas confirmadas.
    """
    profile = getattr(request.user, 'space_provider_profile', None)
    if (
        profile is None
        or profile.verification_status
        != SpaceProviderProfile.VerificationStatus.VERIFIED
        or not profile.is_public
    ):
        messages.error(request, 'Necesitas un Perfil Proveedor verificado y activo.')
        return redirect('accounts:dashboard')

    spaces = list(
        profile.spaces.select_related('space_type', 'commune')
        .order_by('-created_at', '-pk')
    )
    groups_by_id = {}
    groups = []
    for space in spaces:
        group = {
            'space': space,
            'payments': [],
            'attempt_count': 0,
            'approved_count': 0,
            'pending_count': 0,
            'gross_total': 0,
            'refunded_total': 0,
            'commission_total': 0,
            'net_total': 0,
            'to_settle_total': 0,
            'settled_total': 0,
        }
        groups_by_id[space.pk] = group
        groups.append(group)

    payments = list(
        Payment.objects.filter(
            space_booking__provider_profile=profile,
            space_booking__isnull=False,
            activity__isnull=True,
            economic_scope=Payment.EconomicScope.SPACE_BOOKING,
        )
        .select_related('payer', 'space_booking', 'space_booking__space')
        .order_by('-created_at', '-pk')
    )

    totals = {
        'attempt_count': 0,
        'approved_count': 0,
        'pending_count': 0,
        'gross_total': 0,
        'refunded_total': 0,
        'commission_total': 0,
        'net_total': 0,
        'to_settle_total': 0,
        'settled_total': 0,
    }
    financial_statuses = {
        Payment.Status.APPROVED,
        Payment.Status.PARTIALLY_REFUNDED,
        Payment.Status.REFUNDED,
    }

    for payment in payments:
        group = groups_by_id.get(payment.space_booking.space_id)
        if group is None:
            continue
        group['payments'].append(payment)
        for bucket in (group, totals):
            bucket['attempt_count'] += 1
            if payment.status == Payment.Status.PENDING:
                bucket['pending_count'] += 1
            if payment.status in financial_statuses:
                bucket['approved_count'] += 1
                bucket['gross_total'] += payment.amount_clp
                bucket['refunded_total'] += payment.refunded_amount_clp
                bucket['commission_total'] += payment.commission_amount_clp
                bucket['net_total'] += payment.net_amount_clp
                if payment.settlement_status == Payment.SettlementStatus.SETTLED:
                    bucket['settled_total'] += payment.net_amount_clp
                else:
                    bucket['to_settle_total'] += payment.net_amount_clp

    return render(request, 'payments/space_income.html', {
        'provider_profile': profile,
        'groups': groups,
        'totals': totals,
        'sandbox_enabled': _sandbox_enabled(),
    })


def _space_booking_session_time(booking, *, end=False):
    """Fecha/hora aware del bloque reservado, usando la zona de Django."""
    value = booking.end_time if end else booking.start_time
    result = datetime.combine(booking.session_date, value)
    return timezone.make_aware(result, timezone.get_current_timezone())


def _space_booking_payment_allowed(booking, now=None):
    """No aceptar pagos de reservas no confirmadas, vencidas o sin proveedor."""
    now = now or timezone.now()
    return (
        booking.status == SpaceBooking.Status.CONFIRMED
        and booking.price_clp > 0
        and booking.provider_profile.verification_status
        == SpaceProviderProfile.VerificationStatus.VERIFIED
        and booking.provider_profile.user_id != booking.booked_by_id
        and _space_booking_session_time(booking) > now
    )


def _approved_space_payments(booking):
    return Payment.objects.filter(
        space_booking=booking,
        activity__isnull=True,
        economic_scope=Payment.EconomicScope.SPACE_BOOKING,
        status__in=[
            Payment.Status.APPROVED,
            Payment.Status.PARTIALLY_REFUNDED,
            Payment.Status.REFUNDED,
        ],
    )


def _get_space_payment_for_member(request, payment_id):
    return get_object_or_404(
        Payment.objects.select_related(
            'space_booking',
            'space_booking__space',
            'space_booking__provider_profile',
            'space_booking__provider_profile__user',
        ),
        public_id=payment_id,
        payer=request.user,
        space_booking__isnull=False,
        activity__isnull=True,
        economic_scope=Payment.EconomicScope.SPACE_BOOKING,
    )


@login_required(login_url='accounts:login')
def space_checkout(request, booking_id):
    """Abre/reutiliza un intento sandbox para una reserva aceptada y futura."""
    booking = get_object_or_404(
        SpaceBooking.objects.select_related('provider_profile__user'),
        pk=booking_id,
        booked_by=request.user,
    )

    if not _sandbox_enabled():
        messages.error(request, 'Los pagos sandbox de arriendos no están habilitados.')
        return redirect('spaces:booking_detail', booking_id=booking.pk)

    with transaction.atomic():
        booking = get_object_or_404(
            SpaceBooking.objects.select_for_update().select_related(
                'provider_profile__user'
            ),
            pk=booking_id,
            booked_by=request.user,
        )

        previous_payment = (
            _approved_space_payments(booking).order_by('-approved_at').first()
        )
        if previous_payment:
            return redirect(
                'payments:space_receipt', payment_id=previous_payment.public_id,
            )

        if not _space_booking_payment_allowed(booking):
            messages.error(
                request,
                'Este arriendo no está confirmado, su horario venció '
                'o el proveedor no está habilitado para recibir pagos.',
            )
            return redirect('spaces:booking_detail', booking_id=booking.pk)

        # La reserva se bloquea antes de decidir el intento, evitando
        # creaciones simultáneas por sesiones distintas del mismo miembro.
        payment = (
            Payment.objects.filter(
                space_booking=booking,
                payer=request.user,
                activity__isnull=True,
                economic_scope=Payment.EconomicScope.SPACE_BOOKING,
                status=Payment.Status.PENDING,
                amount_clp=booking.price_clp,
            ).order_by('-created_at').first()
        )

        if payment is None:
            payment = Payment(
                payer=request.user,
                activity=None,
                space_booking=booking,
                economic_scope=Payment.EconomicScope.SPACE_BOOKING,
                amount_clp=booking.price_clp,
                currency='CLP',
                provider=Payment.Provider.SANDBOX,
                status=Payment.Status.PENDING,
            )
            payment.full_clean()
            payment.save()

    return render(request, 'payments/space_checkout.html', {
        'booking': booking,
        'payment': payment,
        'sandbox_enabled': _sandbox_enabled(),
    })


@login_required(login_url='accounts:login')
def space_receipt(request, payment_id):
    """Comprobante separado, accesible únicamente por el miembro pagador."""
    payment = _get_space_payment_for_member(request, payment_id)
    return render(request, 'payments/space_receipt.html', {
        'payment': payment,
        'booking': payment.space_booking,
        'sandbox_enabled': _sandbox_enabled(),
        'retained_amount_clp': max(
            payment.amount_clp - payment.refunded_amount_clp, 0,
        ),
    })


@login_required(login_url='accounts:login')
def space_sandbox_approve(request, payment_id):
    """Aprobación idempotente con bloqueo transaccional del bloque reservado."""
    if request.method != 'POST':
        return redirect('payments:space_receipt', payment_id=payment_id)
    if not _sandbox_enabled():
        raise Http404('La simulación de pagos de arriendos está deshabilitada.')

    existing = _get_space_payment_for_member(request, payment_id)
    booking_id = existing.space_booking_id

    # Bloqueo consistente con las operaciones de cancelación en spaces.
    # La transacción se confirma solo cuando todas las validaciones pasan.
    try:
        with transaction.atomic():
            booking = get_object_or_404(
                SpaceBooking.objects.select_for_update().select_related(
                    'provider_profile__user'
                ),
                pk=booking_id,
                booked_by=request.user,
            )
            payment = get_object_or_404(
                Payment.objects.select_for_update(),
                pk=existing.pk,
                payer=request.user,
                space_booking=booking,
                activity__isnull=True,
                economic_scope=Payment.EconomicScope.SPACE_BOOKING,
            )

            if payment.status == Payment.Status.APPROVED:
                messages.info(request, 'Este pago sandbox ya estaba aprobado.')
                return redirect(
                    'payments:space_receipt', payment_id=payment.public_id,
                )

            if payment.status != Payment.Status.PENDING:
                messages.error(
                    request,
                    'Este intento ya terminó. Inicia otro desde tu reserva.',
                )
                return redirect(
                    'payments:space_receipt', payment_id=payment.public_id,
                )

            if request.POST.get('accept_sandbox') != '1':
                messages.error(request, 'Debes confirmar que es una simulación.')
                return redirect(
                    'payments:space_checkout', booking_id=booking.pk,
                )

            if not _space_booking_payment_allowed(booking):
                messages.error(
                    request,
                    'No se puede aprobar el pago: la reserva ya no es '
                    'válida para pago o su horario comenzó.',
                )
                return redirect(
                    'payments:space_receipt', payment_id=payment.public_id,
                )

            if payment.amount_clp != booking.price_clp:
                messages.error(
                    request,
                    'El importe del pago no coincide con el precio '
                    'histórico del arriendo.',
                )
                return redirect(
                    'payments:space_receipt', payment_id=payment.public_id,
                )

            if _approved_space_payments(booking).exclude(pk=payment.pk).exists():
                messages.error(request, 'Este arriendo ya registra un pago.')
                return redirect('spaces:booking_detail', booking_id=booking.pk)

            now = timezone.now()
            payment.status = Payment.Status.APPROVED
            payment.approved_at = now
            payment.provider_reference = (
                f'SBX-SPC-{str(payment.public_id).split("-")[0].upper()}'
            )
            payment.failure_reason = ''

            # Congela plan y comisión del proveedor SOLO al aprobar.
            apply_payment_commission_snapshot(payment, at=now, save=False)
            refresh_payment_settlement_status(
                payment,
                service_end=_space_booking_session_time(booking, end=True),
                now=now,
                save=False,
            )
            # Sin política automática de reembolso de arriendos todavía.
            # No se genera Settlement ni se marca SETTLED en esta versión.
            payment.full_clean()
            payment.save(update_fields=[
                'status', 'approved_at', 'provider_reference', 'failure_reason',
                'plan_code_snapshot', 'commission_rate_percent',
                'commission_base_clp', 'commission_amount_clp',
                'net_amount_clp', 'settlement_status', 'settlement_eligible_at',
                'updated_at',
            ])
    except IntegrityError:
        messages.error(
            request, 'El pago no se completó: ya existe otra operación '
            'aprobada para este arriendo.',
        )
        return redirect('spaces:booking_detail', booking_id=booking_id)

    messages.success(
        request, 'Pago aprobado en sandbox. No se realizó ningún cobro real.',
    )
    return redirect('payments:space_receipt', payment_id=payment.public_id)


@login_required(login_url='accounts:login')
def space_sandbox_reject(request, payment_id):
    if request.method != 'POST':
        return redirect('payments:space_receipt', payment_id=payment_id)
    if not _sandbox_enabled():
        raise Http404('La simulación de pagos de arriendos está deshabilitada.')

    existing = _get_space_payment_for_member(request, payment_id)
    with transaction.atomic():
        booking = get_object_or_404(
            SpaceBooking.objects.select_for_update(), pk=existing.space_booking_id,
        )
        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            pk=existing.pk, payer=request.user, space_booking=booking,
            activity__isnull=True,
            economic_scope=Payment.EconomicScope.SPACE_BOOKING,
        )
        if payment.status != Payment.Status.PENDING:
            messages.info(request, 'Este intento ya no está pendiente.')
        else:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = 'Pago rechazado en simulación sandbox.'
            payment.save(update_fields=[
                'status', 'failure_reason', 'updated_at',
            ])
            messages.error(request, 'El pago fue rechazado en sandbox.')

    return redirect('payments:space_receipt', payment_id=payment_id)


@login_required(login_url='accounts:login')
def space_cancel(request, payment_id):
    """Cancela solamente un INTENTO pendiente, no la reserva en sí."""
    if request.method != 'POST':
        return redirect('payments:space_receipt', payment_id=payment_id)

    existing = _get_space_payment_for_member(request, payment_id)
    with transaction.atomic():
        booking = get_object_or_404(
            SpaceBooking.objects.select_for_update(), pk=existing.space_booking_id,
        )
        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            pk=existing.pk, payer=request.user, space_booking=booking,
            activity__isnull=True,
            economic_scope=Payment.EconomicScope.SPACE_BOOKING,
        )
        if payment.status != Payment.Status.PENDING:
            messages.info(request, 'Este pago ya no puede cancelarse.')
        else:
            payment.status = Payment.Status.CANCELLED
            payment.failure_reason = 'Intento cancelado por el miembro.'
            payment.save(update_fields=[
                'status', 'failure_reason', 'updated_at',
            ])
            messages.info(request, 'El intento de pago fue cancelado.')

    return redirect('payments:space_receipt', payment_id=payment_id)


# ============================================================================
# V131.58 — ADMINISTRACIÓN SEGURA DE LIQUIDACIONES DE ESPACIOS (SANDBOX)
# GET solo muestra datos; POST exige CSRF, staff y permiso change_settlement.
# Roberto y otros proveedores jamás pueden autorizar sus propias liquidaciones.
# ============================================================================


def _require_space_settlement_operator(request):
    """Autorización explícita, adicional a la autenticación."""
    user = request.user
    if not (
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perm('payments.change_settlement')
    ):
        raise PermissionDenied('No tienes autorización para gestionar liquidaciones.')
    if not _sandbox_enabled():
        raise Http404('Las liquidaciones de espacios solo están disponibles en sandbox.')


@login_required(login_url='accounts:login')
@require_GET
def space_settlement_admin(request):
    """Resumen administrativo solo lectura por espacio y jornada."""
    _require_space_settlement_operator(request)

    eligible_payment_statuses = (
        Payment.Status.APPROVED,
        Payment.Status.PARTIALLY_REFUNDED,
        Payment.Status.REFUNDED,
    )
    payments = (
        Payment.objects.filter(
            economic_scope=Payment.EconomicScope.SPACE_BOOKING,
            activity__isnull=True,
            space_booking__isnull=False,
            status__in=eligible_payment_statuses,
        )
        .select_related('space_booking', 'space_booking__space')
        .order_by('space_booking__session_date', 'pk')
    )

    grouped = {}
    def ensure_group(space, date_value):
        key = (space.pk, date_value)
        if key not in grouped:
            grouped[key] = {
                'space': space,
                'date': date_value,
                'payment_count': 0,
                'booking_count': 0,
                'gross_total': 0,
                'commission_total': 0,
                'net_total': 0,
                'settlement': None,
                'incomplete': False,
            }
        return grouped[key]

    booking_ids_by_key = {}
    for payment in payments:
        booking = payment.space_booking
        group = ensure_group(booking.space, booking.session_date)
        group['payment_count'] += 1
        group['gross_total'] += payment.amount_clp
        group['commission_total'] += payment.commission_amount_clp
        group['net_total'] += payment.net_amount_clp
        key = (booking.space_id, booking.session_date)
        booking_ids_by_key.setdefault(key, set()).add(booking.pk)
        if payment.net_amount_clp > 0 and booking.status != SpaceBooking.Status.COMPLETED:
            group['incomplete'] = True

    settlements = Settlement.objects.filter(
        scope_type=Settlement.ScopeType.SPACE_DAY,
    ).select_related('space', 'beneficiary').order_by('-reference_date', '-pk')
    for settlement in settlements:
        group = ensure_group(settlement.space, settlement.reference_date)
        group['settlement'] = settlement

    for key, group in grouped.items():
        group['booking_count'] = len(booking_ids_by_key.get(key, set()))
        settlement = group['settlement']
        group['can_prepare'] = bool(group['payment_count']) and (
            settlement is None or settlement.status != Settlement.Status.SETTLED
        )
        group['can_settle'] = bool(
            settlement and settlement.status == Settlement.Status.ELIGIBLE
        )

    rows = sorted(
        grouped.values(),
        key=lambda group: (group['date'], group['space'].pk),
        reverse=True,
    )
    return render(request, 'payments/space_settlement_admin.html', {
        'rows': rows,
        'now': timezone.localtime(),
        'sandbox_enabled': True,
    })


@login_required(login_url='accounts:login')
@require_POST
@csrf_protect
def space_settlement_prepare(request, space_id, year, month, day):
    """Preparar/actualizar la jornada; NUNCA liquida fondos."""
    _require_space_settlement_operator(request)
    try:
        reference_date = date(year, month, day)
    except ValueError:
        raise Http404('Fecha de jornada inválida.')
    space = get_object_or_404(
        Space.objects.select_related('provider_profile'), pk=space_id,
    )
    try:
        settlement = sync_space_day_settlement(space, reference_date)
    except (SettlementProcessingError, ValidationError) as exc:
        messages.error(request, f'No fue posible preparar la jornada: {exc}')
    else:
        messages.success(
            request,
            f'Jornada {reference_date:%d/%m/%Y} de {space.name} actualizada. '
            f'Estado: {settlement.get_status_display()}. No se transfirió dinero.',
        )
    return redirect('payments:space_settlement_admin')


@login_required(login_url='accounts:login')
@require_POST
@csrf_protect
def space_settlement_close(request, settlement_id):
    """Cierre sandbox con confirmación explícita y validación real del servicio."""
    _require_space_settlement_operator(request)
    if request.POST.get('confirm') != 'yes':
        messages.error(request, 'Debes confirmar expresamente el cierre sandbox.')
        return redirect('payments:space_settlement_admin')

    settlement = get_object_or_404(
        Settlement,
        pk=settlement_id,
        scope_type=Settlement.ScopeType.SPACE_DAY,
    )
    try:
        closed = settle_space_day_settlement(
            settlement, reviewed_by=request.user,
        )
    except SettlementProcessingError as exc:
        messages.error(request, f'Liquidación rechazada: {exc}')
    else:
        messages.success(
            request,
            f'Liquidación SANDBOX #{closed.pk}: '
            f'{closed.net_amount_clp:,} CLP marcados como liquidados. '
            'No se efectuó transferencia bancaria.',
        )
    return redirect('payments:space_settlement_admin')
