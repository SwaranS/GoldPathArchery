"""Pydantic v2 request and response schemas for the Training Plans module."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class BowDivision(str, Enum):
    """World Archery bow divisions."""

    RECURVE = "recurve"
    COMPOUND = "compound"
    BAREBOW = "barebow"
    TRADITIONAL = "traditional"


class PlanArchetype(str, Enum):
    """Macrocycle training plan archetypes."""

    COMPETITION_PEAK = "competition_peak"
    POUNDAGE_INCREASE = "poundage_increase"
    FORM_REBUILD = "form_rebuild"
    SEASON_TRANSITION = "season_transition"
    STAMINA_BUILDER = "stamina_builder"
    RETURN_TO_SHOOTING = "return_to_shooting"


class RoundFormat(str, Enum):
    """World Archery standard target & indoor round formats."""

    WA_720_70M = "wa_720_70m"
    WA_720_60M = "wa_720_60m"
    WA_720_50M = "wa_720_50m"
    WA_1440 = "wa_1440"
    WA_18M_INDOOR = "wa_18m_indoor"
    WA_25M_INDOOR = "wa_25m_indoor"
    VEGAS_300 = "vegas_300"
    FIELD_24_TARGET = "field_24_target"
    BLANK_BALE = "blank_bale"


class FormFault(str, Enum):
    """Biomechanical & execution faults detected via coach review or CV analysis."""

    COLLAPSING_BOW_ARM = "collapsing_bow_arm"
    PLUCKING_RELEASE = "plucking_release"
    TARGET_PANIC_FREEZING = "target_panic_freezing"
    HIGH_BOW_SHOULDER = "high_bow_shoulder"
    INCONSISTENT_ANCHOR = "inconsistent_anchor"
    CANTING_BOW = "canting_bow"
    BACK_TENSION_LOSS = "back_tension_loss"
    OVER_AIMING = "over_aiming"
    GRIP_TORQUE = "grip_torque"
    PREMATURE_LETDOWN = "premature_letdown"


class SessionBlockType(str, Enum):
    """Ordered building blocks within a single archery training session."""

    WARMUP = "warmup"
    TECHNICAL_BLANK_BALE = "technical_blank_bale"
    SCORED_DISTANCE = "scored_distance"
    SPT_CONDITIONING = "spt_conditioning"
    MATCH_SIMULATION = "match_simulation"
    COOLDOWN = "cooldown"


class PlanStatus(str, Enum):
    """Lifecycle status of a TrainingPlan."""

    DRAFT = "draft"
    GENERATING = "generating"
    ACTIVE = "active"
    RECALIBRATING = "recalibrating"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class SessionStatus(str, Enum):
    """Lifecycle status of a TrainingSession."""

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    MODIFIED = "modified"


class MatchScoringSystem(str, Enum):
    """World Archery division-specific match play scoring format."""

    SET_SYSTEM = "set_system"
    CUMULATIVE_15_ARROW = "cumulative_15_arrow"


ArrowRingSymbol = Literal["X", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "M"]

ARROW_RING_POINTS: dict[str, int] = {
    "X": 10,
    "10": 10,
    "9": 9,
    "8": 8,
    "7": 7,
    "6": 6,
    "5": 5,
    "4": 4,
    "3": 3,
    "2": 2,
    "1": 1,
    "M": 0,
}


class GranularEndScore(BaseModel):
    """Granular end-by-end arrow ring values (WA Law #1: never store only aggregated integer scores)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    end_number: int = Field(ge=1, le=36, description="1-based end index within the scored block.")
    arrows: list[ArrowRingSymbol] = Field(
        min_length=1,
        max_length=12,
        description="Individual arrow ring symbols ('X', '10', '9', ..., '1', 'M').",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def end_score(self) -> int:
        return sum(ARROW_RING_POINTS[a] for a in self.arrows)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def x_count(self) -> int:
        return sum(1 for a in self.arrows if a == "X")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ten_plus_x_count(self) -> int:
        return sum(1 for a in self.arrows if a in ("X", "10"))


def compute_granular_score_metrics(ends: list[GranularEndScore]) -> dict[str, float | int]:
    """Compute X-to-10 ratio and 1st-half vs. 2nd-half score decay from granular end data."""
    if not ends:
        return {
            "total_score": 0,
            "total_arrows": 0,
            "x_count": 0,
            "ten_plus_x_count": 0,
            "x_to_10_ratio": 0.0,
            "first_half_score": 0,
            "second_half_score": 0,
            "first_half_vs_second_half_decay_pct": 0.0,
        }

    ordered_ends = sorted(ends, key=lambda e: e.end_number)
    total_score = sum(e.end_score for e in ordered_ends)
    total_arrows = sum(len(e.arrows) for e in ordered_ends)
    x_count = sum(e.x_count for e in ordered_ends)
    ten_plus_x_count = sum(e.ten_plus_x_count for e in ordered_ends)
    x_to_10_ratio = round(x_count / ten_plus_x_count, 4) if ten_plus_x_count > 0 else 0.0

    midpoint = len(ordered_ends) // 2
    if midpoint > 0:
        first_half = ordered_ends[:midpoint]
        second_half = ordered_ends[midpoint : midpoint * 2]
        first_half_score = sum(e.end_score for e in first_half)
        second_half_score = sum(e.end_score for e in second_half)
        if first_half_score > 0:
            decay_pct = round(((first_half_score - second_half_score) / first_half_score) * 100.0, 2)
        else:
            decay_pct = 0.0
    else:
        first_half_score = total_score
        second_half_score = total_score
        decay_pct = 0.0

    return {
        "total_score": total_score,
        "total_arrows": total_arrows,
        "x_count": x_count,
        "ten_plus_x_count": ten_plus_x_count,
        "x_to_10_ratio": x_to_10_ratio,
        "first_half_score": first_half_score,
        "second_half_score": second_half_score,
        "first_half_vs_second_half_decay_pct": decay_pct,
    }


class MatchPlayFormatSpec(BaseModel):
    """Division-specific World Archery match-play specification (WA Law #2)."""

    model_config = ConfigDict(from_attributes=True)

    scoring_system: MatchScoringSystem
    arrows_per_end_or_set: int = 3
    target_set_points_to_win: Optional[int] = None
    max_ends: int = 5
    total_match_arrows: int = 15
    inner_10_active_18m: bool = False

    @classmethod
    def for_division(cls, division: BowDivision, distance_m: int = 70) -> "MatchPlayFormatSpec":
        if division == BowDivision.COMPOUND:
            return cls(
                scoring_system=MatchScoringSystem.CUMULATIVE_15_ARROW,
                arrows_per_end_or_set=3,
                target_set_points_to_win=None,
                max_ends=5,
                total_match_arrows=15,
                inner_10_active_18m=(distance_m <= 18),
            )
        # Recurve, Barebow (and Traditional fallback) use WA Set System
        return cls(
            scoring_system=MatchScoringSystem.SET_SYSTEM,
            arrows_per_end_or_set=3,
            target_set_points_to_win=6,
            max_ends=5,
            total_match_arrows=15,
            inner_10_active_18m=False,
        )


# ---------------------------------------------------------------------------
# Intake Schemas
# ---------------------------------------------------------------------------


class DayAccess(BaseModel):
    """Range and duration constraints for a specific training day of the week."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    day_of_week: int = Field(
        ge=0,
        le=6,
        description="Day of week where 0=Monday and 6=Sunday.",
    )
    available_mins: int = Field(
        default=90,
        ge=15,
        le=360,
        validation_alias=AliasChoices("available_mins", "duration_mins", "duration_minutes"),
        description="Available training duration in minutes.",
    )
    max_distance_m: int = Field(
        default=70,
        ge=3,
        le=90,
        validation_alias=AliasChoices("max_distance_m", "max_distance_meters"),
        description="Maximum shooting distance available at the range on this day (meters).",
    )
    blank_bale_only: bool = Field(
        default=False,
        description="True if only short-range blank bale (<=5m) is available on this day.",
    )

    @property
    def max_distance_meters(self) -> int:
        return self.max_distance_m

    @property
    def duration_minutes(self) -> int:
        return self.available_mins

    @property
    def duration_mins(self) -> int:
        return self.available_mins

    @model_validator(mode="after")
    def sync_blank_bale_flag(self) -> "DayAccess":
        if self.max_distance_m <= 5:
            self.blank_bale_only = True
        return self


class AthleteBaselineInput(BaseModel):
    """Current physical, volume, scoring, and technical baseline for an athlete."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    bow_division: BowDivision
    current_draw_weight_lbs: float = Field(gt=10.0, le=80.0)
    target_draw_weight_lbs: Optional[float] = Field(default=None, gt=10.0, le=80.0)
    current_weekly_arrow_volume: int = Field(
        ge=0,
        le=3000,
        validation_alias=AliasChoices("current_weekly_arrow_volume", "weekly_arrow_volume"),
        description="Baseline weekly arrow volume over the past 4 weeks.",
    )
    recent_average_arrow_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    recent_x_to_10_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    first_half_vs_second_half_decay_pct: Optional[float] = Field(default=None, ge=-100.0, le=100.0)
    active_form_faults: list[FormFault] = Field(
        default_factory=list,
        validation_alias=AliasChoices("active_form_faults", "identified_faults", "form_faults"),
    )
    pain_flags: dict[str, int] = Field(
        default_factory=dict,
        description="Baseline anatomical soreness/pain ratings (0-10) keyed by body region.",
    )
    available_days: list[DayAccess] = Field(
        min_length=1,
        max_length=7,
        validation_alias=AliasChoices("available_days", "weekly_schedule"),
        description="Weekly schedule of available training days and range distances.",
    )

    @property
    def identified_faults(self) -> list[FormFault]:
        return self.active_form_faults

    @property
    def weekly_schedule(self) -> list[DayAccess]:
        return self.available_days

    @field_validator("available_days")
    @classmethod
    def validate_unique_days(cls, v: list[DayAccess]) -> list[DayAccess]:
        days = [item.day_of_week for item in v]
        if len(days) != len(set(days)):
            raise ValueError("Duplicate day_of_week entries are not allowed in available_days.")
        return sorted(v, key=lambda d: d.day_of_week)

    @model_validator(mode="after")
    def default_target_draw_weight(self) -> "AthleteBaselineInput":
        if self.target_draw_weight_lbs is None:
            self.target_draw_weight_lbs = self.current_draw_weight_lbs
        return self


class TrainingGoalInput(BaseModel):
    """Macrocycle training objective, round format, and target dates."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    primary_archetype: PlanArchetype
    secondary_archetype: Optional[PlanArchetype] = None
    round_format: RoundFormat = Field(
        default=RoundFormat.WA_720_70M,
        validation_alias=AliasChoices("round_format", "target_round"),
    )
    start_date: date = Field(default_factory=date.today)
    target_event_date: date = Field(
        validation_alias=AliasChoices("target_event_date", "target_date"),
    )
    competition_tier: Literal["A", "B", "C"] = Field(
        default="A",
        description="Event priority tier ('A' = major championship with 6-week poundage lockout).",
    )
    target_score: Optional[int] = Field(default=None, ge=0, le=1440)
    target_draw_weight_lbs: Optional[float] = Field(default=None, gt=10.0, le=80.0)
    poundage_step_up_date: Optional[date] = Field(
        default=None,
        description="Optional date when a mechanical draw weight increase is scheduled.",
    )

    @property
    def target_date(self) -> date:
        return self.target_event_date

    @model_validator(mode="after")
    def validate_date_window(self) -> "TrainingGoalInput":
        if self.target_event_date <= self.start_date:
            raise ValueError("target_event_date must be strictly after start_date.")
        return self


class GeneratePlanRequest(BaseModel):
    """Top-level payload for POST /api/v1/training-plans/generate."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    athlete_id: UUID
    coach_id: Optional[UUID] = None
    baseline: AthleteBaselineInput
    goal: TrainingGoalInput

    @model_validator(mode="after")
    def validate_poundage_lockout(self) -> "GeneratePlanRequest":
        """Enforce WA Law #3 (Poundage Lockout): prohibit bow weight increases within 6 weeks of an A-tier event."""
        effective_target_lbs = (
            self.goal.target_draw_weight_lbs
            if self.goal.target_draw_weight_lbs is not None
            else (self.baseline.target_draw_weight_lbs or self.baseline.current_draw_weight_lbs)
        )
        self.baseline.target_draw_weight_lbs = effective_target_lbs
        self.goal.target_draw_weight_lbs = effective_target_lbs

        has_poundage_archetype = (
            self.goal.primary_archetype == PlanArchetype.POUNDAGE_INCREASE
            or self.goal.secondary_archetype == PlanArchetype.POUNDAGE_INCREASE
        )
        is_poundage_increase = (
            effective_target_lbs > self.baseline.current_draw_weight_lbs or has_poundage_archetype
        )
        days_until_event = (self.goal.target_event_date - self.goal.start_date).days

        if is_poundage_increase and (
            self.goal.competition_tier == "A"
            or self.goal.primary_archetype == PlanArchetype.COMPETITION_PEAK
            or self.goal.secondary_archetype == PlanArchetype.COMPETITION_PEAK
        ):
            if self.goal.poundage_step_up_date is not None:
                days_from_step_to_event = (self.goal.target_event_date - self.goal.poundage_step_up_date).days
                if days_from_step_to_event < 42:
                    raise ValueError(
                        "Poundage Lockout Violation: Mechanical draw weight increase cannot be scheduled "
                        "within 6 weeks (42 days) of an A-tier competition."
                    )
            elif (
                (
                    self.goal.primary_archetype == PlanArchetype.COMPETITION_PEAK
                    or self.goal.secondary_archetype == PlanArchetype.POUNDAGE_INCREASE
                )
                and days_until_event < 42
            ):
                raise ValueError(
                    "Poundage Lockout Violation: Cannot schedule Poundage Increase or raise draw weight "
                    "within 6 weeks (42 days) of a Competition Peak / A-tier competition."
                )
        return self


# ---------------------------------------------------------------------------
# Response & Live Session Runner Schemas
# ---------------------------------------------------------------------------


class DrillCatalogSchema(BaseModel):
    """Serialized drill metadata from DrillCatalog."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    block_type: SessionBlockType
    bow_divisions: list[BowDivision]
    faults_addressed: list[FormFault] = Field(default_factory=list)
    min_distance_m: int = Field(ge=0, le=90)
    instructions: str
    default_arrows: int = Field(ge=0, le=300)
    spt_hold_seconds: Optional[int] = Field(default=None, ge=0, le=300)
    spt_rest_seconds: Optional[int] = Field(default=None, ge=0, le=600)
    requires_cv_video: bool = False


class SessionBlockResponse(BaseModel):
    """Detailed view of a single prescribed block inside a TrainingSession."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    drill_id: UUID
    block_order: int
    block_type: SessionBlockType
    prescribed_arrows: int
    actual_arrows: int = 0
    distance_m: int
    target_face_cm: Optional[int] = None
    linked_scorecard_id: Optional[UUID] = None
    linked_cv_job_id: Optional[UUID] = None
    completed: bool = False
    drill: Optional[DrillCatalogSchema] = None
    match_play_spec: Optional[MatchPlayFormatSpec] = None


class TrainingSessionDetailResponse(BaseModel):
    """Full response for a single training session and its ordered drill blocks."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    microcycle_id: UUID
    scheduled_date: date
    max_distance_m: int
    duration_mins: int
    status: SessionStatus
    rpe_score: Optional[int] = None
    pain_flags_json: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    blocks: list[SessionBlockResponse] = Field(default_factory=list)


class MesocycleRoadmapItem(BaseModel):
    """Mesocycle phase summary within a TrainingPlanRoadmapResponse."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: UUID
    phase_name: str
    start_week: int
    end_week: int
    pillar_ratios_json: dict[str, float] = Field(default_factory=dict)


class MicrocycleRoadmapItem(BaseModel):
    """Weekly microcycle summary within a TrainingPlanRoadmapResponse."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: UUID
    mesocycle_id: UUID
    week_number: int
    target_arrows: int
    actual_arrows: int = 0
    is_deload_week: bool = False
    coach_locked: bool = False
    sessions: list[TrainingSessionDetailResponse] = Field(default_factory=list)


class MicrocycleAdjustmentDiff(BaseModel):
    """Proposed microcycle volume/drill adjustment during smart recalibration."""

    model_config = ConfigDict(from_attributes=True)

    week_number: int
    previous_target_arrows: int
    proposed_target_arrows: int
    is_deload_week: bool = False
    blank_bale_ratio: Optional[float] = None
    rationale: str


class RecalibrationProposalResponse(BaseModel):
    """Smart recalibration evaluation and proposed microcycle mutations."""

    model_config = ConfigDict(from_attributes=True)

    plan_id: UUID
    recalibration_flag: bool
    recalibration_reason: Optional[str] = None
    triggers_detected: list[str] = Field(default_factory=list)
    analytics_summary: dict[str, Any] = Field(default_factory=dict)
    proposed_adjustments: list[MicrocycleAdjustmentDiff] = Field(default_factory=list)
    coach_locked_weeks_skipped: list[int] = Field(default_factory=list)


class TrainingPlanRoadmapResponse(BaseModel):
    """Complete periodized roadmap response for a TrainingPlan."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    athlete_id: UUID
    coach_id: Optional[UUID] = None
    primary_archetype: PlanArchetype
    secondary_archetype: Optional[PlanArchetype] = None
    start_date: date
    target_date: date
    status: PlanStatus
    baseline_json: dict[str, Any] = Field(default_factory=dict)
    goal_json: dict[str, Any] = Field(default_factory=dict)
    recalibration_flag: bool = False
    recalibration_reason: Optional[str] = None
    mesocycles: list[MesocycleRoadmapItem] = Field(default_factory=list)
    microcycles: list[MicrocycleRoadmapItem] = Field(default_factory=list)
    weekly_planned_arrows: list[int] = Field(default_factory=list)
    weekly_actual_arrows: list[int] = Field(default_factory=list)
    pillar_breakdown_pct: dict[str, float] = Field(default_factory=dict)
    active_recalibration_proposal: Optional[RecalibrationProposalResponse] = None


class SessionBlockLogUpdate(BaseModel):
    """Per-block completion and granular arrow score log submitted by the live session runner (Mode B)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    block_id: Optional[UUID] = None
    block_order: Optional[int] = None
    actual_arrows: int = Field(default=0, ge=0, le=500)
    completed: bool = True
    linked_scorecard_id: Optional[UUID] = Field(
        default=None,
        validation_alias=AliasChoices("linked_scorecard_id", "scorecard_id"),
    )
    linked_cv_job_id: Optional[UUID] = Field(
        default=None,
        validation_alias=AliasChoices("linked_cv_job_id", "cv_job_id"),
    )
    spt_hold_reps: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        validation_alias=AliasChoices("spt_hold_reps", "spt_completed_reps"),
    )
    cv_form_degradation_deg: Optional[float] = Field(default=None, ge=0.0, le=90.0)
    ends: list[GranularEndScore] = Field(
        default_factory=list,
        description="Granular end-by-end arrow values ('X', '10', ..., 'M') for WA Law #1 compliance.",
    )
    detected_faults: list[FormFault] = Field(default_factory=list)


class SessionLogUpdateRequest(BaseModel):
    """Payload to record session completion in Mode A (Quick-Log) or Mode B (Live Runner)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    status: SessionStatus = SessionStatus.COMPLETED
    actual_arrows: Optional[int] = Field(
        default=None,
        ge=0,
        le=1000,
        description="Mode A Quick-Log session arrow total (distributed across blocks if blocks not provided).",
    )
    rpe_score: Optional[int] = Field(default=None, ge=1, le=10)
    pain_flags_json: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("pain_flags_json", "pain_flags"),
    )
    notes: Optional[str] = None
    blocks: list[SessionBlockLogUpdate] = Field(
        default_factory=list,
        validation_alias=AliasChoices("blocks", "block_updates"),
    )


class ApplyRecalibrationRequest(BaseModel):
    """Optional override payload when applying an approved recalibration proposal."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    approved: bool = True
    adjustments: Optional[list[MicrocycleAdjustmentDiff]] = None


class CoachDrillSwapItem(BaseModel):
    """Instruction for a coach to swap a drill on a specific SessionBlock."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    block_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    block_order: Optional[int] = None
    new_drill_id: UUID = Field(validation_alias=AliasChoices("new_drill_id", "drill_id"))
    prescribed_arrows: Optional[int] = Field(default=None, ge=0, le=300)
    distance_m: Optional[int] = Field(default=None, ge=3, le=90)


class CoachOverrideRequest(BaseModel):
    """Payload for PATCH /api/v1/training-plans/microcycles/{microcycle_id}/coach-override."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    coach_locked: Optional[bool] = None
    target_arrows: Optional[int] = Field(default=None, ge=0, le=3000)
    is_deload_week: Optional[bool] = None
    drill_swaps: list[CoachDrillSwapItem] = Field(default_factory=list)


