"""Local fast tests only. Production continues to require PostgreSQL."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "local-tests-only-not-a-production-secret")
for name in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
    os.environ.setdefault(name, "unused-in-sqlite-tests")

from .settings import *  # noqa: F403,E402

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
