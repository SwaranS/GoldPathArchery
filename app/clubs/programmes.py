"""Consent-first group programmes, copied source versions and personal draft jobs."""
from copy import deepcopy
from datetime import date, time, timedelta
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, F
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.models import AthleteProfile, GuardianLink
from accounts.permissions import can, eligible_actor, accessible_athletes
from . import services, memberships, grants
from .models import (Club, ClubMembership, ClubRoleAssignment, ClubTrainingGroup,
    ClubTrainingGroupMember, ClubProgramme, ClubProgrammeRevision, ClubProgrammeAssignment,
    ClubAssignmentPlan, ClubProgrammeProgress)


def enabled():
    return bool(settings.CLUBS_ENABLED and getattr(settings, "CLUB_MEMBERSHIPS_ENABLED", False)
        and getattr(settings, "CLUB_PROGRAMMES_ENABLED", False))


def require_enabled():
    if not enabled():
        raise Http404


class ProgrammeConflict(ValidationError):
    pass


def version_check(obj, version):
    if type(version) is not int or obj.version != version:
        raise ProgrammeConflict("This record changed. Reload the current page before submitting.")


def role_live(role_id, club):
    role = ClubRoleAssignment.objects.filter(pk=role_id, membership__club=club, membership__active=True,
        membership__user__is_active=True, role="coach", revoked_at__isnull=True,
        accepted_at__lte=timezone.now()).select_related("membership__user").first()
    return role if role and eligible_actor(role.membership.user, write=True) and memberships.live_club(club) else None


def group_live(group):
    return bool(group.active and role_live(group.coach_role_id, group.club))


def is_coach(actor, group):
    return bool(eligible_actor(actor, write=True) and group_live(group)
        and group.coach_role.membership.user_id == actor.pk)


def control_group(actor, group_id, *, lock=False, coach_only=False):
    require_enabled()
    group = get_object_or_404(ClubTrainingGroup.objects.select_related("club", "coach_role__membership"), pk=group_id)
    if lock:
        Club.objects.select_for_update(of=("self",)).get(pk=group.club_id)
        group = ClubTrainingGroup.objects.select_for_update(of=("self",)).select_related("club", "coach_role__membership").get(pk=group.pk)
    if not (is_coach(actor, group) or (not coach_only and services.can_manage(actor, group.club))):
        raise Http404
    return group


def member_athlete(member):
    if member.athlete_id:
        return AthleteProfile.objects.filter(pk=member.athlete_id).first()
    return AthleteProfile.objects.filter(account_id=member.user_id).first() if member.user_id else None


def owner_read(actor, athlete):
    if not athlete or not eligible_actor(actor) or athlete.closed_at:
        return False
    if athlete.account_id == actor.pk:
        return can(actor, athlete, "view")
    return (GuardianLink.objects.filter(athlete=athlete, parent=actor, revoked_at__isnull=True,
        access__in=["view", "edit"]).exists() and can(actor, athlete, "view"))


def owns_member(actor, member, *, write=False):
    athlete = member_athlete(member)
    if athlete:
        return can(actor, athlete, "manage_grants") if write or athlete.account_id != actor.pk else owner_read(actor, athlete)
    return bool(member.user_id == actor.pk and eligible_actor(actor, write=write))


def owner_subjects(actor):
    if not eligible_actor(actor):
        return []
    return [a for a in accessible_athletes(actor) if owner_read(actor, a)]


def own_group_members(actor):
    require_enabled()
    if not eligible_actor(actor):
        return ClubTrainingGroupMember.objects.none()
    ids = [a.pk for a in owner_subjects(actor)]
    return ClubTrainingGroupMember.objects.filter(Q(membership__user=actor) | Q(membership__athlete_id__in=ids)
        | Q(membership__user__athlete_profile__pk__in=ids)).select_related("group__club", "membership__athlete", "membership__user").distinct()


