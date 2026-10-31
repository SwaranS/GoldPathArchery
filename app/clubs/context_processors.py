from django.conf import settings
from .services import is_reviewer


def clubs_navigation(request):
    enabled = getattr(settings, "CLUBS_ENABLED", False)
    return {"clubs_enabled": enabled, "clubs_reviewer": enabled and is_reviewer(request.user)}
