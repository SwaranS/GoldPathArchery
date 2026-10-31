"""Fail closed for real onboarding; disabled routes preserve legacy deployments."""
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.checks import Error, register


@register()
def production_readiness(app_configs, **kwargs):
    if not settings.CLUBS_ENABLED or not getattr(settings, "CLUBS_PRODUCTION", False):
        return []
    errors = []
    try:
        if not settings.MFA_ENCRYPTION_KEYS:
            raise ValueError
        for key in settings.MFA_ENCRYPTION_KEYS:
            Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        errors.append(Error("Configure a valid MFA_ENCRYPTION_KEYS key ring before enabling clubs.", id="clubs.E001"))
    if settings.CLUB_EVIDENCE_BACKEND != "azure" or not settings.CLUB_EVIDENCE_AZURE_CONNECTION_STRING or not settings.CLUB_EVIDENCE_AZURE_CONTAINER:
        errors.append(Error("Configure private Azure evidence storage before enabling production clubs.", id="clubs.E002"))
    backend = settings.CACHES["default"]["BACKEND"]
    if backend not in ("django.core.cache.backends.db.DatabaseCache", "django.core.cache.backends.redis.RedisCache"):
        errors.append(Error("Configure a shared cache for MFA replay/rate limiting before enabling production clubs.", id="clubs.E003"))
    return errors


@register()
def facility_photo_readiness(app_configs, **kwargs):
    if not (settings.CLUBS_ENABLED and getattr(settings, "CLUB_FACILITIES_ENABLED", False)
            and getattr(settings, "CLUBS_PRODUCTION", False)):
        return []
    backend = getattr(settings, "CLUB_FACILITY_PHOTO_BACKEND", "disabled")
    if backend == "disabled":
        return []  # Venues and calendars can operate without photo uploads.
    if (backend != "azure" or not getattr(settings, "CLUB_FACILITY_PHOTO_AZURE_CONNECTION_STRING", "")
            or not getattr(settings, "CLUB_FACILITY_PHOTO_AZURE_CONTAINER", "")):
        return [Error("Configure private Azure facility photo storage or disable facility photo uploads in production.", id="clubs.E004")]
    return []
