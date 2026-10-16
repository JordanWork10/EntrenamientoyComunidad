from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


PROFESSIONAL_BASE_COMMISSION = Decimal('12.00')
SPACE_BASE_COMMISSION = Decimal('10.00')


class SubscriptionPlan(models.Model):

    class Code(models.TextChoices):
        MEMBER_PLUS = 'member_plus', 'Miembro Plus'
        PROFESSIONAL_PRO = 'professional_pro', 'Profesional Pro'
        SPACES_PRO = 'spaces_pro', 'Espacios Pro'
        PRO_INTEGRAL = 'pro_integral', 'Pro Integral'

    code = models.CharField(
        max_length=40,
        choices=Code.choices,
        unique=True,
        verbose_name='Código',
    )

    name = models.CharField(
        max_length=80,
        verbose_name='Nombre',
    )

    monthly_price_clp = models.PositiveIntegerField(
        verbose_name='Precio mensual normal',
    )

    intro_price_clp = models.PositiveIntegerField(
        verbose_name='Precio mensual promocional',
    )

    intro_months = models.PositiveSmallIntegerField(
        default=3,
        verbose_name='Meses promocionales',
    )

    trial_days = models.PositiveSmallIntegerField(
        default=7,
        verbose_name='Días de prueba gratuita',
    )

    professional_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Comisión Profesional (%)',
    )

    space_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Comisión Espacios (%)',
    )

    includes_member_plus = models.BooleanField(
        default=True,
        verbose_name='Incluye Miembro Plus',
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Plan activo',
    )

    display_order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Orden de visualización',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización',
    )

    class Meta:
        verbose_name = 'Plan de suscripción'
        verbose_name_plural = 'Planes de suscripción'
        ordering = ['display_order', 'monthly_price_clp']
        constraints = [
            models.CheckConstraint(
                condition=Q(monthly_price_clp__gt=0),
                name='subscription_plan_monthly_price_gt_zero',
            ),
            models.CheckConstraint(
                condition=Q(intro_price_clp__gt=0),
                name='subscription_plan_intro_price_gt_zero',
            ),
            models.CheckConstraint(
                condition=Q(intro_price_clp__lte=models.F('monthly_price_clp')),
                name='subscription_plan_intro_lte_normal',
            ),
            models.CheckConstraint(
                condition=(
                    Q(professional_commission_rate__isnull=True)
                    | (
                        Q(professional_commission_rate__gte=0)
                        & Q(professional_commission_rate__lte=100)
                    )
                ),
                name='subscription_plan_professional_rate_range',
            ),
            models.CheckConstraint(
                condition=(
                    Q(space_commission_rate__isnull=True)
                    | (
                        Q(space_commission_rate__gte=0)
                        & Q(space_commission_rate__lte=100)
                    )
                ),
                name='subscription_plan_space_rate_range',
            ),
        ]

    def __str__(self):
        return self.name


