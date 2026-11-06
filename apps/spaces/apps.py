from django.apps import AppConfig


class SpacesConfig(AppConfig):

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.spaces'

    def ready(self):
        from . import space_notification_receivers_v13209