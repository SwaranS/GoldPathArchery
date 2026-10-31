"""Club-scoped membership transitions; no grants to personal athlete records.

All club mutations serialize on the club row. Home preferences additionally lock
the athlete, so concurrent joins/removals cannot silently select a departed club.
"""
import hashlib
import secrets
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, F
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.models import AthleteProfile
from accounts.permissions import can, eligible_actor, accessible_athletes
from . import services
from .models import (Club, ClubMembership, ClubRoleAssignment, ClubMembershipAction,
                     AthleteHomeClub, AthleteHomeClubHistory)

ROLES = {"admin", "membership_manager", "coach"}


def enabled():
    services.enabled()
    if not getattr(settings, "CLUB_MEMBERSHIPS_ENABLED", False):
        raise Http404


def actor_allowed(actor, *, write=False):
    enabled()
    if not eligible_actor(actor, write=write):
        raise PermissionDenied


def live_club(club):
    return club.status == "active" and club.verified_at is not None


def has_role(actor, club, roles):
    return bool(eligible_actor(actor, write=True) and live_club(club) and
        ClubRoleAssignment.objects.filter(membership__club=club, membership__user=actor,
            membership__active=True, role__in=roles, revoked_at__isnull=True,
            accepted_at__lte=timezone.now()).exists())


def managed(actor, club_id, *, admin=False, lock=False):
    actor_allowed(actor, write=True)
    qs = Club.objects.select_for_update() if lock else Club.objects
    club = get_object_or_404(qs, pk=club_id)
    if not has_role(actor, club, {"admin"} if admin else {"admin", "membership_manager"}):
        raise Http404
    return club


def subjects(actor):
    actor_allowed(actor, write=True)
    return [athlete for athlete in accessible_athletes(actor).order_by("display_name", "pk")
            if can(actor, athlete, "manage_grants")]


def subject(actor, athlete_id=None):
    actor_allowed(actor, write=True)
    if athlete_id:
        athlete = get_object_or_404(AthleteProfile, pk=athlete_id)
        if not can(actor, athlete, "manage_grants"):
            raise Http404
        return athlete
    return None


def owns(actor, membership):
    if membership.athlete_id:
        return can(actor, membership.athlete, "manage_grants")
    return membership.user_id == actor.pk and eligible_actor(actor, write=True)


def owned_memberships(actor):
    actor_allowed(actor)
    athletes = [a.pk for a in accessible_athletes(actor) if can(actor, a, "manage_grants")]
    return ClubMembership.objects.filter(Q(user=actor) | Q(athlete_id__in=athletes)).select_related("club", "athlete").order_by("club__name")


def owner_actions(actor):
    actor_allowed(actor)
    return ClubMembershipAction.objects.filter(Q(actor=actor) | Q(target_user=actor)).select_related("club", "athlete").order_by("-created_at")


def membership_identity(actor, athlete):
    return (athlete.account if athlete else actor), athlete


def check_pending(action, version):
    services.check_version(action, version)
    if action.state != "pending" or (action.expires_at and action.expires_at <= timezone.now()):
        raise ValidationError("This request is no longer pending or has expired.")


def finish(actor, action, state):
    action.state = state
    action.decided_at = timezone.now()
    action.decided_by = actor
    action.version += 1
    action.save()
    services.audit(actor, None, "membership." + action.kind + "." + state, action.pk, club=action.club)


def activate(actor, club, user, athlete):
    query = Q(athlete=athlete) if athlete else Q(user=user)
    if athlete and user:
        query |= Q(user=user)
    rows = list(ClubMembership.objects.filter(query, club=club))
    if len(rows) > 1:
        raise ValidationError("Existing member identities need platform review before linking.")
    member = rows[0] if rows else ClubMembership(club=club, user=user, athlete=athlete)
    if member.pk and not member._state.adding and member.active:
        raise ValidationError("This identity is already an active member.")
    member.user, member.athlete = user, athlete
    member.active, member.ended_at, member.ended_reason = True, None, ""
    member.version += 1
    member.save()
    services.audit(actor, None, "membership.activated", member.pk, club=club)
    return member