class SubscriptionAccount(models.Model):
    """
    Estado promocional a nivel de Cuenta Única.

    Evita reiniciar la prueba gratuita o los tres meses promocionales
    creando nuevas suscripciones o cambiando de perfil.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='subscription_account',
        verbose_name='Cuenta',
    )

    trial_used = models.BooleanField(
        default=False,
        verbose_name='Prueba gratuita utilizada',
    )

    intro_months_used = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Meses promocionales utilizados',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización',
    )

    class Meta:
        verbose_name = 'Cuenta de suscripción'
        verbose_name_plural = 'Cuentas de suscripción'

    def __str__(self):
        return f'Suscripción de {self.user}'


class UserSubscription(models.Model):

    class Status(models.TextChoices):
        TRIAL = 'trial', 'Prueba gratuita'
        ACTIVE = 'active', 'Activa'
        PAST_DUE = 'past_due', 'Pago pendiente'
        CANCEL_AT_PERIOD_END = (
            'cancel_at_period_end',
            'Cancela al finalizar el periodo',
        )
        CANCELLED = 'cancelled', 'Cancelada'

    class Provider(models.TextChoices):
        SANDBOX = 'sandbox', 'Sandbox'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='subscriptions',
        verbose_name='Cuenta',
    )

    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name='subscriptions',
        verbose_name='Plan',
    )

    scheduled_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name='scheduled_subscriptions',
        null=True,
        blank=True,
        verbose_name='Próximo plan programado',
    )

    scheduled_plan_effective_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha del cambio programado',
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.TRIAL,
        verbose_name='Estado',
    )

    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.SANDBOX,
        verbose_name='Proveedor',
    )

    provider_subscription_reference = models.CharField(
        max_length=120,
        blank=True,
        verbose_name='Referencia del proveedor',
    )

    started_at = models.DateTimeField(
        verbose_name='Inicio de la suscripción',
    )

    trial_started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Inicio de prueba',
    )

    trial_ends_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fin de prueba',
    )

    current_period_start = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Inicio del periodo actual',
    )

    current_period_end = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fin del periodo actual',
    )

    next_billing_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Próximo cobro',
    )

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de cancelación',
    )

    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de término',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización',
    )

    class Meta:
        verbose_name = 'Suscripción de usuario'
        verbose_name_plural = 'Suscripciones de usuarios'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(
                    status__in=[
                        'trial',
                        'active',
                        'past_due',
                        'cancel_at_period_end',
                    ]
                ),
                name='unique_effective_subscription_per_user',
            )
        ]

    @property
    def is_effective(self):
        return self.status in {
            self.Status.TRIAL,
            self.Status.ACTIVE,
            self.Status.PAST_DUE,
            self.Status.CANCEL_AT_PERIOD_END,
        }

    def professional_commission_rate(self):
        if self.plan.professional_commission_rate is not None:
            return self.plan.professional_commission_rate
        return PROFESSIONAL_BASE_COMMISSION

    def space_commission_rate(self):
        if self.plan.space_commission_rate is not None:
            return self.plan.space_commission_rate
        return SPACE_BASE_COMMISSION

    def clean(self):
        errors = {}

        if self.scheduled_plan_id and not self.scheduled_plan_effective_at:
            errors['scheduled_plan_effective_at'] = (
                'Debes indicar cuándo comienza el cambio de plan programado.'
            )

        if self.status == self.Status.TRIAL:
            if not self.trial_started_at or not self.trial_ends_at:
                errors['status'] = (
                    'Una suscripción en prueba debe registrar inicio y fin de prueba.'
                )

        if (
            self.current_period_start
            and self.current_period_end
            and self.current_period_end <= self.current_period_start
        ):
            errors['current_period_end'] = (
                'El fin del periodo debe ser posterior a su inicio.'
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.user} · {self.plan.name} · {self.get_status_display()}'


class SubscriptionEvent(models.Model):

    class EventType(models.TextChoices):
        TRIAL_STARTED = 'trial_started', 'Prueba iniciada'
        TRIAL_ENDED = 'trial_ended', 'Prueba finalizada'
        ACTIVATED = 'activated', 'Suscripción activada'
        RENEWED = 'renewed', 'Suscripción renovada'
        PLAN_CHANGE_SCHEDULED = (
            'plan_change_scheduled',
            'Cambio de plan programado',
        )
        PLAN_CHANGED = 'plan_changed', 'Plan cambiado'
        CANCELLATION_REQUESTED = (
            'cancellation_requested',
            'Cancelación solicitada',
        )
        CANCELLED = 'cancelled', 'Suscripción cancelada'
        PAYMENT_FAILED = 'payment_failed', 'Cobro fallido'
        REACTIVATED = 'reactivated', 'Suscripción reactivada'

    subscription = models.ForeignKey(
        UserSubscription,
        on_delete=models.PROTECT,
        related_name='events',
        verbose_name='Suscripción',
    )

    event_type = models.CharField(
        max_length=40,
        choices=EventType.choices,
        verbose_name='Evento',
    )

    amount_clp = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Monto asociado',
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Metadatos',
    )

    occurred_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha del evento',
    )

    class Meta:
        verbose_name = 'Evento de suscripción'
        verbose_name_plural = 'Eventos de suscripción'
        ordering = ['-occurred_at']

    def __str__(self):
        return (
            f'{self.subscription.user} · '
            f'{self.get_event_type_display()} · {self.occurred_at}'
        )
