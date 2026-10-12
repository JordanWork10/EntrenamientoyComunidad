import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.locations.models import Commune, Region


class Command(BaseCommand):
    help = 'Carga las comunas oficiales de Chile'

    SOURCES = [
        (
            'https://interoperabilidad.minsal.cl/'
            'fhir/ig/eis/CodeSystem-eis-comunas-cs.json'
        ),
        (
            'https://build.fhir.org/ig/Minsal-CL/eis/'
            'CodeSystem-eis-comunas-cs.json'
        ),
    ]

    def download_data(self):

        last_error = None

        for url in self.SOURCES:

            try:
                request = Request(
                    url,
                    headers={
                        'User-Agent': 'EntrenamientoyComunidadV2/1.0'
                    }
                )

                with urlopen(request, timeout=30) as response:
                    return json.loads(
                        response.read().decode('utf-8')
                    )

            except (
                URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as error:
                last_error = error

        raise CommandError(
            'No fue posible descargar el catálogo de comunas. '
            f'Detalle: {last_error}'
        )

    def handle(self, *args, **options):

        self.stdout.write(
            'Descargando catálogo oficial de comunas...'
        )

        source_data = self.download_data()

        concepts = source_data.get('concept', [])

        if len(concepts) != 346:
            raise CommandError(
                'El catálogo recibido no contiene 346 comunas. '
                f'Se recibieron: {len(concepts)}'
            )

        communes = []

        for concept in concepts:

            raw_code = str(concept['code'])

            # Los códigos de regiones 01 a 09 pueden venir
            # sin el cero inicial. Los normalizamos a 5 dígitos.
            commune_code = raw_code.zfill(5)

            region_code = commune_code[:2]

            communes.append(
                {
                    'code': commune_code,
                    'name': concept['display'],
                    'region_code': region_code,
                }
            )

        communes.sort(
            key=lambda item: item['code']
        )

        data_path = (
            Path(__file__).resolve().parents[2]
            / 'data'
            / 'communes_chile.json'
        )

        with open(
            data_path,
            'w',
            encoding='utf-8'
        ) as file:
            json.dump(
                communes,
                file,
                ensure_ascii=False,
                indent=4
            )

        created_count = 0
        updated_count = 0

        with transaction.atomic():

            for commune_data in communes:

                try:
                    region = Region.objects.get(
                        code=commune_data['region_code']
                    )

                except Region.DoesNotExist:
                    raise CommandError(
                        'No existe la región con código '
                        f"{commune_data['region_code']}."
                    )

                _, created = Commune.objects.update_or_create(
                    code=commune_data['code'],
                    defaults={
                        'name': commune_data['name'],
                        'region': region,
                        'is_active': True,
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                'Comunas cargadas correctamente. '
                f'Creadas: {created_count}. '
                f'Actualizadas: {updated_count}. '
                f'Total: {len(communes)}.'
            )
        )