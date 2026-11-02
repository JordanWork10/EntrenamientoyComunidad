"""V131.78: integridad de liquidaciones de jornadas profesionales."""

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0007_professional_booking_payment'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='settlement',
            constraint=models.UniqueConstraint(
                fields=('beneficiary', 'reference_date'),
                condition=Q(scope_type='professional_day'),
                name='unique_settlement_professional_day',
            ),
        ),
        migrations.AddConstraint(
            model_name='settlement',
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(scope_type='professional_day')
                    | (
                        Q(reference_date__isnull=False)
                        & Q(activity__isnull=True)
                        & Q(space__isnull=True)
                    )
                ),
                name='settlement_professional_day_origin',
            ),
        ),
    ]
