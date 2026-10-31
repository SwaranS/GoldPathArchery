"""Disposable localhost PostgreSQL only. Never inherits deployment credentials."""
from .test_settings import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "clubs_test",
    "USER": "clubs_test", "PASSWORD": "clubs_test_local_only", "HOST": "127.0.0.1", "PORT": "55440"}}
