from django.apps import AppConfig


class ClubsConfig(AppConfig):
    name = "clubs"

    def ready(self):
        from . import checks  # noqa: F401