@transaction.atomic
def request_join(actor, club_id, athlete_id=None):
    athlete = subject(actor, athlete_id)
    club = get_object_or_404(Club.objects.select_for_update(), pk=club_id,
        visibility="public", status="active", verified_at__isnull=False)
    if not club.accepts_requests:
        raise ValidationError("This club is not accepting join requests. An invitation is required.")
    user, athlete = membership_identity(actor, athlete)
    identity = Q(athlete=athlete) if athlete else Q(user=user, athlete__isnull=True)
    if athlete and user:
        identity |= Q(user=user)
    if ClubMembership.objects.filter(identity, club=club, active=True).exists():
        raise ValidationError("Already an active member.")
    # Removed/suspended members can only return through an explicit invitation.
    if ClubMembership.objects.filter(identity, club=club, ended_reason__in=["removed", "suspended"]).exists():
        raise ValidationError("A new club invitation is required to restore this membership.")
    action_identity = Q(athlete=athlete) if athlete else Q(target_user=user, athlete__isnull=True)
    if athlete and user:
        action_identity |= Q(target_user=user)
    if ClubMembershipAction.objects.filter(action_identity, club=club, kind="join", state="pending").exists():
        raise ValidationError("A join request is already pending.")
    action = ClubMembershipAction.objects.create(club=club, kind="join", actor=actor,
        target_user=user, athlete=athlete)
    services.audit(actor, None, "membership.join.requested", action.pk, club=club)
    return action


@transaction.atomic
def decide_join(actor, club_id, action_id, accept, version):
    club = managed(actor, club_id, lock=True)
    action = get_object_or_404(ClubMembershipAction.objects.select_for_update(), pk=action_id, club=club, kind="join")
    check_pending(action, version)
    if action.actor_id == actor.pk:
        raise PermissionDenied("Another manager must decide your join request.")
    if accept:
        if not action.actor or not eligible_actor(action.actor, write=True):
            raise ValidationError("The applicant is no longer eligible.")
        if action.athlete_id:
            if not can(action.actor, action.athlete, "manage_grants"):
                raise ValidationError("Guardian or athlete authority changed; submit a new request.")
            user = action.athlete.account
        else:
            user = action.target_user
            if not user or user.pk != action.actor_id:
                raise ValidationError("Applicant identity is no longer valid.")
        action.membership = activate(actor, club, user, action.athlete)
    finish(actor, action, "accepted" if accept else "rejected")
    return action


@transaction.atomic
def invite(actor, club_id, email):
    club = managed(actor, club_id, lock=True)
    from django.core.validators import validate_email
    email = email.strip().lower()
    validate_email(email)
    if len(email) > 254:
        raise ValidationError("Email address is too long.")
    token = secrets.token_urlsafe(32)
    action = ClubMembershipAction.objects.create(club=club, kind="invite", actor=actor,
        recipient_email=email, token_digest=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(days=14))
    services.audit(actor, None, "membership.invited", action.pk, club=club)
    return action, token


def recipient(actor, action, token):
    actor_allowed(actor, write=True)
    if action.kind != "invite" or not token or len(token) > 128:
        raise Http404
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not secrets.compare_digest(digest, action.token_digest or ""):
        raise Http404
    if not EmailAddress.objects.filter(user=actor, email__iexact=action.recipient_email, verified=True).exists():
        raise Http404


@transaction.atomic
def accept_invite(actor, action_id, token, *, accept=True, athlete_id=None):
    # Do not reveal a private club before both token and verified recipient match.
    action = get_object_or_404(ClubMembershipAction, pk=action_id)
    recipient(actor, action, token)
    club = Club.objects.select_for_update().get(pk=action.club_id)
    action = ClubMembershipAction.objects.select_for_update().get(pk=action.pk)
    check_pending(action, action.version)
    if not live_club(club) or not action.actor or not has_role(action.actor, club, {"admin", "membership_manager"}):
        raise ValidationError("This invitation is no longer authorized.")
    if accept:
        athlete = subject(actor, athlete_id)
        user, athlete = membership_identity(actor, athlete)
        identity = Q(athlete=athlete) if athlete else Q(user=user)
        if athlete and user:
            identity |= Q(user=user)
        if ClubMembership.objects.filter(identity, club=club, ended_at__gte=action.created_at).exists():
            raise ValidationError("Membership ended after this invitation was issued. A new invitation is required.")
        action.membership = activate(actor, club, user, athlete)
        action.target_user, action.athlete = user, athlete
    finish(actor, action, "accepted" if accept else "declined")
    return action


