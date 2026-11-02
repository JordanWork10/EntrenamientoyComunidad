"""V132.00 — destino: apps/professionals/apps.py (archivo COMPLETO)."""

from django.apps import AppConfig


class ProfessionalsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.professionals'
    verbose_name = 'Profesionales'

    def ready(self):
        # Registro del modelo adicional de videos sin reemplazar el enorme
        # apps/professionals/models.py que ya utiliza la aplicación.
        from . import video_models_v13200  # noqa: F401