def own_assignments(actor):
    require_enabled()
    return ClubProgrammeAssignment.objects.filter(athlete_id__in=[a.pk for a in owner_subjects(actor)]).select_related(
        "athlete", "revision__programme__group__club", "group_member__membership").order_by("-created_at")


def assignment_for_owner(actor, assignment_id, *, write=False):
    require_enabled()
    assignment = get_object_or_404(ClubProgrammeAssignment.objects.select_related("athlete", "revision__programme__group__club", "group_member__membership"), pk=assignment_id)
    if not (can(actor, assignment.athlete, "manage_grants") if write else owner_read(actor, assignment.athlete)):
        raise Http404
    return assignment


def group_for_reader(actor, group_id):
    require_enabled()
    group = get_object_or_404(ClubTrainingGroup.objects.select_related("club", "coach_role__membership"), pk=group_id)
    if services.can_manage(actor, group.club) or is_coach(actor, group):
        return group
    if group_live(group) and any(m.group_id == group.pk and m.state == "active" and m.membership.active
            and owns_member(actor, m.membership) for m in own_group_members(actor)):
        return group
    raise Http404


def groups_for(actor):
    require_enabled()
    if not eligible_actor(actor):
        return []
    own = {m.group_id for m in own_group_members(actor) if m.state == "active" and m.membership.active and owns_member(actor, m.membership)}
    candidates = ClubTrainingGroup.objects.filter(club__status="active", club__verified_at__isnull=False).select_related("club", "coach_role__membership").order_by("name", "pk")
    return [g for g in candidates if services.can_manage(actor, g.club) or is_coach(actor, g) or (g.pk in own and group_live(g))]


@transaction.atomic
def save_group(actor, club_id, data, *, group_id=None, version=None):
    require_enabled()
    club = get_object_or_404(Club.objects.select_for_update(of=("self",)), pk=club_id)
    admin = services.can_manage(actor, club)
    if set(data) != {"name", "description", "discipline", "coach_role", "active"}:
        raise ValidationError("Provide only the group settings shown in the form.")
    group = get_object_or_404(ClubTrainingGroup.objects.select_for_update(of=("self",)), pk=group_id, club=club) if group_id else ClubTrainingGroup(club=club)
    if not admin and (not memberships.has_role(actor, club, {"coach"})
            or data["coach_role"].membership.user_id != actor.pk
            or (group_id and (not is_coach(actor, group) or data["coach_role"].pk != group.coach_role_id))):
        raise Http404
    role = role_live(data["coach_role"].pk, club)
    archiving_existing = group_id and not data["active"] and data["coach_role"].pk == group.coach_role_id
    if not role and not archiving_existing:
        raise ValidationError("Choose a current accepted coach role in this club.")
    if group_id:
        version_check(group, version)
        group.version += 1
    for key, value in data.items():
        setattr(group, key, value)
    group.full_clean()
    group.save()
    services.audit(actor, None, "programme.group.updated" if group_id else "programme.group.created", group.pk, club=club)
    return group


@transaction.atomic
def invite_group(actor, group_id, membership_id):
    group = control_group(actor, group_id, lock=True)
    if not group_live(group):
        raise ValidationError("This group is not currently active with an authorized coach.")
    member = get_object_or_404(ClubMembership, pk=membership_id, club=group.club, active=True)
    current = ClubTrainingGroupMember.objects.filter(group=group, membership=member).first()
    if current and (current.state == "active" or (current.state == "invited" and current.expires_at > timezone.now())):
        raise ValidationError("This membership is already active or invited.")
    if current:
        current.version += 1
    else:
        current = ClubTrainingGroupMember(group=group, membership=member)
    current.state, current.invited_by, current.invited_at = "invited", actor, timezone.now()
    current.expires_at, current.decided_at = timezone.now()+timedelta(days=14), None
    current.save()
    services.audit(actor, None, "programme.group.invited", current.pk, club=group.club)
    return current


