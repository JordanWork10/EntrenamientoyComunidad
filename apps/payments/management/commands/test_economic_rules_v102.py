from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.payments.models import Payment
from apps.payments.services.cancellation_policy import (
    calculate_member_cancellation,
)
from apps.payments.services.commissions import calculate_economic_amounts


class Command(BaseCommand):
    help = 'Prueba el motor económico V102 sin modificar pagos existentes.'

    def handle(self, *args, **options):
        now = timezone.now()
        amount = 8000

        self.stdout.write(self.style.MIGRATE_HEADING('=== V102 · CANCELACIONES ==='))

        cases = [
            ('72 horas antes', 72),
            ('48 horas antes', 48),
            ('31 horas antes', 31),
            ('24 horas antes', 24),
            ('10 horas antes', 10),
            ('1 hora después', -1),
        ]

        for label, hours in cases:
            service_start = now + timedelta(hours=hours)
            result = calculate_member_cancellation(
                amount_clp=amount,
                service_start=service_start,
                cancelled_at=now,
            )
            self.stdout.write(
                f'{label}: {result.refund_percent}% → '
                f'reembolso ${result.refund_amount_clp:,} · '
                f'retenido ${result.retained_amount_clp:,}'
                .replace(',', '.')
            )

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('=== V102 · COMISIONES ==='))

        examples = [
            ('Profesional Base', Decimal('12.00')),
            ('Profesional Pro', Decimal('7.00')),
            ('Proveedor Base', Decimal('10.00')),
            ('Espacios Pro', Decimal('5.00')),
        ]

        for name, rate in examples:
            calculation = calculate_economic_amounts(
                amount_clp=48000,
                refunded_amount_clp=0,
                commission_rate_percent=rate,
            )
            self.stdout.write(
                f'{name}: bruto $48.000 · comisión {rate}% '
                f'(${calculation.commission_amount_clp:,}) · '
                f'neto ${calculation.net_amount_clp:,}'
                .replace(',', '.')
            )

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('=== PAGO EXISTENTE ==='))

        payment = (
            Payment.objects
            .filter(status=Payment.Status.APPROVED)
            .select_related('payer', 'activity')
            .order_by('-approved_at', '-created_at')
            .first()
        )

        if payment:
            self.stdout.write(
                f'{payment.payer} · {payment.activity} · '
                f'${payment.amount_clp:,} · '
                f'plan={payment.plan_code_snapshot} · '
                f'comisión={payment.commission_rate_percent}% · '
                f'neto=${payment.net_amount_clp:,}'
                .replace(',', '.')
            )
        else:
            self.stdout.write('No hay pagos aprobados para mostrar.')

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                'Motor económico V102 probado. Este comando no modifica datos.'
            )
        )