@transaction.atomic
def offer_role(actor, club_id, member_id, role, version):
    club = managed(actor, club_id, admin=True, lock=True)
    member = get_object_or_404(ClubMembership, pk=member_id, club=club, active=True)
    services.check_version(member, version)
    if role not in ROLES or not member.user or not eligible_actor(member.user, write=True):
        raise ValidationError("Roles require an eligible adult account and a predefined club role.")
    if member.user_id == actor.pk:
        raise PermissionDenied("Another administrator must appoint your additional role.")
    if member.roles.filter(role=role, revoked_at__isnull=True).exists() or ClubMembershipAction.objects.filter(
            membership=member, kind="role", role=role, state="pending", expires_at__gt=timezone.now()).exists():
        raise ValidationError("This role is already active or offered.")
    action = ClubMembershipAction.objects.create(club=club, membership=member, kind="role", role=role,
        target_user=member.user, actor=actor, expires_at=timezone.now() + timedelta(days=14))
    services.audit(actor, None, "membership.role.offered", action.pk, club=club)
    return action


@transaction.atomic
def accept_role(actor, action_id, accept, version):
    actor_allowed(actor, write=True)
    action = get_object_or_404(ClubMembershipAction, pk=action_id, kind="role", target_user=actor)
    club = Club.objects.select_for_update().get(pk=action.club_id)
    action = ClubMembershipAction.objects.select_for_update().get(pk=action.pk)
    check_pending(action, version)
    member = action.membership
    if not member or not member.active or member.user_id != actor.pk or not action.actor or not has_role(action.actor, club, {"admin"}):
        raise ValidationError("This appointment is no longer authorized.")
    if accept:
        ClubRoleAssignment.objects.create(membership=member, role=action.role, accepted_at=timezone.now(), appointed_by=action.actor)
        member.version += 1
        member.save(update_fields=["version"])
    finish(actor, action, "accepted" if accept else "declined")
    return action


def protect_last_admin(club, member, role=None):
    if role not in (None, "admin") or not member.roles.filter(role="admin", revoked_at__isnull=True).exists():
        return
    admins = ClubRoleAssignment.objects.filter(membership__club=club, membership__active=True,
        role="admin", revoked_at__isnull=True, accepted_at__lte=timezone.now()).exclude(membership=member).select_related("membership__user")
    if not any(eligible_actor(a.membership.user, write=True) for a in admins):
        raise ValidationError("The last active administrator cannot leave or be removed. An accepted successor or platform recovery is required.")


def clear_home(actor, member):
    athlete = member.athlete
    if athlete is None and member.user_id:
        athlete = AthleteProfile.objects.filter(account_id=member.user_id).first()
    if not athlete:
        return
    AthleteProfile.objects.select_for_update().get(pk=athlete.pk)
    home = AthleteHomeClub.objects.filter(athlete=athlete, club=member.club).first()
    if home:
        AthleteHomeClubHistory.objects.create(athlete=athlete, old_club=home.club, new_club=None, actor=actor, reason="membership_ended")
        home.club = None
        home.version += 1
        home.save()
        services.audit(actor, None, "home.cleared", home.pk, club=member.club)


