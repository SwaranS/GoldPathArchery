"""Platform-only directory curation. Decisions use the transactional review UI."""
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from . import services
from .models import Club, KnownClubListing, ClubClaim, ClubAuditEvent, ClubSecurityEvent
from .security import admin_session_redirect, has_recent_mfa


class ReviewerAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return (getattr(settings, "CLUBS_ENABLED", False)
                and services.is_reviewer(request.user))

    def get_model_perms(self, request):
        # Navigation reflects reviewer authorization; page access still requires MFA.
        return {"view": self.has_module_permission(request)}

    def get_urls(self):
        def protect(view):
            @wraps(view)
            def guarded(request, *args, **kwargs):
                if not self.has_module_permission(request):
                    raise PermissionDenied
                challenge = admin_session_redirect(request)
                if challenge is not None:
                    return challenge
                return view(request, *args, **kwargs)
            return self.admin_site.admin_view(guarded)

        urls = super().get_urls()
        for pattern in urls:
            pattern.callback = protect(pattern.callback)
        return urls

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request) and has_recent_mfa(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KnownClubListing)
class ListingAdmin(ReviewerAdmin):
    list_display = ("name", "country", "reviewed_on")
    readonly_fields = ("club", "created_at")

    def has_add_permission(self, request):
        return self.has_view_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        services.audit(request.user, None, "listing.updated" if change else "listing.created", obj.pk, club=obj.club)


@admin.register(Club)
class ClubAdmin(ReviewerAdmin):
    list_display = ("name", "status", "visibility", "verified_at")


@admin.register(ClubClaim)
class ClaimAdmin(ReviewerAdmin):
    list_display = ("name", "state", "created_at", "review_link")

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(state="draft")

    @admin.display(description="Verification")
    def review_link(self, obj):
        return format_html('<a href="{}">Review claim</a>', reverse("clubs:review", args=[obj.pk]))


@admin.register(ClubAuditEvent)
class AuditAdmin(ReviewerAdmin):
    list_display = ("created_at", "action", "actor", "club_id", "target_id")


@admin.register(ClubSecurityEvent)
class SecurityAdmin(ReviewerAdmin):
    list_display = ("created_at", "action", "actor", "correlation_id")
