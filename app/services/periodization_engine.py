"""Periodization Engine Service for Macrocycle, Microcycle, Session generation & Smart Recalibration."""

from __future__ import annotations

import json
import math
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from app.models.training_plan import (
    DrillCatalog,
    SessionBlock,
    TrainingMesocycle,
    TrainingMicrocycle,
    TrainingPlan,
    TrainingSession,
)
from app.schemas.training_plan import (
    ApplyRecalibrationRequest,
    BowDivision,
    CoachOverrideRequest,
    DayAccess,
    FormFault,
    GeneratePlanRequest,
    MatchPlayFormatSpec,
    MesocycleRoadmapItem,
    MicrocycleAdjustmentDiff,
    MicrocycleRoadmapItem,
    PlanArchetype,
    PlanStatus,
    RecalibrationProposalResponse,
    RoundFormat,
    SessionBlockResponse,
    SessionBlockType,
    SessionLogUpdateRequest,
    SessionStatus,
    TrainingPlanRoadmapResponse,
    TrainingSessionDetailResponse,
)

SEED_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "drill_catalog_seed.json"

# Baseline pillar distributions (Scored / Technical Blank Bale / SPT Conditioning / Match Simulation)
ARCHETYPE_PILLAR_RATIOS: dict[PlanArchetype, dict[str, float]] = {
    PlanArchetype.COMPETITION_PEAK: {
        SessionBlockType.SCORED_DISTANCE.value: 0.45,
        SessionBlockType.TECHNICAL_BLANK_BALE.value: 0.20,
        SessionBlockType.SPT_CONDITIONING.value: 0.15,
        SessionBlockType.MATCH_SIMULATION.value: 0.20,
    },
    PlanArchetype.POUNDAGE_INCREASE: {
        SessionBlockType.SCORED_DISTANCE.value: 0.25,
        SessionBlockType.TECHNICAL_BLANK_BALE.value: 0.40,
        SessionBlockType.SPT_CONDITIONING.value: 0.30,
        SessionBlockType.MATCH_SIMULATION.value: 0.05,
    },
    PlanArchetype.FORM_REBUILD: {
        SessionBlockType.SCORED_DISTANCE.value: 0.20,
        SessionBlockType.TECHNICAL_BLANK_BALE.value: 0.55,
        SessionBlockType.SPT_CONDITIONING.value: 0.20,
        SessionBlockType.MATCH_SIMULATION.value: 0.05,
    },
    PlanArchetype.SEASON_TRANSITION: {
        SessionBlockType.SCORED_DISTANCE.value: 0.35,
        SessionBlockType.TECHNICAL_BLANK_BALE.value: 0.35,
        SessionBlockType.SPT_CONDITIONING.value: 0.20,
        SessionBlockType.MATCH_SIMULATION.value: 0.10,
    },
    PlanArchetype.STAMINA_BUILDER: {
        SessionBlockType.SCORED_DISTANCE.value: 0.50,
        SessionBlockType.TECHNICAL_BLANK_BALE.value: 0.15,
        SessionBlockType.SPT_CONDITIONING.value: 0.25,
        SessionBlockType.MATCH_SIMULATION.value: 0.10,
    },
    PlanArchetype.RETURN_TO_SHOOTING: {
        SessionBlockType.SCORED_DISTANCE.value: 0.20,
        SessionBlockType.TECHNICAL_BLANK_BALE.value: 0.50,
        SessionBlockType.SPT_CONDITIONING.value: 0.25,
        SessionBlockType.MATCH_SIMULATION.value: 0.05,
    },
}

ROUND_FORMAT_SPECS: dict[RoundFormat, tuple[int, int]] = {
    RoundFormat.WA_720_70M: (70, 122),
    RoundFormat.WA_720_60M: (60, 122),
    RoundFormat.WA_720_50M: (50, 80),
    RoundFormat.WA_1440: (70, 122),
    RoundFormat.WA_18M_INDOOR: (18, 40),
    RoundFormat.WA_25M_INDOOR: (25, 60),
    RoundFormat.VEGAS_300: (18, 40),
    RoundFormat.FIELD_24_TARGET: (50, 80),
    RoundFormat.BLANK_BALE: (5, 0),
}

HEAVY_SPT_TITLES = (
    "SPT Power",
    "SPT Endurance",
    "SPT Holding",
)


