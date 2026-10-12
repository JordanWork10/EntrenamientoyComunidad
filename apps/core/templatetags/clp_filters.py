from django import template


register = template.Library()


@register.filter
def clp(value):
    """
    Formatea un valor entero como moneda chilena.

    Ejemplo:
    25000 -> $25.000 CLP
    """

    if value in (
        None,
        '',
    ):
        return ''

    try:
        amount = int(value)

    except (
        TypeError,
        ValueError,
    ):
        return value

    formatted_amount = (
        f'{amount:,}'
        .replace(
            ',',
            '.'
        )
    )

    return (
        f'${formatted_amount} CLP'
    )
