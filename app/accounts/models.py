import uuid
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("Choose a valid IANA timezone.")


class User(AbstractUser):
    """Stable app identity independent of Google email and provider."""

    pass


class UserRole(models.Model):
    class Role(models.TextChoices):
        ARCHER = "archer", "Archer"
        PARENT = "parent", "Parent/guardian"
        COACH = "coach", "Coach"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="unique_user_role")
        ]


class AthleteProfile(models.Model):
    """Training identity survives changes to login accounts and relationships."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="athlete_profile",
    )
    display_name = models.CharField(max_length=100)
    birth_date = models.DateField()
    timezone = models.CharField(
        max_length=64, default="Europe/Dublin", validators=[validate_timezone]
    )
    discipline = models.CharField(
        max_length=20,
        choices=[(v, v.title()) for v in ("recurve", "compound", "barebow")],
    )
    goals = models.TextField(blank=True, max_length=4000)
    availability = models.TextField(blank=True, max_length=4000)
    hidden = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Applied once; request-time checks also enforce age rules without a scheduler.
    transitioned_at = models.DateTimeField(null=True, blank=True)
    parent_review_required = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def age(self, at=None):
        today = (at or timezone.now()).astimezone(ZoneInfo(self.timezone)).date()
        return (
            today.year
            - self.birth_date.year
            - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        )

    def clean(self):
        super().clean()
        validate_timezone(self.timezone)
        if not isinstance(self.birth_date, date):
            return  # Field validation supplies missing/invalid birth-date errors.
        if self.age() < 0:
            raise ValidationError({"birth_date": "Birth date cannot be in the future."})
        if self.account_id and self.age() < 14:
            raise ValidationError("Athletes under 14 cannot have a login account.")


class GuardianLink(models.Model):
    class Access(models.TextChoices):
        VIEW = "view", "View"
        EDIT = "edit", "Edit"
        NONE = "none", "No access"

    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="guardians"
    )
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="guardian_links",
    )
    access = models.CharField(max_length=4, choices=Access.choices, default=Access.EDIT)
    managing = models.BooleanField(default=False)
    declared_at = models.DateTimeField(null=True, blank=True)
    # Only an explicit 16+ athlete grant can authorise parent editing after 16.
    adult_grant = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["athlete", "parent"], name="unique_guardian_link"
            )
        ]


class CoachRelationship(models.Model):
    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="coaches"
    )
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="coached_athletes",
    )
    plan_edit = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["athlete", "coach"], name="unique_coach_relationship"
            )
        ]


class RelationshipInvitation(models.Model):
    class Kind(models.TextChoices):
        COACH = "coach", "Coach"
        PARENT = "parent", "Parent/guardian"
        CLAIM = "claim", "Athlete login"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="invitations"
    )
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    recipient_email = models.EmailField()
    kind = models.CharField(max_length=6, choices=Kind.choices)
    token_digest = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class RelationshipAudit(models.Model):
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    operation = models.CharField(max_length=60)
    target_reference = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RelationshipNotice(models.Model):
    """Durable in-app birthday notifications; no training payload or email delivery dependency."""

    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="relationship_notices",
    )
    kind = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["athlete", "recipient", "kind"],
                name="unique_relationship_notice",
            )
        ]