@transaction.atomic
def respond_group(actor, member_id, accept, version):
    require_enabled()
    member = get_object_or_404(ClubTrainingGroupMember.objects.select_related("group__club", "membership__athlete"), pk=member_id)
    Club.objects.select_for_update(of=("self",)).get(pk=member.group.club_id)
    member = ClubTrainingGroupMember.objects.select_for_update(of=("self",)).select_related("group__club", "membership__athlete").get(pk=member.pk)
    if not owns_member(actor, member.membership, write=True):
        raise Http404
    version_check(member, version)
    if member.state != "invited" or member.expires_at <= timezone.now():
        raise ValidationError("This group invitation is no longer pending.")
    if accept and (not member.membership.active or not group_live(member.group)):
        raise ValidationError("This group invitation is no longer authorized.")
    member.state, member.decided_at = ("active" if accept else "declined"), timezone.now()
    member.version += 1
    member.save()
    services.audit(actor, None, "programme.group." + member.state, member.pk, club=member.group.club)
    return member


@transaction.atomic
def leave_group(actor, member_id, version, *, remove=False):
    require_enabled()
    member = get_object_or_404(ClubTrainingGroupMember.objects.select_related("group__club", "membership__athlete"), pk=member_id)
    Club.objects.select_for_update(of=("self",)).get(pk=member.group.club_id)
    if remove:
        control_group(actor, member.group_id)
    elif not owns_member(actor, member.membership, write=True):
        raise Http404
    member = ClubTrainingGroupMember.objects.select_for_update(of=("self",)).get(pk=member.pk)
    version_check(member, version)
    if member.state not in {"invited", "active"}:
        raise ValidationError("This group membership has already ended.")
    member.state = "removed" if remove else "left"
    member.decided_at, member.version = timezone.now(), member.version+1
    member.save()
    member.assignments.filter(state="offered").update(state="cancelled", version=F("version")+1)
    services.audit(actor, None, "programme.group." + member.state, member.pk, club=member.group.club)


def validate_template(data, group):
    from app.schemas.training_plan import PlanArchetype, RoundFormat
    required = {"title", "instructions", "start_date", "duration_days", "archetype", "round_format", "sessions"}
    if set(data) != required or not isinstance(data["title"], str) or not data["title"].strip() or len(data["title"]) > 160:
        raise ValidationError("Provide a programme title and all template fields.")
    if not isinstance(data["instructions"], str) or len(data["instructions"]) > 4000:
        raise ValidationError("Programme instructions must be at most 4000 characters.")
    if type(data["duration_days"]) is not int or not 1 <= data["duration_days"] <= 365:
        raise ValidationError("Choose a duration from 1 to 365 days.")
    try:
        start = date.fromisoformat(str(data["start_date"]))
        end = start + timedelta(days=data["duration_days"])
        PlanArchetype(data["archetype"])
        RoundFormat(data["round_format"])
    except (ValueError, TypeError, OverflowError):
        raise ValidationError("Choose valid programme dates, archetype and round format.") from None
    sessions = data["sessions"]
    if not isinstance(sessions, list) or not 1 <= len(sessions) <= 14:
        raise ValidationError("Provide 1–14 weekly group sessions.")
    for session in sessions:
        if not isinstance(session, dict) or set(session) != {"weekday", "start_time", "duration_mins", "description"}:
            raise ValidationError("Each session needs weekday, start_time, duration_mins and description.")
        if type(session["weekday"]) is not int or not 0 <= session["weekday"] <= 6 or type(session["duration_mins"]) is not int or not 1 <= session["duration_mins"] <= 480:
            raise ValidationError("Session weekdays must be 0–6 and durations 1–480 minutes.")
        try:
            parsed = time.fromisoformat(session["start_time"])
            if parsed.tzinfo:
                raise ValueError
        except (ValueError, TypeError):
            raise ValidationError("Group session times must be local clock times.") from None
        if not isinstance(session["description"], str) or not session["description"].strip() or len(session["description"]) > 2000:
            raise ValidationError("Each group session description needs 1–2000 characters.")
    return {**deepcopy(data), "start_date": start.isoformat(), "target_date": end.isoformat(), "discipline": group.discipline,
            "timezone": group.club.timezone, "group": group.name, "club": group.club.name}


