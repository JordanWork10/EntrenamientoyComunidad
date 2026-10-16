from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.subscriptions.models import SubscriptionPlan


class Command(BaseCommand):
    help = 'Crea o actualiza los planes oficiales V1 de EntrenamientoyComunidad.'

    def handle(self, *args, **options):
        plans = [
            {
                'code': SubscriptionPlan.Code.MEMBER_PLUS,
                'name': 'Miembro Plus',
                'monthly_price_clp': 4990,
                'intro_price_clp': 3990,
                'intro_months': 3,
                'trial_days': 7,
                'professional_commission_rate': None,
                'space_commission_rate': None,
                'includes_member_plus': True,
                'display_order': 10,
            },
            {
                'code': SubscriptionPlan.Code.PROFESSIONAL_PRO,
                'name': 'Profesional Pro',
                'monthly_price_clp': 14990,
                'intro_price_clp': 11990,
                'intro_months': 3,
                'trial_days': 7,
                'professional_commission_rate': Decimal('7.00'),
                'space_commission_rate': None,
                'includes_member_plus': True,
                'display_order': 20,
            },
            {
                'code': SubscriptionPlan.Code.SPACES_PRO,
                'name': 'Espacios Pro',
                'monthly_price_clp': 24990,
                'intro_price_clp': 19990,
                'intro_months': 3,
                'trial_days': 7,
                'professional_commission_rate': None,
                'space_commission_rate': Decimal('5.00'),
                'includes_member_plus': True,
                'display_order': 30,
            },
            {
                'code': SubscriptionPlan.Code.PRO_INTEGRAL,
                'name': 'Pro Integral',
                'monthly_price_clp': 34990,
                'intro_price_clp': 27990,
                'intro_months': 3,
                'trial_days': 7,
                'professional_commission_rate': Decimal('7.00'),
                'space_commission_rate': Decimal('5.00'),
                'includes_member_plus': True,
                'display_order': 40,
            },
        ]

        for plan_data in plans:
            code = plan_data.pop('code')
            plan, created = SubscriptionPlan.objects.update_or_create(
                code=code,
                defaults=plan_data,
            )

            action = 'creado' if created else 'actualizado'
            self.stdout.write(
                self.style.SUCCESS(f'{plan.name}: {action}')
            )

        self.stdout.write(
            self.style.SUCCESS('Planes de suscripción V1 listos.')
        )
