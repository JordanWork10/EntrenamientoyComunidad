document.addEventListener('DOMContentLoaded', () => {

    const categorySelect =
        document.getElementById('id_category');

    const specialtySelect =
        document.getElementById('id_specialty');

    const regionSelect =
        document.getElementById('id_region');

    const communesContainer =
        document.getElementById(
            'coverage-communes-container'
        );


    /* =========================================
       CATEGORÍA → ESPECIALIDAD
    ========================================= */

    async function loadSpecialties(
        categoryId,
        selectedSpecialty = ''
    ) {

        if (!specialtySelect) {
            return;
        }


        specialtySelect.innerHTML =
            '<option value="">Cargando especialidades...</option>';

        specialtySelect.disabled = true;


        if (!categoryId) {

            specialtySelect.innerHTML =
                '<option value="">Selecciona primero una categoría</option>';

            return;
        }


        try {

            const response = await fetch(
                `/profesionales/especialidades/?category=${categoryId}`
            );


            if (!response.ok) {
                throw new Error(
                    'No fue posible cargar las especialidades.'
                );
            }


            const data = await response.json();


            specialtySelect.innerHTML =
                '<option value="">Selecciona una especialidad</option>';


            data.specialties.forEach(
                (specialty) => {

                    const option =
                        document.createElement('option');

                    option.value =
                        specialty.id;

                    option.textContent =
                        specialty.name;


                    if (
                        selectedSpecialty &&
                        String(specialty.id) ===
                        String(selectedSpecialty)
                    ) {
                        option.selected = true;
                    }


                    specialtySelect.appendChild(
                        option
                    );

                }
            );


            specialtySelect.disabled = false;

        } catch (error) {

            specialtySelect.innerHTML =
                '<option value="">Error al cargar especialidades</option>';

            console.error(error);

        }

    }


    if (categorySelect && specialtySelect) {

        const initialSpecialty =
            specialtySelect.value;


        categorySelect.addEventListener(
            'change',
            () => {

                loadSpecialties(
                    categorySelect.value
                );

            }
        );


        if (categorySelect.value) {

            loadSpecialties(
                categorySelect.value,
                initialSpecialty
            );

        } else {

            specialtySelect.innerHTML =
                '<option value="">Selecciona primero una categoría</option>';

            specialtySelect.disabled = true;

        }

    }


    /* =========================================
       REGIÓN → COMUNAS DE COBERTURA
    ========================================= */

    async function loadCoverageCommunes(
        regionId
    ) {

        if (!communesContainer) {
            return;
        }


        communesContainer.innerHTML =
            '<p class="professional-coverage-empty">Cargando comunas...</p>';


        if (!regionId) {

            communesContainer.innerHTML =
                '<p class="professional-coverage-empty">Selecciona primero una región.</p>';

            return;
        }


        try {

            const response = await fetch(
                `/profesionales/comunas-cobertura/?region=${regionId}`
            );


            if (!response.ok) {
                throw new Error(
                    'No fue posible cargar las comunas.'
                );
            }


            const data = await response.json();


            communesContainer.innerHTML = '';


            data.communes.forEach(
                (commune) => {

                    const label =
                        document.createElement('label');

                    label.className =
                        'professional-commune-option';


                    const checkbox =
                        document.createElement('input');

                    checkbox.type = 'checkbox';

                    checkbox.name =
                        'coverage_communes';

                    checkbox.value =
                        commune.id;


                    const text =
                        document.createElement('span');

                    text.textContent =
                        commune.name;


                    label.appendChild(
                        checkbox
                    );

                    label.appendChild(
                        text
                    );

                    communesContainer.appendChild(
                        label
                    );

                }
            );


            if (data.communes.length === 0) {

                communesContainer.innerHTML =
                    '<p class="professional-coverage-empty">No existen comunas disponibles.</p>';

            }

        } catch (error) {

            communesContainer.innerHTML =
                '<p class="professional-coverage-empty">Error al cargar las comunas.</p>';

            console.error(error);

        }

    }


    if (regionSelect) {

        regionSelect.addEventListener(
            'change',
            () => {

                loadCoverageCommunes(
                    regionSelect.value
                );

            }
        );

    }

});