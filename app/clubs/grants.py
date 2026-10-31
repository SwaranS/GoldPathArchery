"""Live category checks shared by HTML, JSON and durable training workers."""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.models import AthleteProfile
from accounts.permissions import can, eligible_actor
from . import memberships, services
from .models import Club, ClubMembership, ClubRoleAssignment, ClubDataGrant

SCOPES = {
    "profile": "Basic profile (display name and disciplines)",
    "training": "Training schedules and draft summaries (read)",
    "training_edit": "Request new training-plan drafts",
    "scoring": "Scoring sessions and arrow values (read)",
    "equipment": "Equipment inventory (read)",
    "sight_marks": "Sight marks (read)",
    "programme_progress": "Programme progress (self-reported session counts only)",
}


def enabled():
    return bool(settings.CLUBS_ENABLED and getattr(settings, "CLUB_MEMBERSHIPS_ENABLED", False)
                and getattr(settings, "CLUB_DATA_SHARING_ENABLED", False))


def athlete_is_member(athlete, club):
    query = Q(athlete=athlete)
    if athlete.account_id:
        query |= Q(user_id=athlete.account_id)
    return ClubMembership.objects.filter(query, club=club, active=True).exists()


def valid(grant, actor, scope):
    if scope == "programme_progress" and not getattr(settings, "CLUB_PROGRAMMES_ENABLED", False):
        return False
    now = timezone.now()
    if (not enabled() or scope not in SCOPES or scope not in grant.scopes or
            grant.revoked_at or not grant.starts_at <= now < grant.expires_at or
            not eligible_actor(actor, write=True) or grant.athlete.closed_at or
            not grant.approved_by or not can(grant.approved_by, grant.athlete, "manage_grants") or
            not memberships.live_club(grant.club) or not athlete_is_member(grant.athlete, grant.club)):
        return False
    if grant.grantee_id:
        return (grant.grantee_id == actor.pk and memberships.has_role(actor, grant.club, {"coach"})
            and ClubRoleAssignment.objects.filter(membership__club=grant.club, membership__user=actor,
                membership__active=True, role="coach", revoked_at__isnull=True,
                accepted_at__lte=grant.created_at).exists())
    return memberships.has_role(actor, grant.club, {grant.role})


def allows(actor, athlete, scope, *, club_id=None):
    if not enabled() or scope not in SCOPES or not eligible_actor(actor, write=True):
        return False
    candidates = ClubDataGrant.objects.filter(athlete=athlete, revoked_at__isnull=True).filter(
        Q(grantee=actor) | Q(grantee__isnull=True)).select_related("club", "athlete", "approved_by")
    if club_id is not None:
        candidates = candidates.filter(club_id=club_id)
    return any(valid(grant, actor, scope) for grant in candidates)


def require(actor, athlete, scope):
    if not allows(actor, athlete, scope):
        raise Http404


def owner(actor, athlete_id):
    if not enabled():
        raise Http404
    athlete = get_object_or_404(AthleteProfile, pk=athlete_id)
    if not can(actor, athlete, "manage_grants"):
        raise Http404
    return athlete


@transaction.atomic
def issue(actor, athlete_id, *, club_id, grantee_id=None, role="", scopes, purpose, starts_at, expires_at):
    # Serialize against membership termination first, then guardian/home changes.
    club = get_object_or_404(Club.objects.select_for_update(), pk=club_id)
    AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    athlete = owner(actor, athlete_id)
    if not memberships.live_club(club) or not athlete_is_member(athlete, club):
        raise ValidationError("Choose an active verified club membership.")
    if not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) or s not in SCOPES for s in scopes) or len(scopes) != len(set(scopes)):
        raise ValidationError("Choose valid, distinct data categories.")
    if "programme_progress" in scopes and not getattr(settings, "CLUB_PROGRAMMES_ENABLED", False):
        raise ValidationError("Programme progress sharing is not enabled.")
    if "training_edit" in scopes and "training" not in scopes:
        raise ValidationError("Training draft generation also requires training read consent.")
    if not purpose.strip() or len(purpose) > 300:
        raise ValidationError("Record a purpose of at most 300 characters.")
    if not starts_at or not expires_at or expires_at <= max(starts_at, timezone.now()) or expires_at - starts_at > timedelta(days=365):
        raise ValidationError("Choose a future expiry within 365 days of the start.")
    if bool(grantee_id) == bool(role):
        raise ValidationError("Choose one named coach or one club role.")
    from django.contrib.auth import get_user_model
    grantee = get_object_or_404(get_user_model(), pk=grantee_id) if grantee_id else None
    if grantee and not memberships.has_role(grantee, club, {"coach"}):
        raise ValidationError("The named recipient must be a current club coach.")
    if role and role not in memberships.ROLES:
        raise ValidationError("Choose a predefined club role.")
    grant = ClubDataGrant.objects.create(athlete=athlete, club=club, grantee=grantee, role=role,
        approved_by=actor, scopes=scopes, purpose=purpose.strip(), starts_at=starts_at, expires_at=expires_at)
    services.audit(actor, None, "grant.issued", grant.pk, club=club)
    return grant


