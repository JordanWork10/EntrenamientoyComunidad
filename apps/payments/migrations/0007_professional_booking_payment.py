from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('bookings', '0006_bookingincidentprofessionalresponse'),
        ('payments', '0006_spacecancellationrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='professional_booking',
            field=models.ForeignKey(
                to='bookings.booking',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='payments',
                null=True,
                blank=True,
                verbose_name='Reserva individual de servicio profesional',
            ),
        ),
        migrations.RemoveConstraint(
            model_name='payment',
            name='payment_exactly_one_origin',
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        activity__isnull=False,
                        space_booking__isnull=True,
                        professional_booking__isnull=True,
                    )
                    | Q(
                        activity__isnull=True,
                        space_booking__isnull=False,
                        professional_booking__isnull=True,
                    )
                    | Q(
                        activity__isnull=True,
                        space_booking__isnull=True,
                        professional_booking__isnull=False,
                    )
                ),
                name='payment_exactly_one_origin',
            ),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.UniqueConstraint(
                fields=['professional_booking'],
                condition=Q(
                    professional_booking__isnull=False,
                    status__in=['approved', 'partially_refunded'],
                ),
                name='unique_active_paid_prof_booking',
            ),
        ),
    ]
