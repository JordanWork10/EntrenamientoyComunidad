"""Copiar como apps/payments/apps.py (V131.84)."""

from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.payments'
    verbose_name = 'Pagos'

    def ready(self):
        # Modelo de lectura de los eventos almacenados por triggers.
        # Importación única durante la inicialización de Django.
        from . import economic_audit_models_v13184  # noqa: F401