@transaction.atomic
def revoke(actor, athlete_id, grant_id, version):
    owner(actor, athlete_id)
    AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    owner(actor, athlete_id)
    grant = get_object_or_404(ClubDataGrant.objects.select_for_update(), pk=grant_id, athlete_id=athlete_id)
    services.check_version(grant, version)
    if grant.revoked_at:
        raise ValidationError("This grant has already been revoked.")
    grant.revoked_at = timezone.now()
    grant.version += 1
    grant.save(update_fields=["revoked_at", "version"])
    services.audit(actor, None, "grant.revoked", grant.pk, club=grant.club)


def shared_athletes(actor, scope):
    if not enabled() or not eligible_actor(actor, write=True):
        return AthleteProfile.objects.none()
    ids = {g.athlete_id for g in ClubDataGrant.objects.filter(revoked_at__isnull=True).filter(
        Q(grantee=actor) | Q(grantee__isnull=True)).select_related("athlete", "club", "approved_by") if valid(g, actor, scope)}
    return AthleteProfile.objects.filter(pk__in=ids).order_by("display_name", "pk")


def shared_payload(actor, athlete_id, scope):
    athlete = get_object_or_404(AthleteProfile, pk=athlete_id)
    require(actor, athlete, scope)
    if scope == "programme_progress":
        from .programmes import shared_progress
        return shared_progress(actor, athlete_id)
    # Never serialize whole models, input contexts, equipment snapshots, notes,
    # account emails, birth dates or media URLs into this category response.
    if scope == "profile":
        return {"display_name": athlete.display_name, "disciplines": athlete.selected_disciplines}
    if scope == "training":
        from training.models import GeneratedPlan
        return {"plans": [{"id": str(plan.pk), "created_at": plan.created_at,
            "roadmap": training_schedule(plan.roadmap)}
            for plan in GeneratedPlan.objects.filter(athlete=athlete, status="ready").order_by("-created_at")[:100]]}
    if scope == "scoring":
        from scoring.models import ScoringSession
        sessions = ScoringSession.objects.filter(athlete=athlete, deleted_at__isnull=True).order_by("-started_at")[:100]
        return {"sessions": [{"id": str(session.pk), "started_at": session.started_at,
            "status": session.status, "arrows": list(session.shots.order_by("position").values("position", "symbol", "points", "is_x"))} for session in sessions]}
    if scope == "equipment":
        from scoring.models import Equipment, EquipmentComponent, BowConfiguration
        components = []
        for item in EquipmentComponent.objects.filter(owner=athlete).prefetch_related("revisions").order_by("pk")[:1000]:
            revision = item.revisions.first()
            components.append({"id": item.pk, "category": item.category, "status": item.status,
                "name": revision.name if revision else "", "manufacturer": revision.manufacturer if revision else "",
                "model": revision.model if revision else ""})
        configurations = []
        for item in BowConfiguration.objects.filter(owner=athlete).prefetch_related("revisions").order_by("pk")[:1000]:
            revision = item.revisions.first()
            configurations.append({"id": item.pk, "active": item.active, "name": revision.name if revision else ""})
        return {"items": list(Equipment.objects.filter(athlete=athlete).order_by("pk").values("id", "name", "kind", "division", "active")[:1000]),
            "components": components, "configurations": configurations}
    if scope == "sight_marks":
        from scoring.models import SightMark
        return {"marks": list(SightMark.objects.filter(athlete=athlete).order_by("pk").values("id", "distance", "distance_unit", "mark")[:1000])}
    raise Http404


def training_schedule(roadmap):
    """Prescribed sessions only; omit notes, pain flags and linked private IDs."""
    def select(value, keys):
        return {key: value[key] for key in keys if key in value} if isinstance(value, dict) else {}

    def children(value, key, limit):
        result = value.get(key, []) if isinstance(value, dict) else []
        return [item for item in result[:limit] if isinstance(item, dict)] if isinstance(result, list) else []

    result = select(roadmap, ("primary_archetype", "secondary_archetype", "start_date", "target_date", "status",
        "weekly_planned_arrows", "weekly_actual_arrows", "pillar_breakdown_pct"))
    weeks = []
    for week in children(roadmap, "microcycles", 60):
        row = select(week, ("week_number", "target_arrows", "is_deload_week"))
        sessions = []
        for session in children(week, "sessions", 14):
            entry = select(session, ("scheduled_date", "max_distance_m", "duration_mins", "status"))
            blocks = []
            for block in children(session, "blocks", 100):
                detail = select(block, ("block_order", "block_type", "prescribed_arrows", "distance_m", "target_face_cm"))
                detail["drill"] = select(block.get("drill"), ("title", "instructions"))
                blocks.append(detail)
            entry["blocks"] = blocks
            sessions.append(entry)
        row["sessions"] = sessions
        weeks.append(row)
    result["microcycles"] = weeks
    return result
