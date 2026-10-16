import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.activities.models import Activity, ActivityRegistration


class Settlement(models.Model):

    class ScopeType(models.TextChoices):
        ACTIVITY = 'activity', 'Actividad profesional'
        PROFESSIONAL_DAY = 'professional_day', 'Jornada profesional'
        SPACE_DAY = 'space_day', 'Jornada de espacio'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente de liquidación'
        ELIGIBLE = 'eligible', 'Elegible para liquidación'
        ON_HOLD = 'on_hold', 'En revisión'
        SETTLED = 'settled', 'Liquidado'
        FAILED = 'failed', 'Fallido'

    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name='Identificador público',
    )

    beneficiary = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payment_settlements',
        verbose_name='Beneficiario',
    )

    scope_type = models.CharField(
        max_length=30,
        choices=ScopeType.choices,
        default=ScopeType.ACTIVITY,
        verbose_name='Tipo de agrupación',
    )

    activity = models.ForeignKey(
        Activity,
        on_delete=models.PROTECT,
        related_name='settlements',
        null=True,
        blank=True,
        verbose_name='Actividad asociada',
    )

    reference_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='Fecha de referencia',
    )

    gross_amount_clp = models.PositiveIntegerField(
        default=0,
        verbose_name='Monto bruto',
    )

    refunded_amount_clp = models.PositiveIntegerField(
        default=0,
        verbose_name='Monto reembolsado',
    )

    commission_base_clp = models.PositiveIntegerField(
        default=0,
        verbose_name='Base para comisión',
    )

    commission_amount_clp = models.PositiveIntegerField(
        default=0,
        verbose_name='Comisión de plataforma',
    )

    net_amount_clp = models.PositiveIntegerField(
        default=0,
        verbose_name='Monto neto',
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Estado de liquidación',
    )

    eligible_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha elegible para liquidar',
    )

    settled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de liquidación',
    )

    hold_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Motivo de retención o revisión',
    )

    provider_reference = models.CharField(
        max_length=120,
        blank=True,
        verbose_name='Referencia del proveedor',
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
        verbose_name = 'Liquidación'
        verbose_name_plural = 'Liquidaciones'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['scope_type', 'activity'],
                condition=Q(activity__isnull=False),
                name='unique_settlement_per_activity_scope',
            ),
            models.CheckConstraint(
                condition=Q(refunded_amount_clp__lte=F('gross_amount_clp')),
                name='settlement_refund_lte_gross',
            ),
            models.CheckConstraint(
                condition=Q(commission_amount_clp__lte=F('commission_base_clp')),
                name='settlement_commission_lte_base',
            ),
            models.CheckConstraint(
                condition=Q(net_amount_clp__lte=F('commission_base_clp')),
                name='settlement_net_lte_base',
            ),
        ]

    def clean(self):
        errors = {}

        if self.scope_type == self.ScopeType.ACTIVITY and not self.activity_id:
            errors['activity'] = (
                'Una liquidación de actividad debe estar asociada a una actividad.'
            )

        if (
            self.activity_id
            and self.beneficiary_id
            and self.activity.organizer_id != self.beneficiary_id
        ):
            errors['beneficiary'] = (
                'El beneficiario debe ser el organizador de la actividad.'
            )

        if self.refunded_amount_clp > self.gross_amount_clp:
            errors['refunded_amount_clp'] = (
                'El monto reembolsado no puede superar el monto bruto.'
            )

        if self.commission_amount_clp > self.commission_base_clp:
            errors['commission_amount_clp'] = (
                'La comisión no puede superar la base de comisión.'
            )

        if self.net_amount_clp > self.commission_base_clp:
            errors['net_amount_clp'] = (
                'El monto neto no puede superar la base de comisión.'
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f'{self.get_scope_type_display()} · {self.beneficiary} · '
            f'{self.net_amount_clp} CLP · {self.get_status_display()}'
        )


