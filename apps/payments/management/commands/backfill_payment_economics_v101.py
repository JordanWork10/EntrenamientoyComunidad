from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.payments.models import Payment


class Command(BaseCommand):
    help = (
        'Completa los snapshots económicos V101 de pagos creados '
        'antes de la política y las suscripciones.'
    )

    @transaction.atomic
    def handle(self, *args, **options):
        updated = 0

        for payment in Payment.objects.select_for_update().all():
            payment.plan_code_snapshot = 'professional_base'
            payment.commission_rate_percent = Decimal('12.00')
            payment.policy_version = 'LEGACY_PRE_POLICY'

            if payment.status == Payment.Status.REFUNDED:
                payment.refunded_amount_clp = payment.amount_clp
            else:
                processed_refunds = sum(
                    payment.refunds.filter(
                        status='processed'
                    ).values_list('amount_clp', flat=True)
                )
                payment.refunded_amount_clp = min(
                    processed_refunds,
                    payment.amount_clp,
                )

            if payment.status in {
                Payment.Status.APPROVED,
                Payment.Status.PARTIALLY_REFUNDED,
                Payment.Status.REFUNDED,
            }:
                payment.recalculate_economic_amounts()
            else:
                payment.commission_base_clp = 0
                payment.commission_amount_clp = 0
                payment.net_amount_clp = 0

            payment.save(
                update_fields=[
                    'plan_code_snapshot',
                    'commission_rate_percent',
                    'policy_version',
                    'refunded_amount_clp',
                    'commission_base_clp',
                    'commission_amount_clp',
                    'net_amount_clp',
                    'updated_at',
                ]
            )
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Pagos actualizados con arquitectura V101: {updated}'
            )
        )