@transaction.atomic
def save_template(actor, group_id, data, *, programme_id=None, version=None):
    group = control_group(actor, group_id, lock=True, coach_only=True)
    snapshot = validate_template(data, group)
    programme = get_object_or_404(ClubProgramme.objects.select_for_update(of=("self",)), pk=programme_id, group=group, owner_role=group.coach_role) if programme_id else ClubProgramme(group=group, owner_role=group.coach_role)
    if programme_id:
        version_check(programme, version)
        if not programme.active:
            raise ValidationError("Archived programmes cannot be edited.")
        programme.version += 1
    programme.name = snapshot["title"]
    programme.save()
    latest = programme.revisions.order_by("-number").first()
    revision = ClubProgrammeRevision.objects.create(programme=programme, number=(latest.number+1 if latest else 1), snapshot=snapshot)
    services.audit(actor, None, "programme.revision.created", revision.pk, club=group.club)
    return programme


@transaction.atomic
def publish(actor, programme_id, version):
    programme = get_object_or_404(ClubProgramme.objects.select_related("group__club"), pk=programme_id)
    group = control_group(actor, programme.group_id, lock=True, coach_only=True)
    programme = ClubProgramme.objects.select_for_update(of=("self",)).get(pk=programme.pk)
    version_check(programme, version)
    if not programme.active or programme.owner_role_id != group.coach_role_id:
        raise ValidationError("This programme is not under the current coach.")
    revision = programme.revisions.order_by("-number").first()
    if not revision or revision.number == programme.published_revision:
        raise ValidationError("No unpublished revision is available.")
    programme.published_revision, programme.version = revision.number, programme.version+1
    programme.save()
    services.audit(actor, None, "programme.published", revision.pk, club=group.club)
    return programme


@transaction.atomic
def archive(actor, programme_id, version):
    programme = get_object_or_404(ClubProgramme.objects.select_related("group__club"), pk=programme_id)
    group = control_group(actor, programme.group_id, lock=True)
    programme = ClubProgramme.objects.select_for_update(of=("self",)).get(pk=programme.pk)
    version_check(programme, version)
    programme.active, programme.version = False, programme.version+1
    programme.save()
    ClubProgrammeAssignment.objects.filter(revision__programme=programme, state="offered").update(state="cancelled", version=F("version")+1)
    services.audit(actor, None, "programme.archived", programme.pk, club=group.club)


def source_active(assignment):
    programme, member = assignment.revision.programme, assignment.group_member
    group = programme.group
    return bool(enabled() and programme.active and programme.published_revision >= assignment.revision.number
        and programme.owner_role_id == group.coach_role_id and group_live(group)
        and group.discipline == assignment.revision.snapshot["discipline"]
        and member.group_id == group.pk and member.state == "active" and member.membership.active
        and member.version == assignment.group_member_version and not assignment.athlete.closed_at
        and assignment.revision.snapshot["discipline"] in assignment.athlete.selected_disciplines
        and assignment.athlete.pk == getattr(member_athlete(member.membership), "pk", None))


