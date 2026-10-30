import math
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


DIVISIONS = [(x, x.title()) for x in ("recurve", "compound", "barebow")]


def positive_measurement(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
    except (ValueError, TypeError, OverflowError):
        return False


def validate_geometry(value):
    """Spots use normalized canvas centres and radii; rings are outer radii."""
    try:
        spots, rings = value["spots"], value["rings"]
        if not spots or not rings or len(spots) > 16:
            raise ValueError
        for x, y, radius in spots:
            if not all(math.isfinite(float(v)) for v in (x, y, radius)):
                raise ValueError
            if radius <= 0 or abs(x) + radius > 1 or abs(y) + radius > 1:
                raise ValueError
        if any(not math.isfinite(float(r)) or not 0 < r <= 1 for r in rings):
            raise ValueError
        if rings != sorted(set(rings)):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValidationError("Geometry needs spots [[x,y,radius],...] inside [-1,1] and increasing ring radii in (0,1].")


def validate_rules(value):
    try:
        zones = value["zones"]
        if not zones or value.get("boundary", "inner") != "inner":
            raise ValueError
        radii = []
        symbols = set()
        for zone in zones:
            radius, symbol, points = zone["radius"], zone["symbol"], zone["points"]
            if not isinstance(symbol, str) or not symbol or len(symbol) > 8 or symbol == "M" or symbol in symbols:
                raise ValueError
            if isinstance(points, bool) or not isinstance(points, int) or not 0 <= points <= 100:
                raise ValueError
            if not isinstance(zone.get("x", False), bool):
                raise ValueError
            if not math.isfinite(float(radius)) or not 0 < radius <= 1:
                raise ValueError
            radii.append(radius)
            symbols.add(symbol)
        if radii != sorted(set(radii)):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValidationError("Rules need unique ordered zones with radius, symbol, integer points and optional boolean x; boundary must be inner.")


class TargetFace(models.Model):
    name = models.CharField(max_length=100)
    diameter_cm = models.FloatField()
    layout = models.CharField(max_length=30, default="full")
    geometry = models.JSONField(validators=[validate_geometry])
    active = models.BooleanField(default=True)

    def clean(self):
        if self.diameter_cm is not None and (not math.isfinite(self.diameter_cm) or self.diameter_cm <= 0):
            raise ValidationError("Diameter must be positive and finite.")

    def __str__(self):
        return self.name


class ScoringRuleSet(models.Model):
    name = models.CharField(max_length=100)
    rules = models.JSONField(validators=[validate_rules])
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class RoundDefinition(models.Model):
    name = models.CharField(max_length=100)
    division = models.CharField(max_length=20, choices=DIVISIONS)
    category = models.CharField(max_length=100, blank=True)
    verification_required = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    @property
    def maximum(self):
        return sum(s.ends * s.arrows_per_end * max(z["points"] for z in s.rules.rules["zones"]) for s in self.stages.all())

    def __str__(self):
        return self.name


class RoundStage(models.Model):
    round = models.ForeignKey(RoundDefinition, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveIntegerField()
    distance_m = models.FloatField()
    target = models.ForeignKey(TargetFace, on_delete=models.PROTECT)
    rules = models.ForeignKey(ScoringRuleSet, on_delete=models.PROTECT)
    ends = models.PositiveSmallIntegerField()
    arrows_per_end = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["round", "order"], name="scoring_stage_order")]

    def clean(self):
        if ((self.distance_m is not None and (not math.isfinite(self.distance_m) or self.distance_m <= 0))
            or (self.ends is not None and not 1 <= self.ends <= 100)
            or (self.arrows_per_end is not None and not 1 <= self.arrows_per_end <= 36)):
            raise ValidationError("Use positive distance, 1Ã¢â‚¬â€œ100 ends and 1Ã¢â‚¬â€œ36 arrows per end.")


