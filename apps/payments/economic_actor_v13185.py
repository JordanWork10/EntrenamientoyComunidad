"""V131.85 — contexto de auditoría para POST económicos autenticados.

Copiar como: apps/payments/economic_actor_v13185.py

Se usa únicamente al declarar rutas de escritura en payments/urls.py.
SET LOCAL permanece dentro de una transacción PostgreSQL, por lo que no se
filtra la identidad de un usuario hacia otras peticiones ni conexiones.
"""

from functools import wraps

from django.db import connection, transaction
from django.urls import path as django_path


# Son rutas que pueden escribir pagos, reembolsos o liquidaciones.
# Las rutas GET de consulta/recibo no se envuelven, conservando sus callbacks.
ECONOMIC_MUTATION_NAMES = frozenset({
    'space_cancellation_resolve',
    'space_settlement_prepare',
    'space_settlement_close',
    'professional_day_settlement_prepare',
    'professional_day_settlement_close',
    'professional_day_settlement_release',
    'checkout',
    'cancel_paid_activity',
    'sandbox_make_activity_settlement_eligible',
    'sandbox_settle_activity',
    'professional_booking_checkout',
    'professional_booking_sandbox_approve',
    'professional_booking_sandbox_reject',
    'professional_booking_cancel_attempt',
    'space_checkout',
    'space_sandbox_approve',
    'space_sandbox_reject',
    'space_cancel',
    'sandbox_approve',
    'sandbox_reject',
    'cancel',
})


def attribute_economic_post(view_func):
    """Asocia el usuario autenticado al trigger durante una sola petición POST.

    No reemplaza las validaciones de permisos, CSRF ni reglas de negocio de la
    vista original. Si la vista revierte, el evento también se revierte.
    """
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        user = getattr(request, 'user', None)
        if (
            request.method != 'POST'
            or connection.vendor != 'postgresql'
            or not user
            or not user.is_authenticated
            or not user.is_active
        ):
            return view_func(request, *args, **kwargs)

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('payments.audit_actor_id', true)"
                )
                previous_actor = cursor.fetchone()[0] or ''
                cursor.execute(
                    "SELECT set_config('payments.audit_actor_id', %s, true)",
                    [str(user.pk)],
                )

            try:
                return view_func(request, *args, **kwargs)
            finally:
                # Restaurar también cuando TestCase/ATOMIC_REQUESTS mantienen
                # abierta una transacción externa después de la respuesta.
                # Si el bloque SQL quedó inválido por un error, el rollback
                # del atomic revierte automáticamente el SET LOCAL.
                if not connection.needs_rollback:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT set_config('payments.audit_actor_id', %s, true)",
                            [previous_actor],
                        )

    return wrapped


def payment_audit_path(route, view, kwargs=None, name=None):
    """Misma interfaz que django.urls.path, audita solo rutas mutantes."""
    if name in ECONOMIC_MUTATION_NAMES:
        view = attribute_economic_post(view)
    return django_path(route, view, kwargs=kwargs, name=name)
