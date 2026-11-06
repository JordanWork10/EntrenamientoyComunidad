from django.apps import AppConfig


class BookingsConfig(AppConfig):

    default_auto_field = 'django.db.models.BigAutoField'

    name = 'apps.bookings'

    verbose_name = 'Reservas'

    def ready(self):
        """
        Registra las señales de notificaciones persistentes.

        No ejecuta consultas ni modifica datos durante el
        inicio de Django.
        """

        from . import notification_receivers_v13209  # noqa: F401