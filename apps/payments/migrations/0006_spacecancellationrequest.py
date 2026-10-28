"""V131.67: revisión auditada para cancelaciones de arriendos pagados."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0005_settlement_settled_by_and_constraint'),
        ('spaces', '0009_spaceamenity_recommended_space_types_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SpaceCancellationRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requested_role', models.CharField(
                    choices=[('member', 'Miembro'), ('provider', 'Proveedor')],
                    max_length=20,
                )),
                ('reason', models.TextField()),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pendiente de revisión'),
                        ('approved', 'Cancelación aprobada'),
                        ('rejected', 'Solicitud rechazada'),
                    ],
                    default='pending',
                    max_length=20,
                )),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_notes', models.TextField(blank=True)),
                ('refund_amount_clp', models.PositiveIntegerField(default=0)),
                ('booking', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='paid_cancellation_requests',
                    to='spaces.spacebooking',
                )),
                ('payment', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='space_cancellation_requests',
                    to='payments.payment',
                )),
                ('requested_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='requested_space_cancellations',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='reviewed_space_cancellations',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('refund', models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='space_cancellation_request',
                    to='payments.refund',
                )),
            ],
            options={
                'verbose_name': 'Solicitud de cancelación de arriendo pagado',
                'verbose_name_plural': 'Solicitudes de cancelación de arriendos pagados',
                'ordering': ['-requested_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='spacecancellationrequest',
            constraint=models.UniqueConstraint(
                condition=models.Q(status='pending'),
                fields=('booking',),
                name='unique_pending_space_cancel',
            ),
        ),
    ]
