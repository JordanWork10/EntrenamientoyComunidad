from django.db import migrations


# =====================================================
# V123 - RECUPERAR INCIDENCIAS ANTERIORES
# =====================================================

def recover_reported_incidents(apps, schema_editor):
    """
    Recupera las conformidades que ya tenían
    problemas reportados antes de V123.

    No modifica las reservas ni los reportes
    originales y evita duplicar incidencias.
    """

    BookingSessionReview = apps.get_model(
        'bookings',
        'BookingSessionReview'
    )

    BookingSessionIncident = apps.get_model(
        'bookings',
        'BookingSessionIncident'
    )

    database = schema_editor.connection.alias

    # Buscar los problemas que ya estaban registrados
    reported_reviews = BookingSessionReview.objects.using(
        database
    ).filter(
        status='reported'
    )

    # Crear una incidencia por cada reporte
    for review in reported_reviews.iterator():

        BookingSessionIncident.objects.using(
            database
        ).get_or_create(
            review_id=review.pk,
            defaults={
                'status': 'open',
            }
        )


# =====================================================
# MIGRACIÓN
# =====================================================

class Migration(migrations.Migration):

    dependencies = [
        (
            'bookings',
            '0004_bookingsessionincident'
        ),
    ]

    operations = [

        migrations.RunPython(
            recover_reported_incidents,
            migrations.RunPython.noop,
        ),

    ]