class PeriodizationEngineService:
    """Generates periodized World Archery training plans and evaluates post-session recalibration."""

    def __init__(
        self,
        db_session: Optional[Any] = None,
        drill_catalog: Optional[list[DrillCatalog]] = None,
    ) -> None:
        self.db_session = db_session
        self.drills: list[DrillCatalog] = drill_catalog or self._load_seed_catalog()
        self._plans_registry: dict[UUID, TrainingPlan] = {}
        self._cv_degradation_registry: dict[UUID, float] = {}

    @staticmethod
    def _load_seed_catalog(seed_path: Path = SEED_CATALOG_PATH) -> list[DrillCatalog]:
        raw_items = json.loads(seed_path.read_text(encoding="utf-8"))
        catalog: list[DrillCatalog] = []
        for item in raw_items:
            catalog.append(
                DrillCatalog(
                    id=UUID(str(item["id"])),
                    title=item["title"],
                    block_type=item["block_type"],
                    bow_divisions=list(item["bow_divisions"]),
                    faults_addressed=list(item.get("faults_addressed", [])),
                    min_distance_m=int(item["min_distance_m"]),
                    instructions=item["instructions"],
                    default_arrows=int(item["default_arrows"]),
                    spt_hold_seconds=item.get("spt_hold_seconds"),
                    spt_rest_seconds=item.get("spt_rest_seconds"),
                    requires_cv_video=bool(item.get("requires_cv_video", False)),
                )
            )
        return catalog

    def register_plan(self, plan: TrainingPlan) -> None:
        """Store or update a plan in the in-memory registry for fast lookup and testing."""
        self._plans_registry[plan.id] = plan

    def register_cv_job_degradation(self, cv_job_id: UUID, degradation_degrees: float) -> None:
        """Record CV biomechanical angle degradation (in degrees) for a linked CV job ID."""
        self._cv_degradation_registry[cv_job_id] = degradation_degrees

    def compute_pillar_ratios(
        self,
        primary: PlanArchetype,
        secondary: Optional[PlanArchetype] = None,
    ) -> dict[str, float]:
        """Compute normalized pillar distribution for primary and optional secondary archetypes."""
        base = dict(ARCHETYPE_PILLAR_RATIOS[primary])
        if secondary is not None and secondary != primary:
            sec = ARCHETYPE_PILLAR_RATIOS[secondary]
            for key in base:
                base[key] = round(base[key] * 0.75 + sec[key] * 0.25, 4)
        total = sum(base.values()) or 1.0
        return {k: round(v / total, 4) for k, v in base.items()}

    def create_initial_plan(self, request: GeneratePlanRequest) -> TrainingPlan:
        """Create and register the initial TrainingPlan record (status=GENERATING) before background build."""
        plan = TrainingPlan(
            id=uuid.uuid4(),
            athlete_id=request.athlete_id,
            coach_id=request.coach_id,
            primary_archetype=request.goal.primary_archetype.value,
            secondary_archetype=(
                request.goal.secondary_archetype.value if request.goal.secondary_archetype else None
            ),
            start_date=request.goal.start_date,
            target_date=request.goal.target_event_date,
            status=PlanStatus.GENERATING.value,
            baseline_json=request.baseline.model_dump(mode="json"),
            goal_json=request.goal.model_dump(mode="json"),
            recalibration_flag=False,
            recalibration_reason=None,
            mesocycles=[],
            microcycles=[],
        )
        self.register_plan(plan)
        return plan

    def generate_full_plan(self, plan_id: UUID, request: GeneratePlanRequest) -> TrainingPlan:
        """Background worker task: build full Macrocycle -> Mesocycle -> Microcycle -> Session -> Block tree."""
        return self.generate_plan(request, plan_id=plan_id)

    def generate_plan(
        self,
        request: GeneratePlanRequest,
        plan_id: Optional[UUID] = None,
    ) -> TrainingPlan:
        """Build a complete Macrocycle -> Mesocycle -> Microcycle -> Session -> Block hierarchy."""
        start_date = request.goal.start_date
        target_date = request.goal.target_event_date
        total_days = max(7, (target_date - start_date).days)
        total_weeks = max(1, math.ceil(total_days / 7))

        effective_plan_id = plan_id or uuid.uuid4()
        base_ratios = self.compute_pillar_ratios(
            request.goal.primary_archetype,
            request.goal.secondary_archetype,
        )

        plan = self._plans_registry.get(effective_plan_id)
        if plan is None:
            plan = TrainingPlan(
                id=effective_plan_id,
                athlete_id=request.athlete_id,
                coach_id=request.coach_id,
                primary_archetype=request.goal.primary_archetype.value,
                secondary_archetype=(
                    request.goal.secondary_archetype.value if request.goal.secondary_archetype else None
                ),
                start_date=start_date,
                target_date=target_date,
                status=PlanStatus.ACTIVE.value,
                baseline_json=request.baseline.model_dump(mode="json"),
                goal_json=request.goal.model_dump(mode="json"),
                recalibration_flag=False,
                recalibration_reason=None,
                mesocycles=[],
                microcycles=[],
            )
        else:
            plan.status = PlanStatus.ACTIVE.value
            plan.mesocycles = []
            plan.microcycles = []

        mesocycles = self._build_mesocycles(
            plan_id=effective_plan_id,
            primary_archetype=request.goal.primary_archetype,
            total_weeks=total_weeks,
            base_ratios=base_ratios,
        )
        plan.mesocycles = mesocycles

        weekly_volumes = self._compute_weekly_volumes(
            baseline_arrows=request.baseline.current_weekly_arrow_volume,
            total_weeks=total_weeks,
            primary_archetype=request.goal.primary_archetype,
        )

        poundage_step_weeks = self._identify_poundage_step_weeks(
            request=request,
            total_weeks=total_weeks,
        )

        for week_num in range(1, total_weeks + 1):
            meso = self._find_mesocycle_for_week(mesocycles, week_num)
            target_arrows, is_deload = weekly_volumes[week_num - 1]
            is_taper_week = (
                request.goal.primary_archetype == PlanArchetype.COMPETITION_PEAK
                and total_weeks >= 3
                and week_num >= total_weeks - 1
            )
            is_poundage_adaptation = week_num in poundage_step_weeks

            microcycle_id = uuid.uuid4()
            microcycle = TrainingMicrocycle(
                id=microcycle_id,
                plan_id=effective_plan_id,
                mesocycle_id=meso.id,
                week_number=week_num,
                target_arrows=target_arrows,
                actual_arrows=0,
                is_deload_week=is_deload,
                coach_locked=False,
                sessions=[],
            )

            week_start_date = start_date + timedelta(days=(week_num - 1) * 7)
            sessions = self._build_sessions_for_week(
                microcycle=microcycle,
                mesocycle=meso,
                week_start_date=week_start_date,
                target_date=target_date,
                request=request,
                is_taper_week=is_taper_week,
                is_poundage_adaptation=is_poundage_adaptation,
            )
            microcycle.sessions = sessions
            # Synchronize microcycle target_arrows with sum of prescribed session arrows
            prescribed_sum = sum(
                b.prescribed_arrows for s in sessions for b in s.blocks
            )
            if prescribed_sum > 0:
                microcycle.target_arrows = prescribed_sum

            meso.microcycles.append(microcycle)
            plan.microcycles.append(microcycle)

        self.register_plan(plan)
        return plan

    def _build_mesocycles(
        self,
        plan_id: UUID,
        primary_archetype: PlanArchetype,
        total_weeks: int,
        base_ratios: dict[str, float],
    ) -> list[TrainingMesocycle]:
        """Construct Backward-Looking (Competition Peak) or Forward-Looking (General Block) mesocycles."""
        mesocycles: list[TrainingMesocycle] = []

        if primary_archetype == PlanArchetype.COMPETITION_PEAK:
            # Backward-Looking timeline anchored from target_event_date
            if total_weeks <= 2:
                taper_ratios = self._adjust_ratios_for_taper(base_ratios)
                mesocycles.append(
                    TrainingMesocycle(
                        id=uuid.uuid4(),
                        plan_id=plan_id,
                        phase_name="Competition Taper & Peak (Backward-Anchored)",
                        start_week=1,
                        end_week=total_weeks,
                        pillar_ratios_json=taper_ratios,
                        microcycles=[],
                    )
                )
                return mesocycles

            taper_start = total_weeks - 1
            remaining_weeks = taper_start - 1
            if remaining_weeks <= 3:
                mesocycles.append(
                    TrainingMesocycle(
                        id=uuid.uuid4(),
                        plan_id=plan_id,
                        phase_name="Pre-Competition Specific Prep (Backward-Anchored)",
                        start_week=1,
                        end_week=remaining_weeks,
                        pillar_ratios_json=base_ratios,
                        microcycles=[],
                    )
                )
            else:
                split_week = max(1, remaining_weeks // 2)
                foundation_ratios = {
                    SessionBlockType.SCORED_DISTANCE.value: round(base_ratios[SessionBlockType.SCORED_DISTANCE.value] - 0.05, 4),
                    SessionBlockType.TECHNICAL_BLANK_BALE.value: round(base_ratios[SessionBlockType.TECHNICAL_BLANK_BALE.value] + 0.05, 4),
                    SessionBlockType.SPT_CONDITIONING.value: round(base_ratios[SessionBlockType.SPT_CONDITIONING.value] + 0.05, 4),
                    SessionBlockType.MATCH_SIMULATION.value: max(
                        0.05,
                        round(base_ratios[SessionBlockType.MATCH_SIMULATION.value] - 0.05, 4),
                    ),
                }
                mesocycles.append(
                    TrainingMesocycle(
                        id=uuid.uuid4(),
                        plan_id=plan_id,
                        phase_name="Specific Volume & Technical Base (Backward-Anchored)",
                        start_week=1,
                        end_week=split_week,
                        pillar_ratios_json=foundation_ratios,
                        microcycles=[],
                    )
                )
                mesocycles.append(
                    TrainingMesocycle(
                        id=uuid.uuid4(),
                        plan_id=plan_id,
                        phase_name="Pre-Competition Match & Tournament Prep (Backward-Anchored)",
                        start_week=split_week + 1,
                        end_week=remaining_weeks,
                        pillar_ratios_json=base_ratios,
                        microcycles=[],
                    )
                )

            taper_ratios = self._adjust_ratios_for_taper(base_ratios)
            mesocycles.append(
                TrainingMesocycle(
                    id=uuid.uuid4(),
                    plan_id=plan_id,
                    phase_name="Competition Taper & Peak (Backward-Anchored)",
                    start_week=taper_start,
                    end_week=total_weeks,
                    pillar_ratios_json=taper_ratios,
                    microcycles=[],
                )
            )
            return mesocycles

        # Forward-Looking timeline for General Block archetypes
        if total_weeks <= 4:
            mesocycles.append(
                TrainingMesocycle(
                    id=uuid.uuid4(),
                    plan_id=plan_id,
                    phase_name=f"Forward Block — {primary_archetype.value.replace('_', ' ').title()}",
                    start_week=1,
                    end_week=total_weeks,
                    pillar_ratios_json=base_ratios,
                    microcycles=[],
                )
            )
            return mesocycles

        phase1_end = max(2, total_weeks // 3)
        phase2_end = max(phase1_end + 1, (2 * total_weeks) // 3)

        mesocycles.append(
            TrainingMesocycle(
                id=uuid.uuid4(),
                plan_id=plan_id,
                phase_name="Phase 1: Technical & Structural Adaptation (Forward-Looking)",
                start_week=1,
                end_week=phase1_end,
                pillar_ratios_json=base_ratios,
                microcycles=[],
            )
        )
        mesocycles.append(
            TrainingMesocycle(
                id=uuid.uuid4(),
                plan_id=plan_id,
                phase_name="Phase 2: Progressive Load & Conditioning (Forward-Looking)",
                start_week=phase1_end + 1,
                end_week=phase2_end,
                pillar_ratios_json=base_ratios,
                microcycles=[],
            )
        )
        if phase2_end < total_weeks:
            mesocycles.append(
                TrainingMesocycle(
                    id=uuid.uuid4(),
                    plan_id=plan_id,
                    phase_name="Phase 3: Consolidation & Performance Transfer (Forward-Looking)",
                    start_week=phase2_end + 1,
                    end_week=total_weeks,
                    pillar_ratios_json=base_ratios,
                    microcycles=[],
                )
            )
        return mesocycles

    @staticmethod
    def _adjust_ratios_for_taper(base_ratios: dict[str, float]) -> dict[str, float]:
        """Strip heavy SPT conditioning during competition taper and reallocate to scored/match feel."""
        spt_share = base_ratios.get(SessionBlockType.SPT_CONDITIONING.value, 0.15)
        return {
            SessionBlockType.SCORED_DISTANCE.value: round(
                base_ratios.get(SessionBlockType.SCORED_DISTANCE.value, 0.45) + spt_share * 0.5,
                4,
            ),
            SessionBlockType.TECHNICAL_BLANK_BALE.value: round(
                base_ratios.get(SessionBlockType.TECHNICAL_BLANK_BALE.value, 0.20),
                4,
            ),
            SessionBlockType.SPT_CONDITIONING.value: 0.0,
            SessionBlockType.MATCH_SIMULATION.value: round(
                base_ratios.get(SessionBlockType.MATCH_SIMULATION.value, 0.20) + spt_share * 0.5,
                4,
            ),
        }

    def _compute_weekly_volumes(
        self,
        baseline_arrows: int,
        total_weeks: int,
        primary_archetype: PlanArchetype,
    ) -> list[tuple[int, bool]]:
        """
        Compute (target_arrows, is_deload_week) for each week enforcing:
        - <= 15% weekly arrow volume increase during progressive overload phases.
        - 3:1 Step-Loading rule: every 4th week reduces volume by 25%-30% (0.72x).
        - Competition Peak Taper Window: Week -2 (-30%) and Week -1 (-45%) from peak reference load.
        """
        seed_volume = max(90, baseline_arrows if baseline_arrows > 0 else 180)
        volumes: list[tuple[int, bool]] = []

        taper_start_week = (
            total_weeks - 1
            if (primary_archetype == PlanArchetype.COMPETITION_PEAK and total_weeks >= 3)
            else total_weeks + 1
        )

        current_loading_volume = seed_volume
        prev_week_volume = seed_volume

        for week_num in range(1, total_weeks + 1):
            if week_num >= taper_start_week:
                # Backward-Looking Competition Taper Window
                if week_num == total_weeks - 1:
                    # Week -2: 30% reduction from peak loading reference
                    taper_w2 = max(60, int(round(current_loading_volume * 0.70)))
                    volumes.append((taper_w2, False))
                    prev_week_volume = taper_w2
                else:
                    # Week -1: 45% reduction from peak loading reference
                    taper_w1 = max(48, int(round(current_loading_volume * 0.55)))
                    volumes.append((taper_w1, False))
                    prev_week_volume = taper_w1
                continue

            if week_num == 1:
                volumes.append((current_loading_volume, False))
                prev_week_volume = current_loading_volume
            elif week_num % 4 == 0:
                # 3:1 Step-Loading Deload/Assessment week: -28% volume (strictly within 25%-30% reduction)
                deload_arrows = max(60, int(round(current_loading_volume * 0.72)))
                volumes.append((deload_arrows, True))
                prev_week_volume = deload_arrows
            else:
                # Progressive loading week: never increase by more than 15% over previous loading week
                # After a deload week (week_num % 4 == 1), resume from pre-deload loading baseline (+10%)
                if (week_num - 1) % 4 == 0:
                    proposed = int(math.floor(current_loading_volume * 1.10))
                else:
                    proposed = int(math.floor(prev_week_volume * 1.12))
                    max_allowed = int(math.floor(prev_week_volume * 1.15))
                    proposed = min(proposed, max_allowed)

                max_from_loading = int(math.floor(current_loading_volume * 1.15))
                next_volume = min(proposed, max_from_loading)
                current_loading_volume = next_volume
                prev_week_volume = next_volume
                volumes.append((next_volume, False))

        return volumes

    @staticmethod
    def _identify_poundage_step_weeks(
        request: GeneratePlanRequest,
        total_weeks: int,
    ) -> set[int]:
        """Identify microcycle week numbers requiring >=50% blank-bale poundage step-up adaptation."""
        target_lbs = request.baseline.target_draw_weight_lbs or request.baseline.current_draw_weight_lbs
        has_step_up = (
            target_lbs > request.baseline.current_draw_weight_lbs
            or request.goal.primary_archetype == PlanArchetype.POUNDAGE_INCREASE
            or request.goal.secondary_archetype == PlanArchetype.POUNDAGE_INCREASE
        )
        if not has_step_up:
            return set()

        if request.goal.poundage_step_up_date:
            delta_days = max(0, (request.goal.poundage_step_up_date - request.goal.start_date).days)
            start_step_week = min(total_weeks, (delta_days // 7) + 1)
            # 7-10 days spans the step-up week and part of the following week
            return {start_step_week, min(total_weeks, start_step_week + 1)}

        return {1, min(total_weeks, 2)}

    @staticmethod
    def _find_mesocycle_for_week(
        mesocycles: list[TrainingMesocycle],
        week_number: int,
    ) -> TrainingMesocycle:
        for meso in mesocycles:
            if meso.start_week <= week_number <= meso.end_week:
                return meso
        return mesocycles[-1]

    def _build_sessions_for_week(
        self,
        microcycle: TrainingMicrocycle,
        mesocycle: TrainingMesocycle,
        week_start_date: date,
        target_date: date,
        request: GeneratePlanRequest,
        is_taper_week: bool,
        is_poundage_adaptation: bool,
    ) -> list[TrainingSession]:
        """Allocate weekly arrow volume across available DayAccess entries and generate SessionBlocks."""
        schedule = sorted(request.baseline.available_days, key=lambda d: d.day_of_week)
        total_duration = sum(d.duration_minutes for d in schedule) or 1

        # Compute raw per-day arrow targets weighted by session duration
        raw_day_arrows: list[int] = []
        allocated = 0
        for idx, day in enumerate(schedule):
            if idx == len(schedule) - 1:
                day_arrows = max(18, microcycle.target_arrows - allocated)
            else:
                share = day.duration_minutes / total_duration
                day_arrows = max(18, int(round(microcycle.target_arrows * share)))
                allocated += day_arrows
            raw_day_arrows.append(day_arrows)

        # Ensure exact match with microcycle.target_arrows
        diff = microcycle.target_arrows - sum(raw_day_arrows)
        if raw_day_arrows and diff != 0:
            raw_day_arrows[-1] = max(12, raw_day_arrows[-1] + diff)

        sessions: list[TrainingSession] = []
        for day, session_arrows in zip(schedule, raw_day_arrows):
            offset_days = (day.day_of_week - week_start_date.weekday()) % 7
            session_date = week_start_date + timedelta(days=offset_days)
            if session_date > target_date and len(sessions) > 0:
                session_date = target_date

            session_id = uuid.uuid4()
            session = TrainingSession(
                id=session_id,
                microcycle_id=microcycle.id,
                scheduled_date=session_date,
                max_distance_m=day.max_distance_meters,
                duration_mins=day.duration_minutes,
                status=SessionStatus.SCHEDULED.value,
                rpe_score=None,
                pain_flags_json={},
                notes=None,
                blocks=[],
            )
            session.blocks = self._build_blocks_for_session(
                session=session,
                day=day,
                session_arrows=session_arrows,
                pillar_ratios=mesocycle.pillar_ratios_json,
                request=request,
                is_taper_week=is_taper_week,
                is_poundage_adaptation=is_poundage_adaptation,
            )
            sessions.append(session)

        return sessions

    def _build_blocks_for_session(
        self,
        session: TrainingSession,
        day: DayAccess,
        session_arrows: int,
        pillar_ratios: dict[str, float],
        request: GeneratePlanRequest,
        is_taper_week: bool,
        is_poundage_adaptation: bool,
    ) -> list[SessionBlock]:
        """
        Construct ordered SessionBlocks for a single session respecting:
        - Range distance limit (`max_distance_meters < 18` -> no 70m/50m scored or match simulation blocks).
        - Short-distance days route to `technical_blank_bale`, `spt_conditioning`, and `requires_cv_video`
          drills matching `identified_faults`.
        - Poundage step-up window forces >=50% of arrows to short-range blank bale (<=5m).
        - Taper window strips heavy SPT Power/Endurance blocks.
        - WA division rules for match play (Recurve/Barebow = Set System; Compound = 15-arrow Cumulative).
        """
        division = request.baseline.bow_division
        faults = list(request.baseline.identified_faults)
        round_dist_m, round_face_cm = ROUND_FORMAT_SPECS.get(
            request.goal.round_format,
            (70 if division != BowDivision.COMPOUND else 50, 122),
        )

        blocks: list[SessionBlock] = []
        order = 1

        # 1. Warmup Block (0 arrows band warmup or 12-arrow blank bale warmup)
        warmup_drill = self._select_drill(
            block_type=SessionBlockType.WARMUP,
            division=division,
            faults=faults,
            max_distance_m=min(day.max_distance_meters, 5),
        )
        warmup_arrows = min(12, max(0, int(round(session_arrows * 0.10))))
        if warmup_drill.default_arrows == 0:
            warmup_arrows = 0

        blocks.append(
            SessionBlock(
                id=uuid.uuid4(),
                session_id=session.id,
                drill_id=warmup_drill.id,
                block_order=order,
                block_type=SessionBlockType.WARMUP.value,
                prescribed_arrows=warmup_arrows,
                actual_arrows=0,
                distance_m=min(day.max_distance_meters, warmup_drill.min_distance_m),
                target_face_cm=None,
                linked_scorecard_id=None,
                linked_cv_job_id=None,
                completed=False,
                drill=warmup_drill,
            )
        )
        order += 1

        # 2. Cooldown reservation (6 arrows)
        cooldown_drill = self._select_drill(
            block_type=SessionBlockType.COOLDOWN,
            division=division,
            faults=faults,
            max_distance_m=min(day.max_distance_meters, 5),
        )
        cooldown_arrows = min(6, max(0, session_arrows - warmup_arrows))
        main_arrows = max(6, session_arrows - warmup_arrows - cooldown_arrows)

        # 3. Short-distance routing: max_distance_meters < 18
        if day.max_distance_meters < 18 or day.blank_bale_only:
            tech_drill = self._select_drill(
                block_type=SessionBlockType.TECHNICAL_BLANK_BALE,
                division=division,
                faults=faults,
                max_distance_m=min(day.max_distance_meters, 5),
                prefer_cv_video=True,
                prefer_poundage_adaptation=is_poundage_adaptation,
            )

            if is_taper_week:
                # Taper weeks strip heavy SPT conditioning blocks
                tech_arrows = main_arrows
                spt_arrows = 0
            else:
                spt_arrows = max(12, int(round(main_arrows * 0.30)))
                tech_arrows = max(12, main_arrows - spt_arrows)

            blocks.append(
                SessionBlock(
                    id=uuid.uuid4(),
                    session_id=session.id,
                    drill_id=tech_drill.id,
                    block_order=order,
                    block_type=SessionBlockType.TECHNICAL_BLANK_BALE.value,
                    prescribed_arrows=tech_arrows,
                    actual_arrows=0,
                    distance_m=min(day.max_distance_meters, 5),
                    target_face_cm=None,
                    linked_scorecard_id=None,
                    linked_cv_job_id=None,
                    completed=False,
                    drill=tech_drill,
                )
            )
            order += 1

            if spt_arrows > 0 and not is_taper_week:
                spt_drill = self._select_drill(
                    block_type=SessionBlockType.SPT_CONDITIONING,
                    division=division,
                    faults=faults,
                    max_distance_m=min(day.max_distance_meters, 5),
                    prefer_cv_video=bool(faults),
                    exclude_heavy_spt=is_taper_week,
                )
                blocks.append(
                    SessionBlock(
                        id=uuid.uuid4(),
                        session_id=session.id,
                        drill_id=spt_drill.id,
                        block_order=order,
                        block_type=SessionBlockType.SPT_CONDITIONING.value,
                        prescribed_arrows=spt_arrows,
                        actual_arrows=0,
                        distance_m=min(day.max_distance_meters, 5),
                        target_face_cm=None,
                        linked_scorecard_id=None,
                        linked_cv_job_id=None,
                        completed=False,
                        drill=spt_drill,
                    )
                )
                order += 1
        else:
            # Full-range session (max_distance_meters >= 18)
            tech_ratio = pillar_ratios.get(SessionBlockType.TECHNICAL_BLANK_BALE.value, 0.25)
            scored_ratio = pillar_ratios.get(SessionBlockType.SCORED_DISTANCE.value, 0.45)
            spt_ratio = 0.0 if is_taper_week else pillar_ratios.get(SessionBlockType.SPT_CONDITIONING.value, 0.15)
            match_ratio = pillar_ratios.get(SessionBlockType.MATCH_SIMULATION.value, 0.15)

            if is_poundage_adaptation:
                # Poundage Lockout / Step-Up Law: shift >= 50% of arrows to short-range/blank-bale (<=5m)
                tech_ratio = max(0.55, tech_ratio)
                remainder = 1.0 - tech_ratio
                scored_ratio = round(remainder * 0.65, 4)
                spt_ratio = 0.0 if is_taper_week else round(remainder * 0.35, 4)
                match_ratio = 0.0

            match_arrows = 15 if (match_ratio >= 0.10 and main_arrows >= 45) else 0
            remaining_for_pillars = max(12, main_arrows - match_arrows)
            pillar_sum = (tech_ratio + scored_ratio + spt_ratio) or 1.0

            tech_arrows = int(round(remaining_for_pillars * (tech_ratio / pillar_sum)))
            if is_poundage_adaptation:
                min_bale_arrows = math.ceil(session_arrows * 0.50) - warmup_arrows - cooldown_arrows
                tech_arrows = max(tech_arrows, min_bale_arrows)

            spt_arrows = (
                0
                if is_taper_week
                else int(round(remaining_for_pillars * (spt_ratio / pillar_sum)))
            )
            scored_arrows = max(0, remaining_for_pillars - tech_arrows - spt_arrows)

            # Technical Blank Bale block (<=5m)
            if tech_arrows > 0:
                tech_drill = self._select_drill(
                    block_type=SessionBlockType.TECHNICAL_BLANK_BALE,
                    division=division,
                    faults=faults,
                    max_distance_m=5,
                    prefer_cv_video=bool(faults),
                    prefer_poundage_adaptation=is_poundage_adaptation,
                )
                blocks.append(
                    SessionBlock(
                        id=uuid.uuid4(),
                        session_id=session.id,
                        drill_id=tech_drill.id,
                        block_order=order,
                        block_type=SessionBlockType.TECHNICAL_BLANK_BALE.value,
                        prescribed_arrows=tech_arrows,
                        actual_arrows=0,
                        distance_m=min(5, tech_drill.min_distance_m),
                        target_face_cm=None,
                        linked_scorecard_id=None,
                        linked_cv_job_id=None,
                        completed=False,
                        drill=tech_drill,
                    )
                )
                order += 1

            # Scored Distance block
            if scored_arrows > 0:
                effective_scored_dist = min(day.max_distance_meters, round_dist_m)
                effective_face_cm = 40 if effective_scored_dist <= 18 else (80 if division == BowDivision.COMPOUND else round_face_cm)
                scored_drill = self._select_drill(
                    block_type=SessionBlockType.SCORED_DISTANCE,
                    division=division,
                    faults=faults,
                    max_distance_m=effective_scored_dist,
                )
                blocks.append(
                    SessionBlock(
                        id=uuid.uuid4(),
                        session_id=session.id,
                        drill_id=scored_drill.id,
                        block_order=order,
                        block_type=SessionBlockType.SCORED_DISTANCE.value,
                        prescribed_arrows=scored_arrows,
                        actual_arrows=0,
                        distance_m=effective_scored_dist,
                        target_face_cm=effective_face_cm,
                        linked_scorecard_id=None,
                        linked_cv_job_id=None,
                        completed=False,
                        drill=scored_drill,
                    )
                )
                order += 1

            # Match Simulation block (WA Division-Specific Law #2)
            if match_arrows > 0:
                effective_match_dist = min(day.max_distance_meters, round_dist_m)
                effective_face_cm = 40 if effective_match_dist <= 18 else (80 if division == BowDivision.COMPOUND else 122)
                match_drill = self._select_match_drill_for_division(division)
                blocks.append(
                    SessionBlock(
                        id=uuid.uuid4(),
                        session_id=session.id,
                        drill_id=match_drill.id,
                        block_order=order,
                        block_type=SessionBlockType.MATCH_SIMULATION.value,
                        prescribed_arrows=15,
                        actual_arrows=0,
                        distance_m=effective_match_dist,
                        target_face_cm=effective_face_cm,
                        linked_scorecard_id=None,
                        linked_cv_job_id=None,
                        completed=False,
                        drill=match_drill,
                    )
                )
                order += 1

            # SPT Conditioning block (omitted during competition taper to prevent DOMS)
            if spt_arrows > 0 and not is_taper_week:
                spt_drill = self._select_drill(
                    block_type=SessionBlockType.SPT_CONDITIONING,
                    division=division,
                    faults=faults,
                    max_distance_m=5,
                    exclude_heavy_spt=is_taper_week,
                )
                blocks.append(
                    SessionBlock(
                        id=uuid.uuid4(),
                        session_id=session.id,
                        drill_id=spt_drill.id,
                        block_order=order,
                        block_type=SessionBlockType.SPT_CONDITIONING.value,
                        prescribed_arrows=spt_arrows,
                        actual_arrows=0,
                        distance_m=min(5, spt_drill.min_distance_m),
                        target_face_cm=None,
                        linked_scorecard_id=None,
                        linked_cv_job_id=None,
                        completed=False,
                        drill=spt_drill,
                    )
                )
                order += 1

        # 4. Cooldown Block
        if cooldown_arrows > 0:
            blocks.append(
                SessionBlock(
                    id=uuid.uuid4(),
                    session_id=session.id,
                    drill_id=cooldown_drill.id,
                    block_order=order,
                    block_type=SessionBlockType.COOLDOWN.value,
                    prescribed_arrows=cooldown_arrows,
                    actual_arrows=0,
                    distance_m=min(day.max_distance_meters, cooldown_drill.min_distance_m),
                    target_face_cm=None,
                    linked_scorecard_id=None,
                    linked_cv_job_id=None,
                    completed=False,
                    drill=cooldown_drill,
                )
            )

        return blocks

    def _select_match_drill_for_division(self, division: BowDivision) -> DrillCatalog:
        """Select division-specific World Archery match-play drill (Set System vs 15-arrow Cumulative)."""
        match_drills = [
            d for d in self.drills if d.block_type == SessionBlockType.MATCH_SIMULATION.value
        ]
        if division == BowDivision.COMPOUND:
            for drill in match_drills:
                if "compound" in drill.bow_divisions and "Cumulative" in drill.title:
                    return drill
        else:
            for drill in match_drills:
                if "Set-System" in drill.title or "recurve" in drill.bow_divisions:
                    return drill
        return match_drills[0]

    def _select_drill(
        self,
        block_type: SessionBlockType,
        division: BowDivision,
        faults: list[FormFault],
        max_distance_m: int,
        prefer_cv_video: bool = False,
        prefer_poundage_adaptation: bool = False,
        exclude_heavy_spt: bool = False,
    ) -> DrillCatalog:
        """Select the highest-scoring drill from the seed catalog matching division, distance, and faults."""
        candidates = [
            d
            for d in self.drills
            if d.block_type == block_type.value and division.value in d.bow_divisions
        ]
        if not candidates:
            candidates = [d for d in self.drills if d.block_type == block_type.value]

        if exclude_heavy_spt:
            filtered = [
                d
                for d in candidates
                if not any(heavy in d.title for heavy in HEAVY_SPT_TITLES)
            ]
            if filtered:
                candidates = filtered

        fault_values = {f.value for f in faults}

        def score_candidate(drill: DrillCatalog) -> tuple[int, int, int, int]:
            dist_ok = 1 if drill.min_distance_m <= max_distance_m else 0
            poundage_match = (
                1
                if (prefer_poundage_adaptation and "Poundage Step-Up" in drill.title)
                else 0
            )
            fault_overlap = len(fault_values.intersection(set(drill.faults_addressed)))
            cv_bonus = 1 if (prefer_cv_video and drill.requires_cv_video) else 0
            return (dist_ok, poundage_match, fault_overlap, cv_bonus)

        candidates.sort(key=score_candidate, reverse=True)
        return candidates[0]

    # -----------------------------------------------------------------------
    # Smart Recalibration Engine
    # -----------------------------------------------------------------------

    def evaluate_recalibration(
        self,
        plan_or_id: UUID | TrainingPlan,
        reference_date: Optional[date] = None,
        cv_job_degradations: Optional[dict[UUID, float]] = None,
    ) -> RecalibrationProposalResponse:
        """
        Inspect the last 7-14 days of TrainingSession logs and generate a RecalibrationProposalResponse if:
        1. Actual volume < 50% of target volume over 7 days -> propose repeating current microcycle load.
        2. RPE >= 8 for 3 consecutive sessions OR pain_flags is non-empty -> propose 5-day deload + blank bale shift.
        3. Linked CV job reports > 5 degree form degradation after a poundage/volume jump -> propose shifting
           30% of scored arrows to technical blank bale.
        """
        if isinstance(plan_or_id, TrainingPlan):
            plan = plan_or_id
        else:
            if plan_or_id not in self._plans_registry:
                raise KeyError(f"TrainingPlan {plan_or_id} not found in PeriodizationEngineService.")
            plan = self._plans_registry[plan_or_id]

        cv_lookup = dict(self._cv_degradation_registry)
        if cv_job_degradations:
            cv_lookup.update(cv_job_degradations)

        all_sessions: list[TrainingSession] = [
            s for micro in plan.microcycles for s in micro.sessions
        ]
        all_sessions.sort(key=lambda s: s.scheduled_date)

        logged_sessions = [
            s
            for s in all_sessions
            if s.status in (SessionStatus.COMPLETED.value, SessionStatus.SKIPPED.value, SessionStatus.MODIFIED.value)
            or s.rpe_score is not None
            or bool(s.pain_flags_json)
            or any(b.actual_arrows > 0 or b.completed for b in s.blocks)
        ]

        if reference_date is None:
            if logged_sessions:
                reference_date = max(s.scheduled_date for s in logged_sessions)
            elif all_sessions:
                reference_date = all_sessions[0].scheduled_date + timedelta(days=7)
            else:
                reference_date = date.today()

        window_14d_start = reference_date - timedelta(days=14)
        window_7d_start = reference_date - timedelta(days=7)

        sessions_14d = [
            s for s in all_sessions if window_14d_start <= s.scheduled_date <= reference_date
        ]
        sessions_7d = [
            s for s in all_sessions if window_7d_start <= s.scheduled_date <= reference_date
        ]
        if not sessions_7d and all_sessions:
            sessions_7d = all_sessions[: len(plan.microcycles[0].sessions)]
        if not sessions_14d and all_sessions:
            sessions_14d = sessions_7d

        # 1. Check Volume Adherence over 7 days (< 50% actual vs target)
        target_7d = sum(
            sum(b.prescribed_arrows for b in s.blocks) for s in sessions_7d
        )
        actual_7d = sum(
            sum(b.actual_arrows for b in s.blocks) for s in sessions_7d
        )
        if target_7d == 0 and plan.microcycles:
            target_7d = plan.microcycles[0].target_arrows
            actual_7d = plan.microcycles[0].actual_arrows

        volume_ratio_7d = (actual_7d / target_7d) if target_7d > 0 else 1.0
        low_volume_trigger = target_7d > 0 and volume_ratio_7d < 0.50

        # 2. Check RPE >= 8 for 3 consecutive sessions OR non-empty pain_flags
        rpe_sessions = [s for s in (logged_sessions or sessions_14d) if s.rpe_score is not None]
        consecutive_high_rpe = 0
        has_3_consecutive_high_rpe = False
        for s in rpe_sessions:
            if (s.rpe_score or 0) >= 8:
                consecutive_high_rpe += 1
                if consecutive_high_rpe >= 3:
                    has_3_consecutive_high_rpe = True
                    break
            else:
                consecutive_high_rpe = 0

        pain_detected = any(
            bool(s.pain_flags_json)
            and any(
                (isinstance(v, (int, float)) and v > 0) or (isinstance(v, bool) and v) or (isinstance(v, str) and bool(v.strip()))
                for v in s.pain_flags_json.values()
            )
            for s in (logged_sessions or sessions_14d)
        )
        fatigue_or_pain_trigger = has_3_consecutive_high_rpe or pain_detected

        # 3. Check CV Form Degradation > 5.0 degrees after a poundage/volume jump
        max_cv_degradation = 0.0
        for s in (logged_sessions or sessions_14d):
            for b in s.blocks:
                if b.linked_cv_job_id and b.linked_cv_job_id in cv_lookup:
                    deg = float(cv_lookup[b.linked_cv_job_id])
                    if deg > max_cv_degradation:
                        max_cv_degradation = deg
            # Also support inline notes/pain_flags_json metadata carrying cv_degradation_degrees
            if isinstance(s.pain_flags_json, dict) and "cv_form_degradation_deg" in s.pain_flags_json:
                deg = float(s.pain_flags_json["cv_form_degradation_deg"])
                if deg > max_cv_degradation:
                    max_cv_degradation = deg

        cv_degradation_trigger = max_cv_degradation > 5.0

        triggers: list[str] = []
        reasons: list[str] = []

        if fatigue_or_pain_trigger:
            if pain_detected:
                triggers.append("pain_flag_detected")
                reasons.append("Anatomical pain flags reported; prescribing 5-day deload and short-range blank bale shift.")
            if has_3_consecutive_high_rpe:
                triggers.append("rpe_spike_3_consecutive")
                reasons.append("RPE >= 8 for 3 consecutive sessions; prescribing 5-day deload and blank bale recovery shift.")

        if cv_degradation_trigger:
            triggers.append("cv_form_degradation_gt_5_deg")
            reasons.append(
                f"CV biomechanics job detected {max_cv_degradation:.1f}° (>5.0°) form degradation; "
                "shifting 30% of scored arrows to technical blank bale."
            )

        if low_volume_trigger:
            triggers.append("low_volume_adherence_lt_50_pct")
            reasons.append(
                f"7-day arrow volume adherence was {volume_ratio_7d * 100:.1f}% (<50%); "
                "proposing to repeat current microcycle load before progressing."
            )

        recalibration_flag = len(triggers) > 0
        recalibration_reason = " | ".join(reasons) if reasons else None

        proposed_adjustments: list[MicrocycleAdjustmentDiff] = []
        coach_locked_skipped: list[int] = []

        if recalibration_flag and plan.microcycles:
            # Determine current & next microcycles relative to reference_date
            current_micro = plan.microcycles[0]
            for micro in plan.microcycles:
                if any(s.scheduled_date <= reference_date for s in micro.sessions):
                    current_micro = micro

            upcoming_micros = [
                m for m in plan.microcycles if m.week_number >= current_micro.week_number
            ]
            if not upcoming_micros:
                upcoming_micros = [plan.microcycles[-1]]

            for target_micro in upcoming_micros[:2]:
                if target_micro.coach_locked:
                    coach_locked_skipped.append(target_micro.week_number)
                    continue

                prev_arrows = target_micro.target_arrows
                if fatigue_or_pain_trigger:
                    proposed_arrows = max(48, int(round(prev_arrows * 0.70)))
                    proposed_adjustments.append(
                        MicrocycleAdjustmentDiff(
                            week_number=target_micro.week_number,
                            previous_target_arrows=prev_arrows,
                            proposed_target_arrows=proposed_arrows,
                            is_deload_week=True,
                            blank_bale_ratio=0.65,
                            rationale="5-day deload (-30% volume) + blank bale shift due to RPE >= 8 / pain flag.",
                        )
                    )
                    break
                elif cv_degradation_trigger:
                    proposed_adjustments.append(
                        MicrocycleAdjustmentDiff(
                            week_number=target_micro.week_number,
                            previous_target_arrows=prev_arrows,
                            proposed_target_arrows=prev_arrows,
                            is_deload_week=target_micro.is_deload_week,
                            blank_bale_ratio=0.50,
                            rationale=(
                                f"Shift 30% of scored_distance arrows to technical_blank_bale "
                                f"due to {max_cv_degradation:.1f}° CV form degradation."
                            ),
                        )
                    )
                    break
                elif low_volume_trigger:
                    repeat_load = current_micro.target_arrows
                    proposed_adjustments.append(
                        MicrocycleAdjustmentDiff(
                            week_number=target_micro.week_number,
                            previous_target_arrows=prev_arrows,
                            proposed_target_arrows=repeat_load,
                            is_deload_week=False,
                            blank_bale_ratio=None,
                            rationale="Repeat current microcycle target load after <50% 7-day volume completion.",
                        )
                    )
                    break

        plan.recalibration_flag = recalibration_flag
        plan.recalibration_reason = recalibration_reason

        return RecalibrationProposalResponse(
            plan_id=plan.id,
            recalibration_flag=recalibration_flag,
            recalibration_reason=recalibration_reason,
            triggers_detected=triggers,
            analytics_summary={
                "target_arrows_7d": target_7d,
                "actual_arrows_7d": actual_7d,
                "volume_adherence_ratio_7d": round(volume_ratio_7d, 4),
                "max_cv_degradation_degrees": round(max_cv_degradation, 2),
                "has_3_consecutive_high_rpe": has_3_consecutive_high_rpe,
                "pain_detected": pain_detected,
            },
            proposed_adjustments=proposed_adjustments,
            coach_locked_weeks_skipped=coach_locked_skipped,
        )

    def get_plan(self, plan_id: UUID) -> TrainingPlan:
        """Retrieve a TrainingPlan by ID or raise KeyError."""
        if plan_id not in self._plans_registry:
            raise KeyError(f"TrainingPlan {plan_id} not found.")
        return self._plans_registry[plan_id]

    def get_session_with_context(
        self,
        session_id: UUID,
    ) -> tuple[TrainingPlan, TrainingMicrocycle, TrainingSession]:
        """Locate a TrainingSession along with its parent TrainingMicrocycle and TrainingPlan."""
        for plan in self._plans_registry.values():
            for micro in plan.microcycles:
                for sess in micro.sessions:
                    if sess.id == session_id:
                        return plan, micro, sess
        raise KeyError(f"TrainingSession {session_id} not found.")

    def get_microcycle_with_context(
        self,
        microcycle_id: UUID,
    ) -> tuple[TrainingPlan, TrainingMicrocycle]:
        """Locate a TrainingMicrocycle along with its parent TrainingPlan."""
        for plan in self._plans_registry.values():
            for micro in plan.microcycles:
                if micro.id == microcycle_id:
                    return plan, micro
        raise KeyError(f"TrainingMicrocycle {microcycle_id} not found.")

    def log_session(
        self,
        session_id: UUID,
        payload: SessionLogUpdateRequest,
    ) -> tuple[TrainingPlan, TrainingSession]:
        """
        Record session execution in Mode A (Quick-Log) or Mode B (Live Runner):
        - Mode A: session-level actual_arrows, rpe_score (1-10), pain_flags.
        - Mode B: block-level updates linking scorecard_id, cv_job_id, spt_hold_reps, and ends.
        """
        plan, micro, session = self.get_session_with_context(session_id)
        session.status = payload.status.value
        if payload.rpe_score is not None:
            session.rpe_score = payload.rpe_score
        if payload.pain_flags_json:
            merged_flags = dict(session.pain_flags_json or {})
            merged_flags.update(payload.pain_flags_json)
            session.pain_flags_json = merged_flags
        if payload.notes is not None:
            session.notes = payload.notes

        if payload.blocks:
            # Mode B: Live Runner block-by-block updates
            for blk_update in payload.blocks:
                target_block: Optional[SessionBlock] = None
                if blk_update.block_id is not None:
                    target_block = next(
                        (b for b in session.blocks if b.id == blk_update.block_id),
                        None,
                    )
                if target_block is None and blk_update.block_order is not None:
                    target_block = next(
                        (b for b in session.blocks if b.block_order == blk_update.block_order),
                        None,
                    )
                if target_block is None and len(payload.blocks) == 1 and session.blocks:
                    target_block = session.blocks[0]

                if target_block is not None:
                    if blk_update.ends and blk_update.actual_arrows == 0:
                        target_block.actual_arrows = sum(len(e.arrows) for e in blk_update.ends)
                    else:
                        target_block.actual_arrows = blk_update.actual_arrows
                    target_block.completed = blk_update.completed
                    if blk_update.linked_scorecard_id is not None:
                        target_block.linked_scorecard_id = blk_update.linked_scorecard_id
                    if blk_update.linked_cv_job_id is not None:
                        target_block.linked_cv_job_id = blk_update.linked_cv_job_id
                        if blk_update.cv_form_degradation_deg is not None:
                            self.register_cv_job_degradation(
                                blk_update.linked_cv_job_id,
                                blk_update.cv_form_degradation_deg,
                            )
                    elif blk_update.cv_form_degradation_deg is not None:
                        synthetic_cv_id = uuid.uuid4()
                        target_block.linked_cv_job_id = synthetic_cv_id
                        self.register_cv_job_degradation(
                            synthetic_cv_id,
                            blk_update.cv_form_degradation_deg,
                        )
                    if blk_update.spt_hold_reps is not None:
                        meta = dict(session.pain_flags_json or {})
                        spt_reps = dict(meta.get("_spt_hold_reps", {}))
                        spt_reps[str(target_block.id)] = blk_update.spt_hold_reps
                        meta["_spt_hold_reps"] = spt_reps
                        session.pain_flags_json = meta
        elif payload.actual_arrows is not None:
            # Mode A: Quick-Log session arrow total distributed across session blocks
            total_prescribed = sum(b.prescribed_arrows for b in session.blocks) or 1
            remaining = payload.actual_arrows
            shooting_blocks = [b for b in session.blocks if b.prescribed_arrows > 0] or session.blocks
            for idx, blk in enumerate(shooting_blocks):
                if idx == len(shooting_blocks) - 1:
                    blk.actual_arrows = max(0, remaining)
                else:
                    share = int(round(payload.actual_arrows * (blk.prescribed_arrows / total_prescribed)))
                    blk.actual_arrows = min(remaining, max(0, share))
                    remaining -= blk.actual_arrows
                blk.completed = True

        micro.actual_arrows = sum(
            b.actual_arrows for s in micro.sessions for b in s.blocks
        )
        return plan, session

    def apply_recalibration(
        self,
        plan_id: UUID,
        request: Optional[ApplyRecalibrationRequest] = None,
    ) -> TrainingPlan:
        """Apply approved recalibration adjustments to future unlocked TrainingMicrocycle & Session rows."""
        plan = self.get_plan(plan_id)
        if request is not None and request.adjustments is not None:
            adjustments = request.adjustments
        else:
            proposal = self.evaluate_recalibration(plan)
            adjustments = proposal.proposed_adjustments

        division_str = plan.baseline_json.get("bow_division", BowDivision.RECURVE.value)
        division = BowDivision(division_str)
        raw_faults = plan.baseline_json.get("active_form_faults", [])
        faults = [FormFault(f) for f in raw_faults if f in FormFault._value2member_map_]
        bale_drill = self._select_drill(
            block_type=SessionBlockType.TECHNICAL_BLANK_BALE,
            division=division,
            faults=faults,
            max_distance_m=5,
            prefer_cv_video=True,
        )

        adj_by_week = {adj.week_number: adj for adj in adjustments}
        for micro in plan.microcycles:
            if micro.coach_locked or micro.week_number not in adj_by_week:
                continue
            adj = adj_by_week[micro.week_number]
            old_target = micro.target_arrows or 1
            scale = adj.proposed_target_arrows / old_target
            micro.target_arrows = adj.proposed_target_arrows
            micro.is_deload_week = adj.is_deload_week

            for sess in micro.sessions:
                for blk in sess.blocks:
                    blk.prescribed_arrows = max(
                        0 if blk.block_type == SessionBlockType.WARMUP.value else 6,
                        int(round(blk.prescribed_arrows * scale)),
                    )
                if adj.blank_bale_ratio is not None and adj.blank_bale_ratio > 0:
                    # Shift 30%+ of scored_distance arrows to technical_blank_bale (<=5m)
                    scored_blocks = [
                        b for b in sess.blocks if b.block_type == SessionBlockType.SCORED_DISTANCE.value
                    ]
                    tech_blocks = [
                        b
                        for b in sess.blocks
                        if b.block_type == SessionBlockType.TECHNICAL_BLANK_BALE.value
                    ]
                    for sb in scored_blocks:
                        shift_arrows = int(round(sb.prescribed_arrows * 0.30))
                        if shift_arrows > 0:
                            sb.prescribed_arrows = max(6, sb.prescribed_arrows - shift_arrows)
                            if tech_blocks:
                                tech_blocks[0].prescribed_arrows += shift_arrows
                                tech_blocks[0].distance_m = min(5, tech_blocks[0].distance_m)
                            else:
                                sess.blocks.insert(
                                    max(0, len(sess.blocks) - 1),
                                    SessionBlock(
                                        id=uuid.uuid4(),
                                        session_id=sess.id,
                                        drill_id=bale_drill.id,
                                        block_order=len(sess.blocks) + 1,
                                        block_type=SessionBlockType.TECHNICAL_BLANK_BALE.value,
                                        prescribed_arrows=shift_arrows,
                                        actual_arrows=0,
                                        distance_m=3,
                                        target_face_cm=None,
                                        completed=False,
                                        drill=bale_drill,
                                    ),
                                )

        plan.recalibration_flag = False
        plan.recalibration_reason = None
        return plan

    def apply_coach_override(
        self,
        microcycle_id: UUID,
        payload: CoachOverrideRequest,
    ) -> tuple[TrainingPlan, TrainingMicrocycle]:
        """Allow a linked coach to lock/modify weekly volume or swap drills on a microcycle."""
        plan, micro = self.get_microcycle_with_context(microcycle_id)
        if payload.coach_locked is not None:
            micro.coach_locked = payload.coach_locked
        if payload.is_deload_week is not None:
            micro.is_deload_week = payload.is_deload_week

        if payload.target_arrows is not None:
            old_total = sum(b.prescribed_arrows for s in micro.sessions for b in s.blocks) or 1
            scale = payload.target_arrows / old_total
            all_blocks = [b for s in micro.sessions for b in s.blocks if b.prescribed_arrows > 0]
            allocated = 0
            for idx, blk in enumerate(all_blocks):
                if idx == len(all_blocks) - 1:
                    blk.prescribed_arrows = max(0, payload.target_arrows - allocated)
                else:
                    scaled = max(0, int(round(blk.prescribed_arrows * scale)))
                    blk.prescribed_arrows = scaled
                    allocated += scaled
            micro.target_arrows = payload.target_arrows

        if payload.drill_swaps:
            drills_by_id = {d.id: d for d in self.drills}
            for swap in payload.drill_swaps:
                new_drill = drills_by_id.get(swap.new_drill_id)
                if new_drill is None:
                    raise ValueError(f"Drill {swap.new_drill_id} not found in catalog.")
                target_block: Optional[SessionBlock] = None
                for sess in micro.sessions:
                    for blk in sess.blocks:
                        if swap.block_id and blk.id == swap.block_id:
                            target_block = blk
                            break
                        if (
                            swap.session_id
                            and sess.id == swap.session_id
                            and swap.block_order == blk.block_order
                        ):
                            target_block = blk
                            break
                        if swap.block_id is None and swap.session_id is None and swap.block_order == blk.block_order:
                            target_block = blk
                            break
                    if target_block is not None:
                        break

                if target_block is None and micro.sessions and micro.sessions[0].blocks:
                    target_block = micro.sessions[0].blocks[0]

                if target_block is not None:
                    target_block.drill_id = new_drill.id
                    target_block.drill = new_drill
                    target_block.block_type = new_drill.block_type
                    if swap.prescribed_arrows is not None:
                        target_block.prescribed_arrows = swap.prescribed_arrows
                    if swap.distance_m is not None:
                        target_block.distance_m = swap.distance_m

            micro.target_arrows = sum(
                b.prescribed_arrows for s in micro.sessions for b in s.blocks
            )

        return plan, micro

    @staticmethod
    def to_session_detail_response(
        session: TrainingSession,
        division: BowDivision = BowDivision.RECURVE,
    ) -> TrainingSessionDetailResponse:
        """Serialize a TrainingSession and its ordered blocks with drill instructions & match specs."""
        block_items: list[SessionBlockResponse] = []
        for blk in sorted(session.blocks, key=lambda b: b.block_order):
            match_spec = (
                MatchPlayFormatSpec.for_division(division, blk.distance_m)
                if blk.block_type == SessionBlockType.MATCH_SIMULATION.value
                else None
            )
            block_items.append(
                SessionBlockResponse(
                    id=blk.id,
                    session_id=blk.session_id,
                    drill_id=blk.drill_id,
                    block_order=blk.block_order,
                    block_type=SessionBlockType(blk.block_type),
                    prescribed_arrows=blk.prescribed_arrows,
                    actual_arrows=blk.actual_arrows,
                    distance_m=blk.distance_m,
                    target_face_cm=blk.target_face_cm,
                    linked_scorecard_id=blk.linked_scorecard_id,
                    linked_cv_job_id=blk.linked_cv_job_id,
                    completed=blk.completed,
                    drill=blk.drill,
                    match_play_spec=match_spec,
                )
            )
        clean_pain_flags = {
            k: v for k, v in (session.pain_flags_json or {}).items() if not str(k).startswith("_")
        }
        return TrainingSessionDetailResponse(
            id=session.id,
            microcycle_id=session.microcycle_id,
            scheduled_date=session.scheduled_date,
            max_distance_m=session.max_distance_m,
            duration_mins=session.duration_mins,
            status=SessionStatus(session.status),
            rpe_score=session.rpe_score,
            pain_flags_json=clean_pain_flags,
            notes=session.notes,
            blocks=block_items,
        )

    def to_roadmap_response(self, plan: TrainingPlan) -> TrainingPlanRoadmapResponse:
        """Convert a SQLAlchemy TrainingPlan hierarchy into a TrainingPlanRoadmapResponse."""
        division_str = plan.baseline_json.get("bow_division", BowDivision.RECURVE.value)
        division = BowDivision(division_str)

        meso_items = [
            MesocycleRoadmapItem(
                id=m.id,
                plan_id=m.plan_id,
                phase_name=m.phase_name,
                start_week=m.start_week,
                end_week=m.end_week,
                pillar_ratios_json=m.pillar_ratios_json,
            )
            for m in plan.mesocycles
        ]

        micro_items: list[MicrocycleRoadmapItem] = []
        pillar_arrow_totals: dict[str, int] = {
            SessionBlockType.SCORED_DISTANCE.value: 0,
            SessionBlockType.TECHNICAL_BLANK_BALE.value: 0,
            SessionBlockType.SPT_CONDITIONING.value: 0,
            SessionBlockType.MATCH_SIMULATION.value: 0,
        }
        for micro in plan.microcycles:
            session_items = [
                self.to_session_detail_response(sess, division) for sess in micro.sessions
            ]
            for sess in micro.sessions:
                for blk in sess.blocks:
                    if blk.block_type in pillar_arrow_totals:
                        pillar_arrow_totals[blk.block_type] += blk.prescribed_arrows
            micro_items.append(
                MicrocycleRoadmapItem(
                    id=micro.id,
                    plan_id=micro.plan_id,
                    mesocycle_id=micro.mesocycle_id,
                    week_number=micro.week_number,
                    target_arrows=micro.target_arrows,
                    actual_arrows=micro.actual_arrows,
                    is_deload_week=micro.is_deload_week,
                    coach_locked=micro.coach_locked,
                    sessions=session_items,
                )
            )

        total_pillar_arrows = sum(pillar_arrow_totals.values())
        if total_pillar_arrows > 0:
            pillar_breakdown_pct = {
                k: round((v / total_pillar_arrows) * 100.0, 2)
                for k, v in pillar_arrow_totals.items()
            }
        else:
            base_ratios = self.compute_pillar_ratios(
                PlanArchetype(plan.primary_archetype),
                PlanArchetype(plan.secondary_archetype) if plan.secondary_archetype else None,
            )
            pillar_breakdown_pct = {k: round(v * 100.0, 2) for k, v in base_ratios.items()}

        active_proposal: Optional[RecalibrationProposalResponse] = None
        if plan.recalibration_flag:
            active_proposal = self.evaluate_recalibration(plan)

        return TrainingPlanRoadmapResponse(
            id=plan.id,
            athlete_id=plan.athlete_id,
            coach_id=plan.coach_id,
            primary_archetype=PlanArchetype(plan.primary_archetype),
            secondary_archetype=(
                PlanArchetype(plan.secondary_archetype) if plan.secondary_archetype else None
            ),
            start_date=plan.start_date,
            target_date=plan.target_date,
            status=PlanStatus(plan.status),
            baseline_json=plan.baseline_json,
            goal_json=plan.goal_json,
            recalibration_flag=plan.recalibration_flag,
            recalibration_reason=plan.recalibration_reason,
            mesocycles=meso_items,
            microcycles=micro_items,
            weekly_planned_arrows=[m.target_arrows for m in plan.microcycles],
            weekly_actual_arrows=[m.actual_arrows for m in plan.microcycles],
            pillar_breakdown_pct=pillar_breakdown_pct,
            active_recalibration_proposal=active_proposal,
        )