class Equipment(models.Model):
    athlete = models.ForeignKey("accounts.AthleteProfile", on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=[("bow", "Bow"), ("arrow_set", "Arrow set")])
    name = models.CharField(max_length=100)
    division = models.CharField(max_length=20, choices=DIVISIONS, blank=True)
    details = models.TextField(blank=True, max_length=2000)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def clean(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError({"name": "Enter an equipment name."})
        if self.kind == "bow" and not self.division:
            raise ValidationError({"division": "Select a bow division."})
        if self.kind == "arrow_set" and self.division:
            raise ValidationError({"division": "Arrow sets do not have a bow division."})


class EquipmentRevision(models.Model):
    """Append-only specifications; Equipment remains the logical identity."""
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)
    name = models.CharField(max_length=100)
    division = models.CharField(max_length=20, choices=DIVISIONS, blank=True)
    details = models.TextField(blank=True, max_length=2000, verbose_name="Setup notes / arrow-set notes")
    brand = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    handedness = models.CharField(max_length=5, blank=True, choices=[("left", "Left"), ("right", "Right")])
    draw_weight = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    draw_weight_unit = models.CharField(max_length=2, blank=True, choices=[("lb", "lb"), ("kg", "kg")])
    draw_length = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    draw_length_unit = models.CharField(max_length=2, blank=True, choices=[("in", "in"), ("cm", "cm")])
    spine = models.CharField(max_length=40, blank=True)
    length = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    length_unit = models.CharField(max_length=2, blank=True, choices=[("in", "in"), ("cm", "cm")])
    point_weight = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    point_weight_unit = models.CharField(max_length=2, blank=True, choices=[("gr", "grains"), ("g", "g")])
    shaft_diameter = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    shaft_diameter_unit = models.CharField(max_length=2, blank=True, choices=[("mm", "mm"), ("in", "in")])

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["equipment", "number"], name="equipment_revision_number")]

    def clean(self):
        errors = {}
        if not isinstance(self.name, str) or not self.name.strip():
            errors["name"] = "Enter an equipment name."
        for field in ("draw_weight", "draw_length", "length", "point_weight", "shaft_diameter"):
            value, unit = getattr(self, field), getattr(self, field + "_unit")
            if value is not None and not positive_measurement(value):
                errors[field] = "Use a positive finite value."
            if (value is not None) != bool(unit):
                errors[field + "_unit"] = "Supply both a value and its unit, or leave both empty."
        if self.equipment_id:
            bow = self.equipment.kind == "bow"
            if bow and not self.division:
                errors["division"] = "Select a bow division."
            forbidden = ("spine", "length", "point_weight", "shaft_diameter") if bow else ("division", "handedness", "draw_weight", "draw_length")
            for field in forbidden:
                if getattr(self, field):
                    errors[field] = "This field does not apply to this equipment type."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Equipment revisions cannot be changed; create a new revision.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} Ã‚Â· revision {self.number}"


class PhysicalArrow(models.Model):
    arrow_set = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="arrows")
    identifier = models.CharField(max_length=40, validators=[RegexValidator(r"\A[A-Za-z0-9]+\Z", "Use an alphanumeric identifier (letters and digits only).")])
    notes = models.TextField(blank=True, max_length=2000)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["arrow_set", "identifier"], name="scoring_arrow_identifier")]

    def clean(self):
        if self.arrow_set_id and self.arrow_set.kind != "arrow_set":
            raise ValidationError("Physical arrows belong to an arrow set.")


