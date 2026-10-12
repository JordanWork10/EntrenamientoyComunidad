document.addEventListener('DOMContentLoaded', () => {

    const regionSelect = document.getElementById('id_region');
    const communeSelect = document.getElementById('id_commune');

    if (!regionSelect || !communeSelect) {
        return;
    }

    const initialCommune = communeSelect.value;


    async function loadCommunes(regionId, selectedCommune = '') {

        communeSelect.innerHTML =
            '<option value="">Cargando comunas...</option>';

        communeSelect.disabled = true;


        if (!regionId) {

            communeSelect.innerHTML =
                '<option value="">Selecciona primero una región</option>';

            return;
        }


        try {

            const response = await fetch(
                `/cuenta/comunas/?region=${regionId}`
            );

            if (!response.ok) {
                throw new Error('No fue posible cargar las comunas.');
            }

            const data = await response.json();


            communeSelect.innerHTML =
                '<option value="">Selecciona una comuna</option>';


            data.communes.forEach((commune) => {

                const option = document.createElement('option');

                option.value = commune.id;
                option.textContent = commune.name;

                if (
                    selectedCommune &&
                    String(commune.id) === String(selectedCommune)
                ) {
                    option.selected = true;
                }

                communeSelect.appendChild(option);

            });


            communeSelect.disabled = false;

        } catch (error) {

            communeSelect.innerHTML =
                '<option value="">Error al cargar comunas</option>';

            console.error(error);

        }

    }


    regionSelect.addEventListener('change', () => {

        loadCommunes(regionSelect.value);

    });


    if (regionSelect.value) {

        loadCommunes(
            regionSelect.value,
            initialCommune
        );

    } else {

        communeSelect.innerHTML =
            '<option value="">Selecciona primero una región</option>';

        communeSelect.disabled = true;

    }

});