@transaction.atomic
def offer(actor, programme_id, group_member_id, version):
    programme = get_object_or_404(ClubProgramme.objects.select_related("group__club"), pk=programme_id)
    group = control_group(actor, programme.group_id, lock=True, coach_only=True)
    programme = ClubProgramme.objects.select_for_update(of=("self",)).get(pk=programme.pk)
    version_check(programme, version)
    member = get_object_or_404(ClubTrainingGroupMember.objects.select_related("membership"), pk=group_member_id, group=group, state="active", membership__active=True)
    athlete = member_athlete(member.membership)
    if (not programme.active or programme.owner_role_id != group.coach_role_id or not programme.published_revision
            or not athlete or athlete.closed_at or group.discipline not in athlete.selected_disciplines):
        raise ValidationError("Choose an eligible athlete in this active group and a published programme.")
    revision = programme.revisions.get(number=programme.published_revision)
    if revision.snapshot["discipline"] != group.discipline:
        raise ValidationError("Publish a revised template for this group's current discipline before offering it.")
    expired = ClubProgrammeAssignment.objects.filter(revision=revision, group_member=member,
        group_member_version=member.version, state="offered", expires_at__lte=timezone.now())
    for old_offer in expired:
        old_offer.state, old_offer.version = "cancelled", old_offer.version+1
        old_offer.save(update_fields=["state", "version"])
        services.audit(actor, None, "programme.offer.expired", old_offer.pk, club=group.club)
    if ClubProgrammeAssignment.objects.filter(revision=revision, group_member=member, group_member_version=member.version,
            state__in=["offered", "accepted"]).exists():
        raise ValidationError("This group member already has a pending or accepted assignment for this revision.")
    assignment = ClubProgrammeAssignment.objects.create(revision=revision, group_member=member,
        athlete=athlete, group_member_version=member.version, offered_by=actor, expires_at=timezone.now()+timedelta(days=14))
    services.audit(actor, None, "programme.offered", assignment.pk, club=group.club)
    return assignment


def copy_plan(actor, assignment, payload, private_note):
    from app.schemas.training_plan import GeneratePlanRequest
    from training.models import GeneratedPlan
    from pydantic import ValidationError as SchemaError
    payload = deepcopy(payload)
    if not isinstance(payload.get("baseline"), dict):
        raise ValidationError("Provide an individual baseline before accepting.")
    # The accepting athlete/guardian supplies their own baseline and availability.
    # Only division is bound to the consented group, never template arrow volume.
    payload["athlete_id"] = str(assignment.athlete_id)
    payload.setdefault("baseline", {})["bow_division"] = assignment.revision.snapshot["discipline"]
    try:
        payload = GeneratePlanRequest.model_validate(payload).model_dump(mode="json")
    except SchemaError:
        raise ValidationError("Review the individual training inputs; the request is not valid.") from None
    if not isinstance(private_note, str) or len(private_note) > 1000:
        raise ValidationError("The private customization note must be at most 1000 characters.")
    number = assignment.current_plan_number+1
    payload["club_programme_assignment"] = str(assignment.pk)
    payload["club_assignment_version"] = number
    job = GeneratedPlan.objects.create(athlete=assignment.athlete, requested_by=actor, inputs=payload, status="queued")
    ClubAssignmentPlan.objects.create(assignment=assignment, plan=job, number=number, actor=actor, private_note=private_note)
    assignment.current_plan_number = number
    return job


@transaction.atomic
def respond_assignment(actor, assignment_id, decision, version, *, payload=None, private_note=""):
    assignment = assignment_for_owner(actor, assignment_id, write=True)
    Club.objects.select_for_update(of=("self",)).get(pk=assignment.revision.programme.group.club_id)
    AthleteProfile.objects.select_for_update(of=("self",)).get(pk=assignment.athlete_id)
    assignment = assignment_for_owner(actor, assignment_id, write=True)
    assignment = ClubProgrammeAssignment.objects.select_for_update(of=("self",)).select_related("revision__programme__group__club", "group_member__membership", "athlete").get(pk=assignment.pk)
    version_check(assignment, version)
    if decision in {"accept", "decline"}:
        if assignment.state != "offered" or assignment.expires_at <= timezone.now():
            raise ValidationError("This programme offer is no longer pending.")
    elif decision in {"customize", "withdraw"}:
        if assignment.state != "accepted":
            raise ValidationError("Only an accepted assignment can be customized or withdrawn.")
    else:
        raise ValidationError("Choose a permitted assignment response.")
    if decision in {"accept", "customize"}:
        if not source_active(assignment):
            raise ValidationError("This group programme is no longer active or authorized. You may create an independent personal draft instead.")
        if not isinstance(payload, dict):
            raise ValidationError("Provide individual training inputs before accepting.")
        copy_plan(actor, assignment, payload, private_note)
        assignment.state, assignment.accepted_by = "accepted", actor
    else:
        assignment.state = "declined" if decision == "decline" else "withdrawn"
    assignment.version += 1
    assignment.save()
    services.audit(actor, None, "programme.assignment." + decision, assignment.pk, club=assignment.revision.programme.group.club)
    return assignment


