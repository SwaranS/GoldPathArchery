from django.conf import settings
from .services import is_reviewer


def clubs_navigation(request):
    enabled = getattr(settings, "CLUBS_ENABLED", False)
    return {"clubs_enabled": enabled, "clubs_reviewer": enabled and is_reviewer(request.user),
            "club_programmes_enabled": enabled and getattr(settings, "CLUB_MEMBERSHIPS_ENABLED", False) and getattr(settings, "CLUB_PROGRAMMES_ENABLED", False),
            "club_facilities_enabled": enabled and getattr(settings, "CLUB_FACILITIES_ENABLED", False),
            "club_data_sharing_enabled": enabled and getattr(settings, "CLUB_MEMBERSHIPS_ENABLED", False) and getattr(settings, "CLUB_DATA_SHARING_ENABLED", False),
            "club_memberships_enabled": enabled and getattr(settings, "CLUB_MEMBERSHIPS_ENABLED", False)}
