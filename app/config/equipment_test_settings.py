"""Disposable localhost PostgreSQL tests only; never inherits production DB settings."""
from .test_settings import *  # noqa: F403
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "equipment_test",
    "USER": "equipment_test", "PASSWORD": "equipment_test_local_only", "HOST": "127.0.0.1", "PORT": "55439"}}
