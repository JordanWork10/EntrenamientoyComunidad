"""V131.60: responsable de cierre para liquidaciones de espacios.

El campo es opcional porque las liquidaciones históricas no conservan
la identidad del operador. No se inventa ni se rellena retrospectivamente.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0004_settlement_space_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='settlement',
            name='settled_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='authorized_settlements',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Administrador que autorizó el cierre',
            ),
        ),
        migrations.AddConstraint(
            model_name='settlement',
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(scope_type='space_day', status='settled')
                    | models.Q(settled_by__isnull=False)
                ),
                name='settlement_space_close_requires_actor',
            ),
        ),
    ]
