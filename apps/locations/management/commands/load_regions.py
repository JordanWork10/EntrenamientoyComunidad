from django.core.management.base import BaseCommand

from apps.locations.models import Region


class Command(BaseCommand):
    help = 'Carga las regiones de Chile'

    def handle(self, *args, **options):

        regions = [
            ('01', 'Región de Tarapacá'),
            ('02', 'Región de Antofagasta'),
            ('03', 'Región de Atacama'),
            ('04', 'Región de Coquimbo'),
            ('05', 'Región de Valparaíso'),
            (
                '06',
                "Región del Libertador General Bernardo O'Higgins"
            ),
            ('07', 'Región del Maule'),
            ('08', 'Región del Biobío'),
            ('09', 'Región de La Araucanía'),
            ('10', 'Región de Los Lagos'),
            (
                '11',
                'Región de Aysén del General Carlos Ibáñez del Campo'
            ),
            (
                '12',
                'Región de Magallanes y de la Antártica Chilena'
            ),
            ('13', 'Región Metropolitana de Santiago'),
            ('14', 'Región de Los Ríos'),
            ('15', 'Región de Arica y Parinacota'),
            ('16', 'Región de Ñuble'),
        ]

        created_count = 0
        updated_count = 0

        for code, name in regions:

            _, created = Region.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'is_active': True,
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Regiones cargadas correctamente. '
                f'Creadas: {created_count}. '
                f'Actualizadas: {updated_count}.'
            )
        )