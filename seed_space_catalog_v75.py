from django.db import transaction
from apps.spaces.models import SpaceAmenity, SpaceEquipment, SpaceType
import unicodedata


def normalize(value):
    value = (value or '').strip().lower()
    value = ''.join(
        char
        for char in unicodedata.normalize('NFD', value)
        if unicodedata.category(char) != 'Mn'
    )
    return value


def matching_space_types(keywords):
    matches = []
    for space_type in SpaceType.objects.filter(is_active=True):
        haystack = f"{normalize(space_type.name)} {normalize(space_type.slug)}"
        if any(normalize(keyword) in haystack for keyword in keywords):
            matches.append(space_type)
    return matches


def ensure_catalog_item(model, name, slug, display_order):
    item = model.objects.filter(name__iexact=name).first()
    if item is None:
        item = model.objects.filter(slug=slug).first()

    if item is None:
        item = model.objects.create(
            name=name,
            slug=slug,
            display_order=display_order,
            is_active=True,
        )
    else:
        changed = []
        if item.name != name:
            item.name = name
            changed.append('name')
        if not item.is_active:
            item.is_active = True
            changed.append('is_active')
        if changed:
            item.save(update_fields=changed + ['updated_at'])

    return item


EQUIPMENT_SPECS = [
    ('Espejos', 'espejos', 10, ['gimnasio', 'sala', 'estudio', 'academia', 'danza']),
    ('Mats', 'mats', 20, ['gimnasio', 'sala', 'estudio', 'academia', 'yoga', 'pilates']),
    ('Tatami', 'tatami', 30, ['sala', 'estudio', 'academia', 'artes marciales']),
    ('Pesas', 'pesas', 40, ['gimnasio']),
    ('Sistema de sonido', 'sistema-de-sonido', 50, ['gimnasio', 'sala', 'estudio', 'academia', 'danza']),
    ('Piso de madera', 'piso-de-madera', 60, ['sala', 'estudio', 'academia', 'danza']),
    ('Ventilación', 'ventilacion', 70, ['gimnasio', 'sala', 'estudio', 'academia']),
    ('Arcos', 'arcos', 110, ['cancha']),
    ('Mallas', 'mallas', 120, ['cancha']),
    ('Iluminación deportiva', 'iluminacion-deportiva', 130, ['cancha']),
    ('Red deportiva', 'red-deportiva', 140, ['cancha']),
    ('Balones', 'balones', 150, ['cancha']),
    ('Marcador', 'marcador', 160, ['cancha']),
    ('Gradas', 'gradas', 170, ['cancha']),
]

AMENITY_SPECS = [
    ('Duchas', 'duchas', 10, ['gimnasio']),
    ('Camarines', 'camarines', 20, ['gimnasio', 'cancha', 'sala', 'estudio', 'academia']),
    ('Estacionamiento', 'estacionamiento', 30, ['gimnasio', 'cancha']),
    ('Baños', 'banos', 40, ['gimnasio', 'cancha', 'sala', 'estudio', 'academia']),
    ('Agua / bebedero', 'agua-bebedero', 110, ['gimnasio', 'cancha', 'sala', 'estudio', 'academia']),
    ('Accesibilidad universal', 'accesibilidad-universal', 120, ['gimnasio', 'cancha', 'sala', 'estudio', 'academia']),
]


with transaction.atomic():
    for name, slug, order, keywords in EQUIPMENT_SPECS:
        item = ensure_catalog_item(
            SpaceEquipment,
            name,
            slug,
            order,
        )
        item.recommended_space_types.set(
            matching_space_types(keywords)
        )

    for name, slug, order, keywords in AMENITY_SPECS:
        item = ensure_catalog_item(
            SpaceAmenity,
            name,
            slug,
            order,
        )
        item.recommended_space_types.set(
            matching_space_types(keywords)
        )

print('Catálogo V75 actualizado correctamente.')
print('Tipos de espacio activos:', SpaceType.objects.filter(is_active=True).count())
print('Equipamientos activos:', SpaceEquipment.objects.filter(is_active=True).count())
print('Comodidades activas:', SpaceAmenity.objects.filter(is_active=True).count())