class SightMark(models.Model):
    athlete = models.ForeignKey("accounts.AthleteProfile", on_delete=models.CASCADE)
    bow_revision = models.ForeignKey(EquipmentRevision, on_delete=models.PROTECT, related_name="bow_marks", null=True, blank=True)
    configuration_revision = models.ForeignKey("ConfigurationRevision", on_delete=models.PROTECT, null=True, blank=True, related_name="sight_marks")
    arrow_revision = models.ForeignKey(EquipmentRevision, on_delete=models.PROTECT, related_name="arrow_marks", null=True, blank=True)
    distance = models.DecimalField(max_digits=8, decimal_places=3)
    distance_unit = models.CharField(max_length=2, choices=[("m", "m"), ("yd", "yards")])
    mark = models.CharField(max_length=100)
    sight_extension = models.CharField(max_length=100, blank=True)
    windage = models.CharField(max_length=100, blank=True)
    date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, max_length=2000)
    active = models.BooleanField(default=True)

    def clean(self):
        errors = {}
        if self.distance is not None and not positive_measurement(self.distance):
            errors["distance"] = "Use a positive finite distance."
        if not isinstance(self.mark, str) or not self.mark.strip():
            errors["mark"] = "Enter a sight mark."
        if bool(self.bow_revision_id) == bool(self.configuration_revision_id):
            errors["bow_revision"] = "Choose either a legacy bow or exact configuration revision."
        if self.configuration_revision_id and self.configuration_revision.configuration.owner_id != self.athlete_id:
            errors["configuration_revision"] = "Choose this athlete's configuration."
        for field, kind in (("bow_revision", "bow"), ("arrow_revision", "arrow_set")):
            if getattr(self, field + "_id"):
                item = getattr(self, field).equipment
                if item.athlete_id != self.athlete_id or item.kind != kind:
                    errors[field] = "Choose equipment belonging to this athlete with the correct type."
        if errors:
            raise ValidationError(errors)


class ScoringSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    athlete = models.ForeignKey("accounts.AthleteProfile", on_delete=models.CASCADE, related_name="scoring_sessions")
    context = models.CharField(max_length=12, choices=[("training", "Training"), ("competition", "Competition")])
    mode = models.CharField(max_length=12, choices=[("round", "Configured round"), ("custom", "Custom training")])
    # Only services write snapshots, with all mutable configuration copied by value.
    snapshot = models.JSONField()
    equipment = models.JSONField(default=dict)
    status = models.CharField(max_length=12, default="draft", choices=[(v, v.title()) for v in ("draft", "paused", "review", "completed")])
    version = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    invalidated = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)


class ArrowShot(models.Model):
    session = models.ForeignKey(ScoringSession, on_delete=models.CASCADE, related_name="shots")
    position = models.PositiveIntegerField()
    symbol = models.CharField(max_length=8)
    points = models.PositiveSmallIntegerField()
    is_x = models.BooleanField(default=False)
    x = models.FloatField(null=True, blank=True)
    y = models.FloatField(null=True, blank=True)
    spot = models.PositiveSmallIntegerField(null=True, blank=True)
    suggested_symbol = models.CharField(max_length=8, blank=True)
    arrow = models.ForeignKey(PhysicalArrow, null=True, blank=True, on_delete=models.PROTECT)
    arrow_snapshot = models.JSONField(default=dict)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["session", "position"], name="scoring_unique_shot")]


class ScoreChangeAudit(models.Model):
    session = models.ForeignKey(ScoringSession, on_delete=models.CASCADE, related_name="audit")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    at = models.DateTimeField(auto_now_add=True)
    operation = models.CharField(max_length=30)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    reason = models.CharField(max_length=500, blank=True)


class MutationReceipt(models.Model):
    session = models.ForeignKey(ScoringSession, on_delete=models.CASCADE)
    key = models.UUIDField()
    payload = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "key"], name="scoring_retry_key")]


# Advanced equipment extends the legacy identities; it never rewrites score snapshots.
from .component_specs import CATEGORIES, STATUSES, validate_specs


class EquipmentComponent(models.Model):
    owner = models.ForeignKey("accounts.AthleteProfile", on_delete=models.PROTECT, related_name="components")
    category = models.CharField(max_length=20, choices=[(v, v.replace("_", " ").title()) for v in CATEGORIES])
    status = models.CharField(max_length=12, default="active", choices=[(v, v.replace("_", " ").title()) for v in STATUSES])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(status__in=STATUSES), name="component_valid_status"),
                       models.CheckConstraint(condition=models.Q(category__in=CATEGORIES), name="component_valid_category")]

    def __str__(self):
        revision = self.revisions.first()
        return revision.name if revision else f"Component {self.pk}"


