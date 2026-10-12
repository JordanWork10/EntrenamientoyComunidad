from django import forms


class BookingCreateForm(forms.Form):
    """
    Recibe la sesión concreta elegida por el usuario.

    Los campos se mantienen ocultos en la interfaz porque la
    selección proviene de un bloque generado por el sistema.
    De todos modos, el backend vuelve a validar completamente
    fecha y horario antes de crear la reserva.
    """

    session_date = forms.DateField(
        widget=forms.HiddenInput(),
    )

    start_time = forms.TimeField(
        input_formats=[
            '%H:%M',
            '%H:%M:%S',
        ],
        widget=forms.HiddenInput(),
    )

    end_time = forms.TimeField(
        input_formats=[
            '%H:%M',
            '%H:%M:%S',
        ],
        widget=forms.HiddenInput(),
    )