class Payment(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        APPROVED = 'approved', 'Aprobado'
        FAILED = 'failed', 'Fallido'
        CANCELLED = 'cancelled', 'Cancelado'
        PARTIALLY_REFUNDED = 'partially_refunded', 'Reembolso parcial'
        REFUNDED = 'refunded', 'Reembolsado'

    class Provider(models.TextChoices):
        SANDBOX = 'sandbox', 'Sandbox'

    class EconomicScope(models.TextChoices):
        PROFESSIONAL_ACTIVITY = (
            'professional_activity',
            'Actividad profesional',
        )
        PROFESSIONAL_SERVICE = (
            'professional_service',
            'Servicio profesional',
        )
        SPACE_BOOKING = (
            'space_booking',
            'Reserva de espacio',
        )

    class SettlementStatus(models.TextChoices):
        PENDING = 'pending', 'Pendiente de liquidación'
        ELIGIBLE = 'eligible', 'Elegible para liquidación'
        ON_HOLD = 'on_hold', 'En revisión'
        SETTLED = 'settled', 'Liquidado'

    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name='Identificador público',
    )

    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name='Miembro que paga',
    )

    activity = models.ForeignKey(
        Activity,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name='Actividad',
    )

    registration = models.OneToOneField(
        ActivityRegistration,
        on_delete=models.PROTECT,
        related_name='payment',
        null=True,
        blank=True,
        verbose_name='Inscripción confirmada',
    )

    settlement = models.ForeignKey(
        Settlement,
        on_delete=models.PROTECT,
        related_name='payments',
        null=True,
        blank=True,
        verbose_name='Liquidación asociada',
    )

    economic_scope = models.CharField(
        max_length=30,
        choices=EconomicScope.choices,
        default=EconomicScope.PROFESSIONAL_ACTIVITY,
        verbose_name='Origen económico',
    )

    amount_clp = models.PositiveIntegerField(
        verbose_name='Monto pagado',
    )

    currency = models.CharField(
        max_length=3,
        default='CLP',
        verbose_name='Moneda',
    )

    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.SANDBOX,
        verbose_name='Proveedor',
    )

    provider_reference = models.CharField(
        max_length=120,
        blank=True,
        verbose_name='Referencia del proveedor',
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Estado',
    )

    failure_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Motivo de fallo o cancelación',
    )

    # Snapshot histórico del plan y de la comisión aplicados a la operación.
    plan_code_snapshot = models.CharField(
        max_length=40,
        default='professional_base',
        verbose_name='Plan aplicado',
    )

    commission_rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('12.00'),
        verbose_name='Porcentaje de comisión aplicado',
    )

    refunded_amount_clp = models.PositiveIntegerField(
        default=0,
        verbose_name='Monto reembolsado acumulado',
    )

    commission_base_clp = models.PositiveIntegerField(
        default=0,
        verbose_name='Base vigente para comisión',
    )

    commission_amount_clp = models.PositiveIntegerField(
        default=0,
        verbose_name='Comisión vigente de plataforma',
    )

    net_amount_clp = models.PositiveIntegerField(
        default=0,
        verbose_name='Monto neto vigente del prestador',
    )

    policy_version = models.CharField(
        max_length=50,
        default='LEGACY_PRE_POLICY',
        verbose_name='Versión de política',
    )

    policy_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de aceptación de política',
    )

    settlement_status = models.CharField(
        max_length=20,
        choices=SettlementStatus.choices,
        default=SettlementStatus.PENDING,
        verbose_name='Estado económico',
    )

    settlement_eligible_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha elegible para liquidar',
    )

    settled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de liquidación',
    )

    settlement_hold_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Motivo de retención de liquidación',
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de aprobación',
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
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_clp__gt=0),
                name='payment_amount_clp_gt_zero',
            ),
            models.CheckConstraint(
                condition=Q(refunded_amount_clp__lte=F('amount_clp')),
                name='payment_refunded_lte_amount',
            ),
            models.CheckConstraint(
                condition=Q(commission_rate_percent__gte=0)
                & Q(commission_rate_percent__lte=100),
                name='payment_commission_rate_range',
            ),
            models.CheckConstraint(
                condition=Q(commission_amount_clp__lte=F('commission_base_clp')),
                name='payment_commission_lte_base',
            ),
            models.CheckConstraint(
                condition=Q(net_amount_clp__lte=F('commission_base_clp')),
                name='payment_net_lte_base',
            ),
            models.UniqueConstraint(
                fields=['payer', 'activity'],
                condition=Q(
                    status__in=[
                        'approved',
                        'partially_refunded',
                    ]
                ),
                name='unique_active_paid_payment_per_member_activity',
            ),
        ]

    @staticmethod
    def _percentage_amount(amount_clp, rate_percent):
        value = (
            Decimal(amount_clp)
            * Decimal(rate_percent)
            / Decimal('100')
        )
        return int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    @property
    def refundable_amount_clp(self):
        return max(self.amount_clp - self.refunded_amount_clp, 0)

    def recalculate_economic_amounts(self):
        self.commission_base_clp = self.refundable_amount_clp
        self.commission_amount_clp = self._percentage_amount(
            self.commission_base_clp,
            self.commission_rate_percent,
        )
        self.net_amount_clp = max(
            self.commission_base_clp - self.commission_amount_clp,
            0,
        )

    def clean(self):
        errors = {}

        if self.activity_id:
            if self.activity.activity_type != Activity.ActivityType.PROFESSIONAL:
                errors['activity'] = (
                    'Los pagos se aplican únicamente a actividades profesionales.'
                )

            if self.activity.price <= 0:
                errors['activity'] = (
                    'Esta actividad no requiere un pago.'
                )

        if (
            self.activity_id
            and self.payer_id
            and self.activity.organizer_id == self.payer_id
        ):
            errors['payer'] = (
                'El organizador no paga por participar en su propia actividad.'
            )

        if self.refunded_amount_clp > self.amount_clp:
            errors['refunded_amount_clp'] = (
                'El total reembolsado no puede superar el pago original.'
            )

        if self.commission_rate_percent < 0 or self.commission_rate_percent > 100:
            errors['commission_rate_percent'] = (
                'La comisión debe estar entre 0% y 100%.'
            )

        if self.commission_amount_clp > self.commission_base_clp:
            errors['commission_amount_clp'] = (
                'La comisión no puede superar la base de comisión.'
            )

        if self.net_amount_clp > self.commission_base_clp:
            errors['net_amount_clp'] = (
                'El monto neto no puede superar la base de comisión.'
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f'{self.payer} · {self.activity} · '
            f'{self.amount_clp} {self.currency} · {self.get_status_display()}'
        )


