import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.activities.models import Activity, ActivityRegistration


class Payment(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        APPROVED = 'approved', 'Aprobado'
        FAILED = 'failed', 'Fallido'
        CANCELLED = 'cancelled', 'Cancelado'
        REFUNDED = 'refunded', 'Reembolsado'

    class Provider(models.TextChoices):
        SANDBOX = 'sandbox', 'Sandbox'

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
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Estado',
    )

    failure_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Motivo de fallo o cancelación',
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
                condition=models.Q(amount_clp__gt=0),
                name='payment_amount_clp_gt_zero',
            ),
            models.UniqueConstraint(
                fields=['payer', 'activity'],
                condition=models.Q(status='approved'),
                name='unique_approved_payment_per_member_activity',
            ),
        ]

    def clean(self):
        errors = {}

        if self.activity_id:
            if (
                self.activity.activity_type
                != Activity.ActivityType.PROFESSIONAL
            ):
                errors['activity'] = (
                    'Los pagos V1 solo se aplican a actividades profesionales.'
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

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f'{self.payer} · {self.activity} · '
            f'{self.amount_clp} {self.currency} · {self.get_status_display()}'
        )
