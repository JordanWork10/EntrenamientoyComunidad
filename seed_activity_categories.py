import os

import django


os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE',
    'config.settings',
)

django.setup()


from django.utils.text import slugify

from apps.activities.models import ActivityCategory


CATEGORIES = [
    'Ciclismo',
    'Running y trote',
    'Fútbol',
    'Entrenamiento funcional',
    'Yoga',
    'Pilates',
    'Baile',
    'Boxeo',
    'Artes marciales',
    'Senderismo',
    'Caminata',
    'Entrenamiento deportivo',
    'Deportes recreativos',
    'Talleres',
    'Movilidad y bienestar',
]


def run():
    created_count = 0
    existing_count = 0

    print()
    print('Cargando categorías de actividades...')
    print()

    for category_name in CATEGORIES:
        category, created = ActivityCategory.objects.get_or_create(
            slug=slugify(category_name),
            defaults={
                'name': category_name,
                'is_active': True,
            },
        )

        if created:
            created_count += 1
            print(f'[CREADA] {category.name}')
        else:
            existing_count += 1
            print(f'[EXISTE] {category.name}')

    print()
    print('Proceso finalizado.')
    print(f'Categorías creadas: {created_count}')
    print(f'Categorías existentes: {existing_count}')
    print(f'Total registrado: {ActivityCategory.objects.count()}')
    print()


if __name__ == '__main__':
    run()