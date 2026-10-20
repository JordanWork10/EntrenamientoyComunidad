# V121 - Confirmación de sesión y evaluación opcional.

from datetime import timedelta

from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
)

from django.db import migrations, models
import django.db.models.deletion

from django.utils import timezone


def backfill_recent_completed(apps, schema_editor):
    """
    Recupera sesiones completadas recientemente
    para permitir su confirmación por el miembro.
    """

    Booking = apps.get_model(
        'bookings',
        'Booking'
    )

    Review = apps.get_model(
        'bookings',
        'BookingSessionReview'
    )

    now = timezone.now()

    completed = Booking.objects.filter(
        status='completed',
        completed_at__gte=now - timedelta(hours=48),
        completed_at__lte=now,
    )

    for booking in completed.iterator():

        Review.objects.get_or_create(
            booking_id=booking.pk,
            defaults={
                'expires_at': (
                    booking.completed_at
                    + timedelta(hours=48)
                )
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        (
            'bookings',
            '0002_alter_booking_status_alter_bookinghistory_action'
        ),
    ]

    operations = [

        migrations.CreateModel(
            name='BookingSessionReview',

            fields=[

                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),

                (
                    'status',
                    models.CharField(
                        max_length=20,
                        default='pending',
                        choices=[
                            (
                                'pending',
                                'Esperando respuesta'
                            ),
                            (
                                'confirmed',
                                'Confirmada por el miembro'
                            ),
                            (
                                'reported',
                                'Problema reportado'
                            ),
                            (
                                'no_response',
                                'Sin respuesta'
                            ),
                        ],
                        verbose_name='Conformidad del miembro',
                    ),
                ),

                (
                    'expires_at',
                    models.DateTimeField(
                        verbose_name='Límite para responder',
                    ),
                ),

                (
                    'responded_at',
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),

                (
                    'issue_reason',
                    models.TextField(
                        blank=True,
                        max_length=1000,
                    ),
                ),

                (
                    'rating',
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(5),
                        ],
                        verbose_name='Evaluación (1 a 5)',
                    ),
                ),

                (
                    'rating_comment',
                    models.CharField(
                        blank=True,
                        max_length=500,
                    ),
                ),

                (
                    'rated_at',
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),

                (
                    'created_at',
                    models.DateTimeField(
                        auto_now_add=True,
                    ),
                ),

                (
                    'updated_at',
                    models.DateTimeField(
                        auto_now=True,
                    ),
                ),

                (
                    'booking',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='session_review',
                        to='bookings.booking',
                        verbose_name='Reserva profesional',
                    ),
                ),

            ],

            options={
                'verbose_name': 'Conformidad de sesión',
                'verbose_name_plural': 'Conformidades de sesiones',
                'ordering': ['-created_at'],
            },
        ),

        migrations.RunPython(
            backfill_recent_completed,
            migrations.RunPython.noop,
        ),

    ]