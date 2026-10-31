"""Platform-only directory curation. Decisions use the transactional review UI."""
from django.conf import settings
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from . import services
from .models import Club, KnownClubListing, ClubClaim, ClubAuditEvent, ClubSecurityEvent
from .security import has_recent_mfa


class ReviewerAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return (getattr(settings, "CLUBS_ENABLED", False)
                and services.is_reviewer(request.user) and has_recent_mfa(request))

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

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
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

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
