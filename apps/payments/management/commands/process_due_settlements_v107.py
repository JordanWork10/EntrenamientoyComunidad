from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.payments.models import Settlement
from apps.payments.services.settlements import (
    SettlementProcessingError,
    settle_activity_settlement,
    sync_activity_settlement,
)


def activity_service_end(activity):
    value = datetime.combine(
        activity.date,
        activity.end_time,
    )

    if activity.end_time <= activity.start_time:
        value += timedelta(days=1)

    if timezone.is_naive(value):
        value = timezone.make_aware(
            value,
            timezone.get_current_timezone(),
        )

    return value


class Command(BaseCommand):
    help = (
        'Actualiza liquidaciones de actividades y, en sandbox, '
        'liquida automáticamente las que ya son elegibles.'
    )

    def handle(self, *args, **options):
        now = timezone.now()

        settlements = (
            Settlement.objects
            .filter(
                scope_type=Settlement.ScopeType.ACTIVITY,
                status__in=[
                    Settlement.Status.PENDING,
                    Settlement.Status.ELIGIBLE,
                ],
            )
            .select_related(
                'activity',
                'beneficiary',
            )
        )

        refreshed = 0
        settled = 0
        skipped = 0

        for settlement in settlements:
            activity = settlement.activity

            if activity is None:
                skipped += 1
                continue

            settlement = sync_activity_settlement(
                activity,
                service_end=activity_service_end(activity),
                now=now,
            )
            refreshed += 1

            if settlement.net_amount_clp <= 0:
                skipped += 1
                continue

            if settlement.status != Settlement.Status.ELIGIBLE:
                continue

            if not getattr(settings, 'PAYMENTS_SANDBOX', False):
                self.stdout.write(
                    self.style.WARNING(
                        f'{activity.title}: elegible, pendiente de proveedor real.'
                    )
                )
                continue

            try:
                settle_activity_settlement(
                    settlement,
                    now=now,
                    provider_reference=(
                        f'AUTO-SBX-{str(settlement.public_id).split("-")[0].upper()}'
                    ),
                )
                settled += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'{activity.title}: liquidada automáticamente en sandbox.'
                    )
                )
            except SettlementProcessingError as exc:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'{activity.title}: {exc}'
                    )
                )

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                'V107 completado · '
                f'actualizadas={refreshed} · '
                f'liquidadas={settled} · '
                f'omitidas={skipped}'
            )
        )
