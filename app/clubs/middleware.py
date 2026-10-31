"""Safe request correlation and bounded denied-access telemetry, never URL/payload logs."""
from contextvars import ContextVar
import uuid

from django.conf import settings
from django.core.cache import cache

request_correlation = ContextVar("club_request_correlation", default=None)


def security_event(request, action):
    from .models import ClubSecurityEvent
    actor = request.user if request.user.is_authenticated else None
    # Bound repeated probes. No query strings, addresses, tokens, evidence or free text.
    key = f"club-security:{actor.pk if actor else 'anonymous'}:{action}"
    if cache.add(key, True, timeout=60):
        ClubSecurityEvent.objects.create(actor=actor, action=action,
            correlation_id=request_correlation.get() or uuid.uuid4())


class ClubRequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.CLUBS_ENABLED or not request.path.startswith(("/clubs/", "/admin/clubs/")):
            return self.get_response(request)
        correlation_id = uuid.uuid4()
        token = request_correlation.set(correlation_id)
        try:
            response = self.get_response(request)
            if response.status_code in (403, 404):
                security_event(request, "access.denied")
            response["X-Request-ID"] = str(correlation_id)
            return response
        finally:
            request_correlation.reset(token)
