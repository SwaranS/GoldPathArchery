"""Club identity and independent verification; no access to personal athlete data."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from accounts.models import validate_timezone


class Identity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Club(Identity):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending verification"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        ARCHIVED = "archived", "Archived"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=200, unique=True)
    country = models.CharField(max_length=80)
    region = models.CharField(max_length=100, blank=True)
    town = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(max_length=4000, blank=True)
    timezone = models.CharField(max_length=64, default="Europe/Dublin", validators=[validate_timezone])
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    verified_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    accepts_requests = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["pending", "active", "suspended", "archived"]), name="club_valid_status"),
            models.CheckConstraint(condition=Q(visibility__in=["public", "private"]), name="club_valid_visibility"),
            models.CheckConstraint(condition=~Q(status="active") | Q(verified_at__isnull=False), name="active_club_verified"),
        ]
        indexes = [models.Index(fields=["status", "visibility"])]

    def __str__(self):
        return self.name


class KnownClubListing(Identity):
    name = models.CharField(max_length=160)
    country = models.CharField(max_length=80)
    region = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    federation_number = models.CharField(max_length=100, blank=True)
    source_url = models.URLField()
    reviewed_on = models.DateField()
    club = models.OneToOneField(Club, null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return self.name


class ClubClaim(Identity):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        INFORMATION = "information_requested", "Information requested"
        REVIEW = "under_review", "Under review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    listing = models.ForeignKey(KnownClubListing, null=True, blank=True, on_delete=models.PROTECT)
    club = models.ForeignKey(Club, null=True, blank=True, on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    country = models.CharField(max_length=80)
    region = models.CharField(max_length=100, blank=True)
    town = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(max_length=4000, blank=True)
    visibility = models.CharField(max_length=10, choices=Club.Visibility.choices, default=Club.Visibility.PRIVATE)
    timezone = models.CharField(max_length=64, default="Europe/Dublin", validators=[validate_timezone])
    role_assertion = models.CharField(max_length=500)
    federation_number = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=24, choices=State.choices, default=State.SUBMITTED)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_club_claims")
    decision_reason = models.CharField(max_length=1000, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        permissions = [("review_club_claim", "Independently verify and decide club claims")]
        constraints = [models.CheckConstraint(condition=Q(state__in=["draft", "submitted", "information_requested", "under_review", "approved", "rejected"]), name="club_claim_valid_state")]
        indexes = [models.Index(fields=["state", "created_at"])]


class ClubVerificationEvidence(Identity):
    claim = models.ForeignKey(ClubClaim, on_delete=models.PROTECT, related_name="evidence")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    source_url = models.URLField(help_text="Independently located official source, not just the applicant's contact.")
    contact_reference = models.CharField(max_length=500)
    outcome = models.CharField(max_length=500)
    confirmed = models.BooleanField(default=False)
    checked_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    storage_key = models.CharField(max_length=100, blank=True, editable=False)
    purged_at = models.DateTimeField(null=True, blank=True, editable=False)


class ClubMembership(Identity):
    """Durable affiliation; requests and invitations have their own lifecycle."""
    club = models.ForeignKey(Club, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    athlete = models.ForeignKey("accounts.AthleteProfile", null=True, blank=True, on_delete=models.SET_NULL)
    active = models.BooleanField(default=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=12, blank=True, choices=[
        ("left", "Left"), ("removed", "Removed"), ("suspended", "Suspended")])
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["club", "user"], condition=Q(user__isnull=False), name="club_unique_user"),
            models.UniqueConstraint(fields=["club", "athlete"], condition=Q(athlete__isnull=False), name="club_unique_athlete"),
        ]


class ClubRoleAssignment(Identity):
    membership = models.ForeignKey(ClubMembership, on_delete=models.PROTECT, related_name="roles")
    role = models.CharField(max_length=20, default="admin", choices=[
        ("admin", "Admin"), ("membership_manager", "Membership manager"), ("coach", "Coach")])
    accepted_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    verified_claim = models.OneToOneField(ClubClaim, null=True, blank=True, on_delete=models.PROTECT)
    appointed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="club_appointments")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["membership", "role"], condition=Q(revoked_at__isnull=True), name="club_unique_active_role"),
            models.CheckConstraint(condition=Q(role__in=["admin", "membership_manager", "coach"]), name="club_role_valid")]


class ClubMembershipAction(Identity):
    club = models.ForeignKey(Club, on_delete=models.PROTECT)
    membership = models.ForeignKey(ClubMembership, null=True, blank=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=[("join", "Join request"), ("invite", "Invitation"), ("role", "Role appointment")])
    state = models.CharField(max_length=12, default="pending", choices=[
        ("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected"),
        ("declined", "Declined"), ("revoked", "Revoked")])
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="club_actions")
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="club_requests")
    athlete = models.ForeignKey("accounts.AthleteProfile", null=True, blank=True, on_delete=models.SET_NULL)
    recipient_email = models.EmailField(blank=True)
    token_digest = models.CharField(max_length=64, null=True, blank=True, unique=True)
    role = models.CharField(max_length=20, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="club_action_decisions")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["join", "invite", "role"]), name="club_action_kind_valid"),
            models.CheckConstraint(condition=Q(state__in=["pending", "accepted", "rejected", "declined", "revoked"]), name="club_action_state_valid"),
            models.CheckConstraint(condition=Q(role__in=["", "admin", "membership_manager", "coach"]), name="club_action_role_valid"),
        ]
        indexes = [models.Index(fields=["club", "kind", "state"])]


class AthleteHomeClub(Identity):
    athlete = models.OneToOneField("accounts.AthleteProfile", on_delete=models.CASCADE)
    club = models.ForeignKey(Club, null=True, blank=True, on_delete=models.PROTECT)
    version = models.PositiveIntegerField(default=1)


class AthleteHomeClubHistory(Identity):
    athlete = models.ForeignKey("accounts.AthleteProfile", on_delete=models.CASCADE)
    old_club = models.ForeignKey(Club, null=True, on_delete=models.PROTECT, related_name="home_departures")
    new_club = models.ForeignKey(Club, null=True, on_delete=models.PROTECT, related_name="home_arrivals")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    reason = models.CharField(max_length=20, default="selected")


class ClubAuditEvent(Identity):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    club = models.ForeignKey(Club, null=True, on_delete=models.PROTECT)
    claim = models.ForeignKey(ClubClaim, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=60)
    # Fixed action codes only. Evidence/notes/tokens never enter audit payloads.
    target_id = models.UUIDField(null=True)
    correlation_id = models.UUIDField(default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=20, default="service")


class ClubClaimDecision(Identity):
    """Append-only applicant-visible review history; excluded from operational logs."""
    claim = models.ForeignKey(ClubClaim, on_delete=models.PROTECT, related_name="decisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    state = models.CharField(max_length=24)
    reason = models.CharField(max_length=1000)

    class Meta:
        ordering = ["created_at", "id"]


class EvidenceUpload(Identity):
    """Durable upload intent. Failed/crashed uploads remain discoverable for cleanup."""
    storage_key = models.CharField(max_length=100, unique=True)


class ClubSecurityEvent(Identity):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=60)
    correlation_id = models.UUIDField(default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=20, default="web")


class ClubDataGrant(Identity):
    """Explicit athlete authority; never inferred from membership or account role."""
    athlete = models.ForeignKey("accounts.AthleteProfile", on_delete=models.CASCADE)
    club = models.ForeignKey(Club, on_delete=models.PROTECT)
    grantee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="club_data_grants")
    role = models.CharField(max_length=20, blank=True, choices=[("admin", "Admin"), ("membership_manager", "Membership manager"), ("coach", "Coach")])
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="approved_club_data_grants")
    scopes = models.JSONField(default=list)
    purpose = models.CharField(max_length=300)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(Q(grantee__isnull=False, role="") | Q(grantee__isnull=True, role__in=["admin", "membership_manager", "coach"])), name="club_grant_one_recipient"),
            models.CheckConstraint(condition=Q(expires_at__gt=models.F("starts_at")), name="club_grant_valid_window"),
        ]
        indexes = [models.Index(fields=["athlete", "club", "revoked_at"])]


FACILITY_AUDIENCES = [("public", "Public"), ("members", "Club members"), ("coaches", "Club coaches"), ("admins", "Club administrators"), ("group", "Named facility access group")]


class FacilityAccessGroup(Identity):
    club = models.ForeignKey(Club, on_delete=models.PROTECT, related_name="facility_access_groups")
    name = models.CharField(max_length=100)
    members = models.ManyToManyField(ClubMembership, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    def __str__(self):
        return self.name


class ClubFacility(Identity):
    club = models.ForeignKey(Club, on_delete=models.PROTECT, related_name="facilities")
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, max_length=4000)
    address = models.TextField(blank=True, max_length=1000)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    timezone = models.CharField(max_length=64, default="Europe/Dublin", validators=[validate_timezone])
    audience = models.CharField(max_length=10, choices=FACILITY_AUDIENCES, default="members")
    location_audience = models.CharField(max_length=10, choices=FACILITY_AUDIENCES, default="admins")
    access_group = models.ForeignKey(FacilityAccessGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="facilities")
    location_group = models.ForeignKey(FacilityAccessGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="locations")
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(audience__in=[a[0] for a in FACILITY_AUDIENCES]), name="facility_audience_valid"),
            models.CheckConstraint(condition=Q(location_audience__in=[a[0] for a in FACILITY_AUDIENCES]), name="facility_location_audience_valid"),
            models.CheckConstraint(condition=Q(latitude__isnull=True, longitude__isnull=True) | Q(latitude__isnull=False, longitude__isnull=False, latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180), name="facility_coordinates_valid"),
        ]

    def __str__(self):
        return self.name


class ShootingArea(Identity):
    facility = models.ForeignKey(ClubFacility, on_delete=models.PROTECT, related_name="areas")
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=10, choices=[("indoor", "Indoor"), ("outdoor", "Outdoor"), ("mixed", "Mixed")])
    disciplines = models.JSONField(default=list)
    distances_m = models.JSONField(default=list)
    lane_capacity = models.PositiveSmallIntegerField()
    target_capacity = models.PositiveSmallIntegerField()
    audience = models.CharField(max_length=10, choices=FACILITY_AUDIENCES, default="members")
    access_group = models.ForeignKey(FacilityAccessGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="areas")
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["indoor", "outdoor", "mixed"]), name="shooting_area_kind_valid"),
            models.CheckConstraint(condition=Q(audience__in=[a[0] for a in FACILITY_AUDIENCES]), name="shooting_area_audience_valid"),
            models.CheckConstraint(condition=Q(lane_capacity__gt=0, target_capacity__gt=0), name="shooting_area_capacity_positive"),
        ]


class FacilityAvailabilityRule(Identity):
    area = models.ForeignKey(ShootingArea, on_delete=models.PROTECT, related_name="rules")
    weekday = models.PositiveSmallIntegerField(choices=list(enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])))
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    priority = models.PositiveSmallIntegerField(default=0)
    audience = models.CharField(max_length=10, choices=FACILITY_AUDIENCES, default="members")
    access_group = models.ForeignKey(FacilityAccessGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="rules")
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(weekday__lte=6), name="facility_weekday_valid"),
            models.CheckConstraint(condition=Q(ends_on__isnull=True) | Q(ends_on__gte=models.F("starts_on")), name="facility_rule_dates_valid"),
            models.CheckConstraint(condition=Q(end_time__gt=models.F("start_time")), name="facility_rule_times_valid"),
            models.CheckConstraint(condition=Q(audience__in=[a[0] for a in FACILITY_AUDIENCES]), name="facility_rule_audience_valid"),
        ]


class FacilityAvailabilityException(Identity):
    area = models.ForeignKey(ShootingArea, on_delete=models.PROTECT, related_name="exceptions")
    starts_on = models.DateField()
    ends_on = models.DateField()
    kind = models.CharField(max_length=10, choices=[("closed", "Closed"), ("replace", "Replacement hours")])
    replacement_slots = models.JSONField(default=list, blank=True)
    reason = models.CharField(max_length=300)
    priority = models.PositiveSmallIntegerField(default=0)
    audience = models.CharField(max_length=10, choices=FACILITY_AUDIENCES, default="members")
    access_group = models.ForeignKey(FacilityAccessGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="exceptions")
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(ends_on__gte=models.F("starts_on")), name="facility_exception_dates_valid"),
            models.CheckConstraint(condition=Q(kind__in=["closed", "replace"]), name="facility_exception_kind_valid"),
            models.CheckConstraint(condition=Q(audience__in=[a[0] for a in FACILITY_AUDIENCES]), name="facility_exception_audience_valid"),
        ]


class FacilityPhoto(Identity):
    facility = models.ForeignKey(ClubFacility, on_delete=models.PROTECT, related_name="photos")
    caption = models.CharField(max_length=200)
    storage_key = models.CharField(max_length=100, unique=True, editable=False)
    audience = models.CharField(max_length=10, choices=FACILITY_AUDIENCES, default="admins")
    access_group = models.ForeignKey(FacilityAccessGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="photos")
    primary = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["facility"], condition=Q(primary=True, active=True), name="facility_one_primary_photo"),
            models.CheckConstraint(condition=Q(audience__in=[a[0] for a in FACILITY_AUDIENCES]), name="facility_photo_audience_valid")]


class FacilityPhotoUpload(Identity):
    storage_key = models.CharField(max_length=100, unique=True)


class ClubTrainingGroup(Identity):
    club = models.ForeignKey(Club, on_delete=models.PROTECT, related_name="training_groups")
    coach_role = models.ForeignKey(ClubRoleAssignment, on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, max_length=4000)
    discipline = models.CharField(max_length=12, choices=[(v, v.title()) for v in ("recurve", "compound", "barebow")])
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    def __str__(self):
        return self.name


class ClubTrainingGroupMember(Identity):
    group = models.ForeignKey(ClubTrainingGroup, on_delete=models.PROTECT, related_name="members")
    membership = models.ForeignKey(ClubMembership, on_delete=models.PROTECT, related_name="training_groups")
    state = models.CharField(max_length=12, default="invited", choices=[(v, v.title()) for v in ("invited", "active", "declined", "left", "removed")])
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    invited_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "membership"], name="training_group_member_unique"),
            models.CheckConstraint(condition=Q(state__in=["invited", "active", "declined", "left", "removed"]), name="training_group_member_state")]


class ClubProgramme(Identity):
    group = models.ForeignKey(ClubTrainingGroup, on_delete=models.PROTECT, related_name="programmes")
    owner_role = models.ForeignKey(ClubRoleAssignment, on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    active = models.BooleanField(default=True)
    published_revision = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)


class ClubProgrammeRevision(Identity):
    programme = models.ForeignKey(ClubProgramme, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    snapshot = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["programme", "number"], name="programme_revision_unique")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Programme revisions are immutable; create a new revision.")
        return super().save(*args, **kwargs)


class ClubProgrammeAssignment(Identity):
    revision = models.ForeignKey(ClubProgrammeRevision, on_delete=models.PROTECT, related_name="assignments")
    group_member = models.ForeignKey(ClubTrainingGroupMember, on_delete=models.PROTECT, related_name="assignments")
    athlete = models.ForeignKey("accounts.AthleteProfile", on_delete=models.CASCADE)
    group_member_version = models.PositiveIntegerField()
    offered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="offered_programmes")
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="accepted_programmes")
    expires_at = models.DateTimeField()
    state = models.CharField(max_length=12, default="offered", choices=[(v, v.title()) for v in ("offered", "accepted", "declined", "withdrawn", "cancelled")])
    current_plan_number = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["revision", "group_member", "group_member_version"], condition=Q(state__in=["offered", "accepted"]), name="programme_assignment_unique"),
            models.CheckConstraint(condition=Q(state__in=["offered", "accepted", "declined", "withdrawn", "cancelled"]), name="programme_assignment_state")]


class ClubAssignmentPlan(Identity):
    assignment = models.ForeignKey(ClubProgrammeAssignment, on_delete=models.CASCADE, related_name="plans")
    plan = models.OneToOneField("training.GeneratedPlan", null=True, on_delete=models.SET_NULL)
    number = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    private_note = models.TextField(blank=True, max_length=1000)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["assignment", "number"], name="assignment_plan_number_unique")]


class ClubProgrammeProgress(Identity):
    assignment = models.OneToOneField(ClubProgrammeAssignment, on_delete=models.CASCADE, related_name="progress")
    completed_sessions = models.PositiveIntegerField(default=0)
    private_note = models.TextField(blank=True, max_length=2000)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)
