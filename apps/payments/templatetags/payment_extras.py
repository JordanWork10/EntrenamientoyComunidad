from django import template
from django.db.models import Sum

from apps.payments.models import Payment


register = template.Library()


@register.simple_tag
def member_payment_summary(user):
    """
    Resumen compacto para mostrar Pagos dentro de Mi cuenta.
    """

    if not getattr(user, 'is_authenticated', False):
        return {
            'movements': 0,
            'approved_total': 0,
            'pending': 0,
        }

    payments = Payment.objects.filter(
        payer=user,
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

    return {
        'movements': payments.count(),
        'approved_total': approved_total,
        'pending': (
            payments
            .filter(
                status=Payment.Status.PENDING,
            )
            .count()
        ),
    }


@register.simple_tag
def professional_payment_summary(user):
    """
    Resumen compacto para el acceso Pagos del Centro Profesional.

    movements considera operaciones económicas reales del organizador:
    aprobadas, parcialmente reembolsadas o reembolsadas.
    """

    if not getattr(user, 'is_authenticated', False):
        return {
            'movements': 0,
            'approved_count': 0,
            'approved_total': 0,
        }

    payments = Payment.objects.filter(
        activity__organizer=user,
    )

    economic_payments = payments.filter(
        status__in=[
            Payment.Status.APPROVED,
            Payment.Status.PARTIALLY_REFUNDED,
            Payment.Status.REFUNDED,
        ],
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

    return {
        'movements': economic_payments.count(),
        'approved_count': approved_payments.count(),
        'approved_total': approved_total,
    }