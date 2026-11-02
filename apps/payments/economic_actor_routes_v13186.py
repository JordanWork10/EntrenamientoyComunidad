"""V131.86: identificar al responsable en cancelaciones fuera de /pagos/.

Destino: apps/payments/economic_actor_routes_v13186.py

En cada archivo de rutas indicado, DESPUES de construir ``urlpatterns``::

    from apps.payments.economic_actor_routes_v13186 import enable_external_economic_audit
    urlpatterns = enable_external_economic_audit(urlpatterns, app_name='bookings')

Cambiar ``bookings`` por ``activities`` o ``spaces`` según corresponda.
No se reemplazan rutas, vistas, validaciones ni HTML existentes.
"""

from django.urls.resolvers import URLPattern

from .economic_actor_v13185 import attribute_economic_post


# Rutas externas que pueden causar cambios en Payment, Refund o Settlement.
# La envoltura V131.85 asocia al operador solo en POST autenticados y en la
# misma transacción de la operación. Los GET conservan su lógica original.
EXTERNAL_ECONOMIC_ROUTE_NAMES = {
    'bookings': frozenset({
        'cancel_my_booking',
        'professional_cancel',
    }),
    'activities': frozenset({
        'cancel_professional',
    }),
    'spaces': frozenset({
        'cancel_my_booking',
        'provider_cancel_booking',
    }),
}


def enable_external_economic_audit(urlpatterns, *, app_name):
    """Envuelve solo las rutas externas que pueden modificar dinero.

    Mantiene las rutas, nombres, conversores, valores por defecto y el orden.
    Es idempotente: llamar dos veces no duplica la transacción de atribución.

    Se limita a rutas HTTP; no identifica procesos automáticos sin petición.
    No convierte una operación no autorizada en autorizada: la vista sigue
    controlando permisos, CSRF, validaciones y políticas de reembolso.
    """
    if app_name not in EXTERNAL_ECONOMIC_ROUTE_NAMES:
        raise ValueError(f'Módulo económico externo desconocido: {app_name}')

    selected_names = EXTERNAL_ECONOMIC_ROUTE_NAMES[app_name]
    found = set()

    for urlpattern in urlpatterns:
        if not isinstance(urlpattern, URLPattern):
            continue
        if urlpattern.name not in selected_names:
            continue

        found.add(urlpattern.name)
        original = urlpattern.callback
        if getattr(original, '_economic_actor_v13186', False):
            continue

        wrapped = attribute_economic_post(original)
        wrapped._economic_actor_v13186 = True
        urlpattern.callback = wrapped

    missing = selected_names - found
    if missing:
        raise RuntimeError(
            f'Faltan rutas económicas de {app_name}: '
            + ', '.join(sorted(missing))
        )

    return urlpatterns
