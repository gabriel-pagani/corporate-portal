from django.apps import AppConfig


class AppConfig(AppConfig):
    name = 'app'
    verbose_name = 'Sistema'

    def ready(self):
        from . import signals  # noqa: F401
