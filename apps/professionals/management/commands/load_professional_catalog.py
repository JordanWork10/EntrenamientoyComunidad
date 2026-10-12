from django.core.management.base import BaseCommand
from django.db import transaction

from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalSpecialty,
)


class Command(BaseCommand):
    help = (
        'Carga las categorías y especialidades '
        'profesionales iniciales de la plataforma'
    )

    def handle(self, *args, **options):

        catalog = [
            {
                'name': 'Entrenamiento y Rendimiento',
                'slug': 'entrenamiento-rendimiento',
                'description': (
                    'Preparación física, entrenamiento individual '
                    'y mejora del rendimiento.'
                ),
                'order': 1,
                'specialties': [
                    {
                        'name': 'Entrenador personal',
                        'slug': 'entrenador-personal',
                    },
                    {
                        'name': 'Preparador físico',
                        'slug': 'preparador-fisico',
                    },
                    {
                        'name': 'Entrenamiento funcional',
                        'slug': 'entrenamiento-funcional',
                    },
                    {
                        'name': 'Acondicionamiento físico',
                        'slug': 'acondicionamiento-fisico',
                    },
                    {
                        'name': 'Fuerza y biomecánica',
                        'slug': 'fuerza-biomecanica',
                    },
                ],
            },

            {
                'name': 'Kinesiología y Readaptación',
                'slug': 'kinesiologia-readaptacion',
                'description': (
                    'Rehabilitación, recuperación funcional '
                    'y readaptación física o deportiva.'
                ),
                'order': 2,
                'specialties': [
                    {
                        'name': 'Kinesiología',
                        'slug': 'kinesiologia',
                    },
                    {
                        'name': 'Readaptación deportiva',
                        'slug': 'readaptacion-deportiva',
                    },
                    {
                        'name': 'Rehabilitación musculoesquelética',
                        'slug': 'rehabilitacion-musculoesqueletica',
                    },
                ],
            },

            {
                'name': 'Yoga, Pilates y Movilidad',
                'slug': 'yoga-pilates-movilidad',
                'description': (
                    'Disciplinas orientadas al movimiento, '
                    'movilidad, control corporal y flexibilidad.'
                ),
                'order': 3,
                'specialties': [
                    {
                        'name': 'Yoga',
                        'slug': 'yoga',
                    },
                    {
                        'name': 'Pilates',
                        'slug': 'pilates',
                    },
                    {
                        'name': 'Movilidad y flexibilidad',
                        'slug': 'movilidad-flexibilidad',
                    },
                ],
            },

            {
                'name': 'Danza y Clases Grupales',
                'slug': 'danza-clases-grupales',
                'description': (
                    'Actividades dirigidas, danza, baile '
                    'y entrenamiento colectivo.'
                ),
                'order': 4,
                'specialties': [
                    {
                        'name': 'Danza',
                        'slug': 'danza',
                    },
                    {
                        'name': 'Baile',
                        'slug': 'baile',
                    },
                    {
                        'name': 'Clases grupales',
                        'slug': 'clases-grupales',
                    },
                    {
                        'name': 'Bootcamp',
                        'slug': 'bootcamp',
                    },
                ],
            },

            {
                'name': 'Artes Marciales y Deportes de Combate',
                'slug': 'artes-marciales-combate',
                'description': (
                    'Entrenamiento técnico y físico relacionado '
                    'con artes marciales y deportes de combate.'
                ),
                'order': 5,
                'specialties': [
                    {
                        'name': 'Artes marciales',
                        'slug': 'artes-marciales',
                    },
                    {
                        'name': 'Boxeo',
                        'slug': 'boxeo',
                    },
                    {
                        'name': 'Kickboxing',
                        'slug': 'kickboxing',
                    },
                ],
            },
        ]

        categories_created = 0
        categories_updated = 0

        specialties_created = 0
        specialties_updated = 0

        with transaction.atomic():

            for category_data in catalog:

                category, created = (
                    ProfessionalCategory.objects.update_or_create(
                        slug=category_data['slug'],
                        defaults={
                            'name': category_data['name'],
                            'description': (
                                category_data['description']
                            ),
                            'display_order': (
                                category_data['order']
                            ),
                            'is_active': True,
                        }
                    )
                )

                if created:
                    categories_created += 1
                else:
                    categories_updated += 1

                for order, specialty_data in enumerate(
                    category_data['specialties'],
                    start=1
                ):

                    _, specialty_created = (
                        ProfessionalSpecialty.objects.update_or_create(
                            slug=specialty_data['slug'],
                            defaults={
                                'category': category,
                                'name': specialty_data['name'],
                                'display_order': order,
                                'is_active': True,
                            }
                        )
                    )

                    if specialty_created:
                        specialties_created += 1
                    else:
                        specialties_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                'Catálogo profesional cargado correctamente.\n'
                f'Categorías creadas: {categories_created}.\n'
                f'Categorías actualizadas: {categories_updated}.\n'
                f'Especialidades creadas: {specialties_created}.\n'
                f'Especialidades actualizadas: {specialties_updated}.'
            )
        )