class ComponentRevision(models.Model):
    component = models.ForeignKey(EquipmentComponent, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    owner_at_revision = models.ForeignKey("accounts.AthleteProfile", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=100)
    manufacturer = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    serial_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(max_length=2000, blank=True)
    specs = models.JSONField(default=dict, blank=True)
    schema_version = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["component", "number"], name="component_revision_number")]

    def clean(self):
        if not self.name.strip():
            raise ValidationError("Enter a component name.")
        validate_specs(self.component.category, self.specs)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Component revisions are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Component revisions are immutable.")

    def __str__(self):
        return f"{self.name} / revision {self.number}"


class EquipmentActivity(models.Model):
    owner = models.ForeignKey("accounts.AthleteProfile", on_delete=models.PROTECT)
    component = models.ForeignKey(EquipmentComponent, null=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    event = models.CharField(max_length=50)
    at = models.DateTimeField(auto_now_add=True)
    detail = models.JSONField(default=dict)

    class Meta:
        ordering = ["-at", "-pk"]


class BowConfiguration(models.Model):
    owner = models.ForeignKey("accounts.AthleteProfile", on_delete=models.PROTECT, related_name="bow_configurations")
    active = models.BooleanField(default=True)

    def __str__(self):
        revision = self.revisions.first()
        return revision.name if revision else f"Configuration {self.pk}"


class ConfigurationRevision(models.Model):
    configuration = models.ForeignKey(BowConfiguration, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    name = models.CharField(max_length=100)
    division = models.CharField(max_length=20, choices=DIVISIONS)
    preferred_arrows = models.ForeignKey(Equipment, null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    rule_version = models.PositiveSmallIntegerField(default=1)
    acknowledged = models.BooleanField(default=False)
    components = models.ManyToManyField(ComponentRevision, through="ConfigurationMember")

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["configuration", "number"], name="configuration_revision_number")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Configuration revisions are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} / version {self.number}"


class ConfigurationMember(models.Model):
    revision = models.ForeignKey(ConfigurationRevision, on_delete=models.PROTECT, related_name="members")
    component = models.ForeignKey(EquipmentComponent, on_delete=models.PROTECT)
    component_revision = models.ForeignKey(ComponentRevision, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["revision", "component"], name="configuration_unique_component")]

    def clean(self):
        if self.component_revision.component_id != self.component_id:
            raise ValidationError("Component revision identity mismatch.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Configuration membership is immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class AthleteEquipmentDefaults(models.Model):
    athlete = models.OneToOneField("accounts.AthleteProfile", on_delete=models.PROTECT)
    configuration = models.ForeignKey(BowConfiguration, null=True, blank=True, on_delete=models.PROTECT)


class EquipmentShare(models.Model):
    component = models.ForeignKey(EquipmentComponent, on_delete=models.PROTECT, related_name="shares")
    owner = models.ForeignKey("accounts.AthleteProfile", on_delete=models.PROTECT, related_name="equipment_shares_sent")
    recipient = models.ForeignKey("accounts.AthleteProfile", on_delete=models.PROTECT, related_name="equipment_shares_received")
    status = models.CharField(max_length=10, default="pending", choices=[(s, s.title()) for s in ("pending", "approved", "revoked", "rejected")])
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="equipment_shares_initiated")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="equipment_shares_decided")
    at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True)
    permit_photos = models.BooleanField(default=False)


class EquipmentTransfer(models.Model):
    component = models.ForeignKey(EquipmentComponent, on_delete=models.PROTECT, related_name="transfers")
    sender = models.ForeignKey("accounts.AthleteProfile", on_delete=models.PROTECT, related_name="equipment_transfers_sent")
    recipient = models.ForeignKey("accounts.AthleteProfile", on_delete=models.PROTECT, related_name="equipment_transfers_received")
    status = models.CharField(max_length=10, default="pending", choices=[(s, s.title()) for s in ("pending", "accepted", "cancelled", "rejected")])
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="equipment_transfers_initiated")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="equipment_transfers_decided")
    at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["component"], condition=models.Q(status="pending"), name="component_one_pending_transfer")]
