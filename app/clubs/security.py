"""HTTP reviewer gate. Social-provider login alone is never treated as MFA."""
import math
import time
from urllib.parse import urlencode

from allauth.account.authentication import get_authentication_records
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from . import services


def has_recent_mfa(request):
    if not services.is_reviewer(request.user):
        return False
    now = time.time()
    for record in reversed(get_authentication_records(request)):
        at = record.get("at")
        if (record.get("method") == "mfa" and isinstance(at, (int, float)) and math.isfinite(at)
                and 0 <= now - at < settings.CLUB_REVIEW_MFA_MAX_AGE
                and Authenticator.objects.filter(pk=record.get("id"), user=request.user,
                    type=record.get("type")).exists()):
            return True
    return False


def review_session_redirect(request):
    services.require_reviewer(request.user)
    if has_recent_mfa(request):
        return None
    from .middleware import security_event
    security_event(request, "review.mfa_required")
    enrolled = Authenticator.objects.filter(user=request.user, type="totp").exists()
    url = reverse("mfa_reauthenticate" if enrolled else "mfa_index")
    # Do not stash private evidence uploads or automatically replay decisions.
    return redirect(url + "?" + urlencode({"next": request.get_full_path()}))
