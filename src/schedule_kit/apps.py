from django.apps import AppConfig


class CeleryKitConfig(AppConfig):
    name = "schedule_kit"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Celery Kit"

    def ready(self):
        from .signals import register_signals
        register_signals()
