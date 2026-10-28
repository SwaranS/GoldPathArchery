"""Object permissions. Call for the specific operation again in jobs/history/export handlers."""

from django.db.models import Q

from .models import AthleteProfile, CoachRelationship, GuardianLink

OPERATIONS = {
    "view",
    "edit_profile",
    "edit_plan",
    "activate_plan",
    "log_scores",
    "manage_grants",
    "export",
    "close",
}


def is_admin(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (user.is_staff or user.is_superuser)
    )


def eligible_actor(user, *, write=False):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    own = AthleteProfile.objects.filter(account=user).first()
    return own is None or (own.closed_at is None and own.age() >= (16 if write else 14))


def can(user, athlete, operation):
    if (
        operation not in OPERATIONS
        or athlete.closed_at
        or not eligible_actor(user, write=operation != "view")
    ):
        return False
    age = athlete.age()
    if athlete.account_id == user.pk:
        return age >= (14 if operation == "view" else 16)
    parent = (
        GuardianLink.objects.filter(
            athlete=athlete, parent=user, revoked_at__isnull=True
        )
        .exclude(access="none")
        .first()
    )
    if parent:
        if operation == "view":
            return True
        if operation in {"manage_grants", "export", "close"}:
            return age < 16 and parent.managing and parent.access == "edit"
        if parent.access == "edit" and (
            (age < 16 and parent.managing) or (age >= 16 and parent.adult_grant)
        ):
            return True
    coach = CoachRelationship.objects.filter(
        athlete=athlete, coach=user, revoked_at__isnull=True
    ).first()
    return bool(
        coach
        and (operation == "view" or (operation == "edit_plan" and coach.plan_edit))
    )


def accessible_athletes(user):
    if not eligible_actor(user):
        return AthleteProfile.objects.none()
    return (
        AthleteProfile.objects.filter(closed_at__isnull=True)
        .filter(
            Q(account=user)
            | Q(
                guardians__parent=user,
                guardians__revoked_at__isnull=True,
                guardians__access__in=["view", "edit"],
            )
            | Q(coaches__coach=user, coaches__revoked_at__isnull=True)
        )
        .distinct()
    )


def training_fields(athlete):
    # Explicit allowlist: never serialize a model wholesale for coaches.
    return {
        "id": str(athlete.pk),
        "display_name": athlete.display_name,
        "discipline": athlete.discipline,
        "goals": athlete.goals,
        "availability": athlete.availability,
        "version": athlete.version,
    }
