"""V131.84 — modelo de eventos económicos almacenados en PostgreSQL.

Copiar como: apps/payments/economic_audit_models_v13184.py

La escritura de eventos es responsabilidad exclusiva de los triggers
de la migración 0009. No exponer create/update/delete por vistas.
"""

from django.core.exceptions import ValidationError
from django.db import models


class EconomicAuditEventQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        raise ValidationError('Solo el trigger de PostgreSQL puede crear eventos.')

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError('Los eventos de auditoría no se pueden modificar.')

    def update(self, **kwargs):
        raise ValidationError('Los eventos de auditoría no se pueden modificar.')

    def delete(self):
        raise ValidationError('Los eventos de auditoría no se pueden eliminar.')


class EconomicAuditEvent(models.Model):
    class Source(models.TextChoices):
        PAYMENT = 'payment', 'Pago'
        REFUND = 'refund', 'Reembolso'
        SETTLEMENT = 'settlement', 'Liquidación'

    class Action(models.TextChoices):
        CREATED = 'created', 'Creación'
        UPDATED = 'updated', 'Actualización'
        DELETED = 'deleted', 'Eliminación'

    source_type = models.CharField(max_length=16, choices=Source.choices)
    source_pk = models.BigIntegerField()
    source_public_id = models.UUIDField()
    action = models.CharField(max_length=12, choices=Action.choices)
    before_state = models.JSONField(default=dict)
    after_state = models.JSONField(default=dict)
    changed_fields = models.JSONField(default=list)
    actor_identifier = models.CharField(max_length=120, blank=True)
    actor_source = models.CharField(max_length=30, blank=True)
    occurred_at = models.DateTimeField()

    objects = EconomicAuditEventQuerySet.as_manager()

    class Meta:
        db_table = 'payments_economic_audit_event'
        verbose_name = 'Evento de auditoría económica'
        verbose_name_plural = 'Eventos de auditoría económica'
        ordering = ('-occurred_at', '-id')
        indexes = [
            models.Index(
                fields=('source_type', 'source_public_id', '-occurred_at'),
                name='pay_audit_source_13184_idx',
            ),
            models.Index(
                fields=('-occurred_at',),
                name='pay_audit_time_13184_idx',
            ),
        ]

    def save(self, *args, **kwargs):
        raise ValidationError('Solo el trigger de PostgreSQL puede crear eventos.')

    def delete(self, *args, **kwargs):
        raise ValidationError('Los eventos de auditoría no se pueden eliminar.')

    def __str__(self):
        return f'{self.get_action_display()} de {self.get_source_type_display()} #{self.source_pk}'