@transaction.atomic
def end_membership(actor, club_id, member_id, reason, version):
    actor_allowed(actor, write=True)
    club = get_object_or_404(Club.objects.select_for_update(), pk=club_id)
    member = get_object_or_404(ClubMembership.objects.select_related("athlete"), pk=member_id, club=club)
    if reason == "left":
        if not owns(actor, member):
            raise Http404
    elif reason in {"removed", "suspended"}:
        if not has_role(actor, club, {"admin"}):
            raise Http404
    else:
        raise ValidationError("Choose a permitted membership action.")
    services.check_version(member, version)
    if not member.active:
        raise ValidationError("This membership has already ended.")
    protect_last_admin(club, member)
    member.active, member.ended_at, member.ended_reason = False, timezone.now(), reason
    member.version += 1
    member.save()
    member.roles.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    # A later rejoin must not silently restore restricted facility audiences.
    for group in member.facilityaccessgroup_set.all():
        services.audit(actor, None, "facility.group.membership_ended", group.pk, club=club)
    member.facilityaccessgroup_set.clear()
    for group_member in member.training_groups.filter(state__in=["active", "invited"]):
        group_member.state, group_member.version = "left", group_member.version+1
        group_member.decided_at = timezone.now()
        group_member.save()
        group_member.assignments.filter(state="offered").update(state="cancelled", version=F("version")+1)
        services.audit(actor, None, "programme.group.membership_ended", group_member.pk, club=club)
    ClubMembershipAction.objects.filter(membership=member, kind="role", state="pending").update(state="revoked", decided_at=timezone.now(), decided_by=actor)
    clear_home(actor, member)
    from .models import ClubDataGrant
    affected = Q(athlete_id=member.athlete_id) if member.athlete_id else Q(pk__in=[])
    if member.user_id:
        affected |= Q(grantee_id=member.user_id) | Q(athlete__account_id=member.user_id)
    for grant in ClubDataGrant.objects.filter(affected, club=club, revoked_at__isnull=True):
        grant.revoked_at = timezone.now()
        grant.version += 1
        grant.save(update_fields=["revoked_at", "version"])
        services.audit(actor, None, "grant.membership_ended", grant.pk, club=club)
    services.audit(actor, None, "membership." + reason, member.pk, club=club)
    return member


@transaction.atomic
def revoke_role(actor, club_id, role_id, version):
    club = managed(actor, club_id, admin=True, lock=True)
    role = get_object_or_404(ClubRoleAssignment.objects.select_related("membership"), pk=role_id, membership__club=club, revoked_at__isnull=True)
    services.check_version(role.membership, version)
    protect_last_admin(club, role.membership, role.role)
    role.revoked_at = timezone.now()
    role.save(update_fields=["revoked_at"])
    role.membership.version += 1
    role.membership.save(update_fields=["version"])
    services.audit(actor, None, "membership.role.revoked", role.pk, club=club)


@transaction.atomic
def revoke_action(actor, club_id, action_id, version):
    club = managed(actor, club_id, lock=True)
    action = get_object_or_404(ClubMembershipAction.objects.select_for_update(), pk=action_id, club=club)
    if action.kind == "role" and not has_role(actor, club, {"admin"}):
        raise Http404
    check_pending(action, version)
    finish(actor, action, "revoked")


def home_options(athlete):
    identity = Q(athlete=athlete)
    if athlete.account_id:
        identity |= Q(user_id=athlete.account_id)
    return Club.objects.filter(clubmembership__in=ClubMembership.objects.filter(identity, active=True),
        status="active", verified_at__isnull=False).distinct().order_by("name")


@transaction.atomic
def select_home(actor, athlete_id, club_id, version):
    athlete = subject(actor, athlete_id)
    AthleteProfile.objects.select_for_update().get(pk=athlete.pk)
    home = AthleteHomeClub.objects.filter(athlete=athlete).first()
    if home is None:
        if version != 0:
            raise services.ClaimConflict("Home club changed. Reload before saving.")
        home = AthleteHomeClub(athlete=athlete)
    else:
        services.check_version(home, version)
    club = get_object_or_404(home_options(athlete), pk=club_id) if club_id else None
    if home.club_id == (club.pk if club else None):
        return home
    AthleteHomeClubHistory.objects.create(athlete=athlete, old_club=home.club, new_club=club, actor=actor)
    home.club = club
    home.version += 1
    home.save()
    services.audit(actor, None, "home.selected" if club else "home.cleared", home.pk, club=club)
    return home


@transaction.atomic
def set_requests(actor, club_id, accepts, version):
    club = managed(actor, club_id, admin=True, lock=True)
    services.check_version(club, version)
    club.accepts_requests = accepts
    club.version += 1
    club.save(update_fields=["accepts_requests", "version"])
    services.audit(actor, None, "membership.requests.changed", club.pk, club=club)
