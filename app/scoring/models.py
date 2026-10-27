import math
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


DIVISIONS = [(x, x.title()) for x in ("recurve", "compound", "barebow")]


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
            raise ValidationError("Use positive distance, 1–100 ends and 1–36 arrows per end.")


class Equipment(models.Model):
    athlete = models.ForeignKey("accounts.AthleteProfile", on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=[("bow", "Bow"), ("arrow_set", "Arrow set")])
    name = models.CharField(max_length=100)
    division = models.CharField(max_length=20, choices=DIVISIONS, blank=True)
    details = models.TextField(blank=True, max_length=2000)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class PhysicalArrow(models.Model):
    arrow_set = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="arrows")
    identifier = models.CharField(max_length=40)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["arrow_set", "identifier"], name="scoring_arrow_identifier")]

    def clean(self):
        if self.arrow_set_id and self.arrow_set.kind != "arrow_set":
            raise ValidationError("Physical arrows belong to an arrow set.")


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
