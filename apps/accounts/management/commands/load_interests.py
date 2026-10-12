from django.core.management.base import BaseCommand

from apps.accounts.models import PlatformInterest


class Command(BaseCommand):
    help = 'Carga los intereses disponibles en la plataforma'

    def handle(self, *args, **options):

        interests = [
            {
                'name': 'Fuerza y Biomecánica',
                'slug': 'fuerza-biomecanica',
                'description': (
                    'Entrenamiento de fuerza, técnica, '
                    'movimiento y biomecánica.'
                ),
                'display_order': 1,
            },
            {
                'name': 'Kinesiología y Readaptación',
                'slug': 'kinesiologia-readaptacion',
                'description': (
                    'Servicios orientados a recuperación, '
                    'rehabilitación y readaptación física.'
                ),
                'display_order': 2,
            },
            {
                'name': 'Yoga Funcional y Movilidad',
                'slug': 'yoga-movilidad',
                'description': (
                    'Yoga, movilidad, flexibilidad '
                    'y trabajo funcional.'
                ),
                'display_order': 3,
            },
            {
                'name': 'Clases Grupales y Bootcamps',
                'slug': 'clases-grupales-bootcamps',
                'description': (
                    'Actividades colectivas, entrenamiento '
                    'grupal y sesiones tipo bootcamp.'
                ),
                'display_order': 4,
            },
            {
                'name': 'Arriendo de Espacios y Canchas',
                'slug': 'arriendo-espacios-canchas',
                'description': (
                    'Interés en espacios deportivos, '
                    'salas, estudios y canchas.'
                ),
                'display_order': 5,
            },
            {
                'name': 'Preparación Física Específica',
                'slug': 'preparacion-fisica-especifica',
                'description': (
                    'Preparación física orientada a '
                    'objetivos deportivos específicos.'
                ),
                'display_order': 6,
            },
        ]

        created_count = 0
        updated_count = 0

        for interest in interests:

            _, created = PlatformInterest.objects.update_or_create(
                slug=interest['slug'],
                defaults={
                    'name': interest['name'],
                    'description': interest['description'],
                    'display_order': interest['display_order'],
                    'is_active': True,
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                'Intereses cargados correctamente. '
                f'Creados: {created_count}. '
                f'Actualizados: {updated_count}.'
            )
        )