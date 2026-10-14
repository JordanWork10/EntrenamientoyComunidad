from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.activities.models import Activity, ActivityRegistration

from .models import Payment


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
        Payment.objects.select_related(
            'activity',
            'activity__organizer',
            'registration',
        ),
        public_id=payment_id,
        payer=request.user,
    )

    return render(
        request,
        'payments/receipt.html',
        {
            'payment': payment,
            'activity': payment.activity,
            'sandbox_enabled': _sandbox_enabled(),
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

        payment.registration = registration
        payment.status = Payment.Status.APPROVED
        payment.approved_at = timezone.now()
        payment.provider_reference = (
            f'SBX-{str(payment.public_id).split("-")[0].upper()}'
        )
        payment.failure_reason = ''

        try:
            payment.full_clean()
            payment.save(
                update_fields=[
                    'registration',
                    'status',
                    'approved_at',
                    'provider_reference',
                    'failure_reason',
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
            'Necesitas un Perfil Profesional verificado para revisar pagos recibidos.',
        )
        return redirect(
            'accounts:dashboard',
        )

    professional_payments = (
        Payment.objects
        .filter(
            activity__organizer=request.user,
            activity__activity_type=Activity.ActivityType.PROFESSIONAL,
            status__in=[
                Payment.Status.APPROVED,
                Payment.Status.REFUNDED,
            ],
        )
        .select_related(
            'payer',
            'activity',
            'activity__category',
            'registration',
        )
        .order_by(
            '-approved_at',
            '-created_at',
        )
    )

    approved_payments = professional_payments.filter(
        status=Payment.Status.APPROVED,
    )

    refunded_payments = professional_payments.filter(
        status=Payment.Status.REFUNDED,
    )

    approved_total = (
        approved_payments
        .aggregate(
            total=Sum('amount_clp'),
        )
        .get('total')
        or 0
    )

    refunded_total = (
        refunded_payments
        .aggregate(
            total=Sum('amount_clp'),
        )
        .get('total')
        or 0
    )

    paid_activity_count = (
        professional_payments
        .values('activity_id')
        .distinct()
        .count()
    )

    return render(
        request,
        'payments/professional_income.html',
        {
            'professional_profile': professional_profile,
            'payments': professional_payments,
            'approved_count': approved_payments.count(),
            'approved_total': approved_total,
            'refunded_count': refunded_payments.count(),
            'refunded_total': refunded_total,
            'paid_activity_count': paid_activity_count,
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

    payments = (
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

    approved_payments = payments.filter(
        status=Payment.Status.APPROVED,
    )

    approved_total = (
        approved_payments
        .aggregate(
            total=Sum('amount_clp'),
        )
        .get('total')
        or 0
    )

    return render(
        request,
        'payments/activity_payments.html',
        {
            'activity': activity,
            'payments': payments,
            'approved_count': approved_payments.count(),
            'approved_total': approved_total,
        },
    )