def generation_allowed(job):
    marker = job.inputs.get("club_programme_assignment")
    if marker is None:
        return True
    if not enabled():
        return False
    if type(job.inputs.get("club_assignment_version")) is not int:
        return False
    try:
        marker = uuid.UUID(str(marker))
    except (ValueError, TypeError):
        return False
    row = ClubAssignmentPlan.objects.filter(plan=job, assignment_id=marker, number=job.inputs.get("club_assignment_version")).select_related(
        "assignment__revision__programme__group__club", "assignment__group_member__membership", "assignment__athlete", "actor").first()
    return bool(row and row.assignment.state == "accepted" and row.assignment.current_plan_number == row.number
        and row.assignment.athlete_id == job.athlete_id and row.actor_id == job.requested_by_id
        and row.actor and can(row.actor, row.assignment.athlete, "manage_grants") and source_active(row.assignment))


def plan_source(job):
    row = ClubAssignmentPlan.objects.filter(plan=job).select_related("assignment__revision__programme__group__club").first()
    if row is None:
        return None
    return {"assignment_id": str(row.assignment_id), "plan_version": row.number, "revision": row.assignment.revision.number,
        "group": row.assignment.revision.programme.group.name, **deepcopy(row.assignment.revision.snapshot)}


@transaction.atomic
def save_progress(actor, assignment_id, completed_sessions, private_note, version):
    assignment = assignment_for_owner(actor, assignment_id, write=True)
    AthleteProfile.objects.select_for_update(of=("self",)).get(pk=assignment.athlete_id)
    assignment = assignment_for_owner(actor, assignment_id, write=True)
    if assignment.state not in {"accepted", "withdrawn"}:
        raise ValidationError("Progress is available only for accepted personal assignments.")
    latest = assignment.plans.filter(number=assignment.current_plan_number, plan__status="ready").select_related("plan").first()
    if latest is None:
        raise ValidationError("Your individual draft is not ready yet.")
    total = sum(len(week.get("sessions", [])) for week in latest.plan.roadmap.get("microcycles", []))
    if type(completed_sessions) is not int or not 0 <= completed_sessions <= total or not isinstance(private_note, str) or len(private_note) > 2000:
        raise ValidationError("Use a valid self-reported session count and a private note of at most 2000 characters.")
    progress = ClubProgrammeProgress.objects.filter(assignment=assignment).first()
    if progress:
        version_check(progress, version)
        progress.version += 1
    elif version != 0:
        raise ProgrammeConflict("Progress changed. Reload before saving.")
    else:
        progress = ClubProgrammeProgress(assignment=assignment)
    progress.completed_sessions, progress.private_note = completed_sessions, private_note
    progress.save()
    services.audit(actor, None, "programme.progress.updated", assignment.pk, club=assignment.revision.programme.group.club)
    return progress


def shared_progress(actor, athlete_id):
    athlete = get_object_or_404(AthleteProfile, pk=athlete_id)
    rows = ClubProgrammeProgress.objects.filter(assignment__athlete=athlete).defer("private_note").select_related(
        "assignment__revision__programme__group__club", "assignment__group_member__membership", "assignment__athlete")
    result = []
    for row in rows:
        assignment = row.assignment
        club = assignment.revision.programme.group.club
        if assignment.state == "accepted" and source_active(assignment) and grants.allows(actor, athlete, "programme_progress", club_id=club.pk):
            result.append({"assignment": str(assignment.pk), "programme": assignment.revision.snapshot["title"],
                "completed_sessions": row.completed_sessions, "updated_at": row.updated_at})
    return {"progress": result}
