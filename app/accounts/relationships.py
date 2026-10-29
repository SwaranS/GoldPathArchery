"""Transactional writes for private relationships. Lock the athlete before grants/tokens."""

import hashlib
import secrets
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from .models import (
    AthleteProfile,
    CoachRelationship,
    GuardianLink,
    RelationshipAudit,
    RelationshipInvitation,
    RelationshipNotice,
    UserRole,
)
from .permissions import can, eligible_actor


class Conflict(Exception):
    pass


def audit(athlete, actor, operation, target=""):
    RelationshipAudit.objects.create(
        athlete=athlete, actor=actor, operation=operation, target_reference=str(target)
    )


def require(user, athlete, operation):
    if not can(user, athlete, operation):
        raise PermissionDenied


def check_version(athlete, version):
    if str(athlete.version) != str(version):
        raise Conflict("This profile changed. Reload and review before saving.")


def changed(athlete):
    athlete.version += 1
    athlete.save(update_fields=["version"])


def apply_age_transition(athlete):
    """Caller holds athlete row lock. Does not resurrect revoked grants."""
    if athlete.closed_at or athlete.age() < 16 or athlete.transitioned_at:
        return
    athlete.transitioned_at = timezone.now()
    athlete.parent_review_required = True
    athlete.version += 1
    athlete.save(update_fields=["transitioned_at", "parent_review_required", "version"])
    athlete.guardians.filter(
        revoked_at__isnull=True, access="edit", adult_grant=False
    ).update(access="view")
    recipients = set(
        athlete.guardians.filter(revoked_at__isnull=True)
        .exclude(access="none")
        .values_list("parent_id", flat=True)
    )
    if athlete.account_id:
        recipients.add(athlete.account_id)
    for recipient in recipients:
        RelationshipNotice.objects.get_or_create(
            athlete=athlete, recipient_id=recipient, kind="athlete_turned_16"
        )
    audit(athlete, None, "age_16_transition")


@transaction.atomic
def transition(athlete_id):
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    apply_age_transition(athlete)
    return athlete


@transaction.atomic
def create_profile(user, data, *, child=False, declaration=False):
    if not eligible_actor(user, write=True):
        raise PermissionDenied
    role = UserRole.Role.PARENT if child else UserRole.Role.ARCHER
    if not user.role_assignments.filter(role=role).exists():
        raise PermissionDenied
    if child and not declaration:
        raise ValidationError("Confirm that you are this child's parent or guardian.")
    # Serializes creation/claim of the one own profile for a login.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    athlete = AthleteProfile(**data, account=None if child else user)
    athlete.full_clean()
    if (child and athlete.age() >= 16) or (not child and athlete.age() < 16):
        raise ValidationError(
            "Create child profiles below 16; junior logins must claim an existing profile by invitation."
        )
    athlete.save()
    if child:
        GuardianLink.objects.create(
            athlete=athlete, parent=user, managing=True, declared_at=timezone.now()
        )
    else:
        # A newly created adult profile has no inherited parent grants to review.
        athlete.transitioned_at = timezone.now()
        athlete.save(update_fields=["transitioned_at"])
    audit(athlete, user, "create_child" if child else "create_own")
    return athlete


@transaction.atomic
def update_profile(user, athlete_id, data, version):
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    apply_age_transition(athlete)
    require(user, athlete, "edit_profile")
    check_version(athlete, version)
    # Birth date/timezone corrections could reverse age permissions. Separate reauthenticated workflow needed.
    if set(data) - {"display_name", "discipline", "disciplines", "goals", "availability", "hidden"}:
        raise ValidationError(
            "Birth date, timezone and login changes are not supported here."
        )
    for key, value in data.items():
        setattr(athlete, key, value)
    athlete.full_clean()
    changed(athlete)
    athlete.save()
    audit(athlete, user, "edit_profile")
    return athlete


def may_invite(user, athlete, kind):
    if kind == RelationshipInvitation.Kind.CLAIM:
        if (
            not eligible_actor(user, write=True)
            or athlete.closed_at
            or athlete.account_id
            or athlete.age() < 14
        ):
            return False
        return (
            athlete.guardians.filter(
                parent=user, managing=True, revoked_at__isnull=True
            )
            .exclude(access="none")
            .exists()
        )
    return kind in {"parent", "coach"} and can(user, athlete, "manage_grants")


@transaction.atomic
def invite(user, athlete_id, kind, recipient_email, version):
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    apply_age_transition(athlete)
    if not may_invite(user, athlete, kind):
        raise PermissionDenied
    check_version(athlete, version)
    email = recipient_email.strip().lower()
    validate_email(email)
    if (
        EmailAddress.objects.filter(user=user, email__iexact=email).exists()
        or email == user.email.lower()
    ):
        raise ValidationError("Invite a different person's verified email.")
    token = secrets.token_urlsafe(32)
    invitation = RelationshipInvitation.objects.create(
        athlete=athlete,
        sender=user,
        kind=kind,
        recipient_email=email,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        created_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=7),
    )
    changed(athlete)
    audit(athlete, user, "invite_" + kind, invitation.pk)
    return invitation, token


