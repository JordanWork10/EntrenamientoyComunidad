from django.db import migrations


BACKFILL_REASON = (
    'Registro inicial creado al habilitar la trazabilidad '
    'de disponibilidades.'
)


def backfill_availability_history(apps, schema_editor):
    ProfessionalServiceAvailability = apps.get_model(
        'professionals',
        'ProfessionalServiceAvailability',
    )

    ProfessionalServiceAvailabilityHistory = apps.get_model(
        'professionals',
        'ProfessionalServiceAvailabilityHistory',
    )

    for availability in ProfessionalServiceAvailability.objects.all():

        new_data = {
            'weekday': availability.weekday,
            'weekday_display': dict(
                ProfessionalServiceAvailability
                ._meta
                .get_field('weekday')
                .choices
            ).get(
                availability.weekday
            ),
            'start_time': (
                availability.start_time.isoformat()
                if availability.start_time
                else None
            ),
            'end_time': (
                availability.end_time.isoformat()
                if availability.end_time
                else None
            ),
            'valid_from': (
                availability.valid_from.isoformat()
                if availability.valid_from
                else None
            ),
            'valid_until': (
                availability.valid_until.isoformat()
                if availability.valid_until
                else None
            ),
            'is_active': availability.is_active,
        }

        ProfessionalServiceAvailabilityHistory.objects.create(
            availability=availability,
            action='created',
            previous_data={},
            new_data=new_data,
            changed_by=None,
            reason=BACKFILL_REASON,
        )


class Migration(migrations.Migration):

    dependencies = [
        (
            'professionals',
            '0006_professionalserviceavailabilityhistory',
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_availability_history,
            migrations.RunPython.noop,
        ),
    ]