class Refund(models.Model):

    class RefundType(models.TextChoices):
        FULL = 'full', 'Total'
        PARTIAL = 'partial', 'Parcial'

    class Reason(models.TextChoices):
        MEMBER_CANCELLATION = 'member_cancellation', 'Cancelación del Miembro'
        PROFESSIONAL_CANCELLATION = (
            'professional_cancellation',
            'Cancelación del Profesional',
        )
        PROVIDER_CANCELLATION = (
            'provider_cancellation',
            'Cancelación del Proveedor',
        )
        SERVICE_NOT_PROVIDED = (
            'service_not_provided',
            'Servicio no realizado',
        )
        PLATFORM_ISSUE = 'platform_issue', 'Problema de plataforma'
        EXCEPTIONAL = 'exceptional', 'Caso excepcional'
        OTHER = 'other', 'Otro'

    class Status(models.TextChoices):
        REQUESTED = 'requested', 'Solicitado'
        APPROVED = 'approved', 'Aprobado'
        REJECTED = 'rejected', 'Rechazado'
        PROCESSED = 'processed', 'Procesado'
        FAILED = 'failed', 'Fallido'

    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name='Identificador público',
    )

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name='refunds',
        verbose_name='Pago original',
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='requested_refunds',
        null=True,
        blank=True,
        verbose_name='Solicitado por',
    )

    refund_type = models.CharField(
        max_length=20,
        choices=RefundType.choices,
        verbose_name='Tipo de reembolso',
    )

    reason = models.CharField(
        max_length=40,
        choices=Reason.choices,
        verbose_name='Motivo',
    )

    amount_clp = models.PositiveIntegerField(
        verbose_name='Monto a reembolsar',
    )

    policy_percentage_snapshot = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Porcentaje de política aplicado',
    )

    hours_before_service_snapshot = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Horas de anticipación registradas',
    )

    policy_version_snapshot = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Política aplicada',
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
        verbose_name='Estado',
    )

    notes = models.TextField(
        blank=True,
        verbose_name='Observaciones',
    )

    provider_reference = models.CharField(
        max_length=120,
        blank=True,
        verbose_name='Referencia del proveedor',
    )

    requested_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de solicitud',
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de resolución',
    )

    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de procesamiento',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización',
    )

    class Meta:
        verbose_name = 'Reembolso'
        verbose_name_plural = 'Reembolsos'
        ordering = ['-requested_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_clp__gt=0),
                name='refund_amount_gt_zero',
            ),
            models.CheckConstraint(
                condition=(
                    Q(policy_percentage_snapshot__isnull=True)
                    | (
                        Q(policy_percentage_snapshot__gte=0)
                        & Q(policy_percentage_snapshot__lte=100)
                    )
                ),
                name='refund_policy_percentage_range',
            ),
        ]

    def clean(self):
        errors = {}

        if self.payment_id:
            already_processed = (
                Refund.objects
                .filter(
                    payment_id=self.payment_id,
                    status=Refund.Status.PROCESSED,
                )
                .exclude(pk=self.pk)
                .aggregate(total=models.Sum('amount_clp'))
                .get('total')
                or 0
            )

            available = max(self.payment.amount_clp - already_processed, 0)

            if self.amount_clp > available:
                errors['amount_clp'] = (
                    'El reembolso no puede superar el saldo reembolsable del pago.'
                )

        if (
            self.policy_percentage_snapshot is not None
            and (
                self.policy_percentage_snapshot < 0
                or self.policy_percentage_snapshot > 100
            )
        ):
            errors['policy_percentage_snapshot'] = (
                'El porcentaje de política debe estar entre 0% y 100%.'
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f'{self.payment.public_id} · {self.amount_clp} CLP · '
            f'{self.get_status_display()}'
        )