@transaction.atomic
def accept(user, token, *, declaration=False):
    # Never expose target or recipient on an invalid, expired, forwarded or revoked link.
    digest = hashlib.sha256(token.encode()).hexdigest()
    stub = (
        RelationshipInvitation.objects.filter(token_digest=digest)
        .values("athlete_id")
        .first()
    )
    if not stub:
        raise PermissionDenied
    athlete = AthleteProfile.objects.select_for_update().get(pk=stub["athlete_id"])
    invitation = RelationshipInvitation.objects.select_for_update().get(
        token_digest=digest
    )
    apply_age_transition(athlete)
    if (
        not eligible_actor(user, write=invitation.kind != "claim")
        or athlete.closed_at
        or invitation.accepted_at
        or invitation.revoked_at
        or invitation.expires_at <= timezone.now()
        or invitation.sender_id == user.pk
        or not EmailAddress.objects.filter(
            user=user, email__iexact=invitation.recipient_email, verified=True
        ).exists()
        or not may_invite(invitation.sender, athlete, invitation.kind)
    ):
        raise PermissionDenied
    if invitation.kind == "claim":
        get_user_model().objects.select_for_update().get(pk=user.pk)
        if (
            athlete.account_id
            or athlete.age() < 14
            or AthleteProfile.objects.filter(account=user).exists()
        ):
            raise PermissionDenied
        # An existing guardian/coach must never become the child's login.
        if (
            athlete.guardians.filter(parent=user).exists()
            or athlete.coaches.filter(coach=user).exists()
        ):
            raise PermissionDenied
        athlete.account = user
        athlete.save(update_fields=["account"])
        UserRole.objects.get_or_create(user=user, role="archer")
        if athlete.age() >= 16:
            athlete.parent_review_required = True
            athlete.save(update_fields=["parent_review_required"])
            RelationshipNotice.objects.get_or_create(
                athlete=athlete, recipient=user, kind="athlete_turned_16"
            )
    else:
        if athlete.account_id == user.pk:
            raise PermissionDenied
        if invitation.kind == "coach":
            if not user.role_assignments.filter(role="coach").exists():
                raise PermissionDenied
            CoachRelationship.objects.update_or_create(
                athlete=athlete,
                coach=user,
                defaults={
                    "revoked_at": None,
                    "plan_edit": False,
                    "accepted_at": timezone.now(),
                },
            )
        else:
            if not user.role_assignments.filter(role="parent").exists() or (
                athlete.age() < 16 and not declaration
            ):
                raise PermissionDenied
            GuardianLink.objects.update_or_create(
                athlete=athlete,
                parent=user,
                defaults={
                    "access": "edit" if athlete.age() < 16 else "view",
                    "managing": athlete.age() < 16,
                    "adult_grant": False,
                    "revoked_at": None,
                    "declared_at": timezone.now() if declaration else None,
                },
            )
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    changed(athlete)
    audit(athlete, user, "accept_" + invitation.kind, invitation.pk)
    return athlete


@transaction.atomic
def set_grant(user, athlete_id, kind, target_id, access, version):
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    apply_age_transition(athlete)
    if athlete.closed_at:
        raise PermissionDenied
    if kind == "coach":
        link = CoachRelationship.objects.get(athlete=athlete, pk=target_id)
        self_end = (
            link.coach_id == user.pk
            and access == "none"
            and eligible_actor(user, write=True)
        )
        if not self_end:
            require(user, athlete, "manage_grants")
        check_version(athlete, version)
        if access not in {"view", "edit", "none"} or (
            link.revoked_at and access != "none"
        ):
            raise ValidationError(
                "An ended coach relationship requires a new invitation."
            )
        link.plan_edit = access == "edit"
    elif kind == "parent":
        link = GuardianLink.objects.get(athlete=athlete, pk=target_id)
        self_end = (
            link.parent_id == user.pk
            and access == "none"
            and eligible_actor(user, write=True)
        )
        if not self_end:
            require(user, athlete, "manage_grants")
        check_version(athlete, version)
        if access not in {"view", "edit", "none"} or (
            link.revoked_at and access != "none"
        ):
            raise ValidationError(
                "An ended parent relationship requires a new invitation."
            )
        if athlete.age() < 16 and link.managing and access != "edit":
            others = athlete.guardians.filter(
                managing=True, access="edit", revoked_at__isnull=True
            ).exclude(pk=link.pk)
            if not others.exists():
                raise ValidationError(
                    "Transfer management to another parent before removing the last managing parent."
                )
        link.access = access
        link.adult_grant = athlete.age() >= 16 and access != "none"
    else:
        raise ValidationError("Unknown relationship.")
    link.revoked_at = timezone.now() if access == "none" else None
    link.save()
    # Revocation also kills outstanding invitations to that recipient to avoid stale re-grants.
    if access == "none":
        target = link.coach if kind == "coach" else link.parent
        emails = list(
            EmailAddress.objects.filter(user=target).values_list("email", flat=True)
        ) + [target.email]
        for email in emails:
            athlete.invitations.filter(
                kind=kind,
                recipient_email__iexact=email,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
            ).update(revoked_at=timezone.now())
        # A removed managing parent cannot leave invitations behind for later reactivation.
        athlete.invitations.filter(
            sender=target, accepted_at__isnull=True, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
    changed(athlete)
    audit(athlete, user, kind + "_grant_" + access, link.pk)


@transaction.atomic
def revoke_invitation(user, athlete_id, invitation_id, version):
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    apply_age_transition(athlete)
    invitation = RelationshipInvitation.objects.get(pk=invitation_id, athlete=athlete)
    if athlete.closed_at:
        raise PermissionDenied
    if not (
        eligible_actor(user, write=True)
        and user.pk == invitation.sender_id
        and may_invite(user, athlete, invitation.kind)
    ):
        require(user, athlete, "manage_grants")
    check_version(athlete, version)
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at"])
    changed(athlete)
    audit(athlete, user, "revoke_invitation", invitation.pk)


@transaction.atomic
def confirm_parent_review(user, athlete_id, version):
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    apply_age_transition(athlete)
    if athlete.account_id != user.pk:
        raise PermissionDenied
    require(user, athlete, "manage_grants")
    check_version(athlete, version)
    athlete.parent_review_required = False
    changed(athlete)
    athlete.save(update_fields=["parent_review_required"])
    audit(athlete, user, "parent_review_confirmed")
