"""Comprehensive unit tests for PeriodizationEngineService (Task 2)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.training_plan import (
    AthleteBaselineInput,
    BowDivision,
    DayAccess,
    FormFault,
    GeneratePlanRequest,
    MatchScoringSystem,
    PlanArchetype,
    RoundFormat,
    SessionBlockType,
    SessionStatus,
    TrainingGoalInput,
)
from app.services.periodization_engine import ARCHETYPE_PILLAR_RATIOS, PeriodizationEngineService


def _make_standard_schedule() -> list[DayAccess]:
    """2 weekday short-range sessions (5m) and 2 weekend full-range sessions (70m)."""
    return [
        DayAccess(day_of_week=1, duration_minutes=60, max_distance_meters=5),
        DayAccess(day_of_week=3, duration_minutes=60, max_distance_meters=10),
        DayAccess(day_of_week=5, duration_minutes=120, max_distance_meters=70),
        DayAccess(day_of_week=6, duration_minutes=120, max_distance_meters=70),
    ]


def _make_generate_request(
    *,
    division: BowDivision = BowDivision.RECURVE,
    primary_archetype: PlanArchetype = PlanArchetype.COMPETITION_PEAK,
    secondary_archetype: PlanArchetype | None = None,
    weeks: int = 8,
    baseline_volume: int = 200,
    current_lbs: float = 38.0,
    target_lbs: float = 38.0,
    faults: list[FormFault] | None = None,
    schedule: list[DayAccess] | None = None,
    round_format: RoundFormat = RoundFormat.WA_720_70M,
    poundage_step_up_date: date | None = None,
) -> GeneratePlanRequest:
    start = date(2026, 11, 2)  # Monday
    target = start + timedelta(days=weeks * 7)
    return GeneratePlanRequest(
        athlete_id=uuid.uuid4(),
        coach_id=uuid.uuid4(),
        baseline=AthleteBaselineInput(
            bow_division=division,
            current_draw_weight_lbs=current_lbs,
            target_draw_weight_lbs=target_lbs,
            current_weekly_arrow_volume=baseline_volume,
            identified_faults=faults or [FormFault.COLLAPSING_BOW_ARM, FormFault.PLUCKING_RELEASE],
            weekly_schedule=schedule or _make_standard_schedule(),
        ),
        goal=TrainingGoalInput(
            primary_archetype=primary_archetype,
            secondary_archetype=secondary_archetype,
            round_format=round_format,
            start_date=start,
            target_event_date=target,
            competition_tier="A",
            poundage_step_up_date=poundage_step_up_date,
        ),
    )


class TestArchetypesAndTimelines:
    """Verify all 6 PlanArchetypes and Forward-Looking vs Backward-Looking mesocycles."""

    @pytest.mark.parametrize("archetype", list(PlanArchetype))
    def test_all_six_archetype_pillar_distributions_sum_to_one(self, archetype: PlanArchetype) -> None:
        engine = PeriodizationEngineService()
        ratios = engine.compute_pillar_ratios(archetype)
        assert set(ratios.keys()) == {
            SessionBlockType.SCORED_DISTANCE.value,
            SessionBlockType.TECHNICAL_BLANK_BALE.value,
            SessionBlockType.SPT_CONDITIONING.value,
            SessionBlockType.MATCH_SIMULATION.value,
        }
        assert pytest.approx(sum(ratios.values()), abs=1e-3) == 1.0
        assert ratios == ARCHETYPE_PILLAR_RATIOS[archetype]

    def test_backward_looking_competition_peak_timeline(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(primary_archetype=PlanArchetype.COMPETITION_PEAK, weeks=8)
        plan = engine.generate_plan(req)

        assert len(plan.microcycles) == 8
        assert len(plan.mesocycles) >= 2
        assert "Backward-Anchored" in plan.mesocycles[0].phase_name
        assert "Taper & Peak" in plan.mesocycles[-1].phase_name
        assert plan.mesocycles[-1].start_week == 7
        assert plan.mesocycles[-1].end_week == 8

    @pytest.mark.parametrize(
        "general_archetype",
        [
            PlanArchetype.POUNDAGE_INCREASE,
            PlanArchetype.FORM_REBUILD,
            PlanArchetype.SEASON_TRANSITION,
            PlanArchetype.STAMINA_BUILDER,
            PlanArchetype.RETURN_TO_SHOOTING,
        ],
    )
    def test_forward_looking_general_block_timelines(self, general_archetype: PlanArchetype) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(primary_archetype=general_archetype, weeks=9)
        plan = engine.generate_plan(req)

        assert len(plan.microcycles) == 9
        assert all("Forward-Looking" in m.phase_name for m in plan.mesocycles)
        assert plan.mesocycles[0].start_week == 1
        assert plan.mesocycles[-1].end_week == 9


class TestPeriodizationVolumeAndTaperLaws:
    """Verify 15% weekly volume cap, 3:1 step-loading deloads, competition taper, and poundage lockout."""

    def test_weekly_volume_never_increases_more_than_15_percent(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(
            primary_archetype=PlanArchetype.STAMINA_BUILDER,
            weeks=10,
            baseline_volume=200,
        )
        plan = engine.generate_plan(req)

        prev_loading_arrows = 200
        for micro in plan.microcycles:
            if not micro.is_deload_week:
                assert micro.target_arrows <= int(prev_loading_arrows * 1.15)
                prev_loading_arrows = micro.target_arrows

    def test_three_to_one_step_loading_deload_weeks(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(
            primary_archetype=PlanArchetype.STAMINA_BUILDER,
            weeks=8,
            baseline_volume=200,
        )
        plan = engine.generate_plan(req)

        week3 = plan.microcycles[2]
        week4 = plan.microcycles[3]
        week7 = plan.microcycles[6]
        week8 = plan.microcycles[7]

        assert week4.week_number == 4
        assert week4.is_deload_week is True
        reduction_w4 = (week3.target_arrows - week4.target_arrows) / week3.target_arrows
        assert 0.25 <= reduction_w4 <= 0.30

        assert week8.week_number == 8
        assert week8.is_deload_week is True
        reduction_w8 = (week7.target_arrows - week8.target_arrows) / week7.target_arrows
        assert 0.25 <= reduction_w8 <= 0.30

    def test_competition_peak_taper_weeks_reduce_volume_and_strip_heavy_spt(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(
            primary_archetype=PlanArchetype.COMPETITION_PEAK,
            weeks=8,
            baseline_volume=200,
        )
        plan = engine.generate_plan(req)

        # Peak loading reference prior to taper is week 6
        peak_loading_arrows = plan.microcycles[5].target_arrows
        taper_week_minus_2 = plan.microcycles[6]  # Week 7
        taper_week_minus_1 = plan.microcycles[7]  # Week 8

        assert taper_week_minus_2.target_arrows == int(round(peak_loading_arrows * 0.70))
        assert taper_week_minus_1.target_arrows == int(round(peak_loading_arrows * 0.55))

        for taper_micro in (taper_week_minus_2, taper_week_minus_1):
            for session in taper_micro.sessions:
                for block in session.blocks:
                    assert block.block_type != SessionBlockType.SPT_CONDITIONING.value

    def test_poundage_lockout_within_6_weeks_of_a_tier_event_raises(self) -> None:
        start = date(2026, 11, 2)
        target = start + timedelta(days=35)  # 5 weeks (< 6 weeks lockout)
        with pytest.raises(ValidationError, match="Poundage Lockout Violation"):
            GeneratePlanRequest(
                athlete_id=uuid.uuid4(),
                baseline=AthleteBaselineInput(
                    bow_division=BowDivision.RECURVE,
                    current_draw_weight_lbs=36.0,
                    target_draw_weight_lbs=40.0,
                    current_weekly_arrow_volume=180,
                    weekly_schedule=_make_standard_schedule(),
                ),
                goal=TrainingGoalInput(
                    primary_archetype=PlanArchetype.COMPETITION_PEAK,
                    start_date=start,
                    target_event_date=target,
                    competition_tier="A",
                ),
            )

    def test_poundage_step_up_shifts_at_least_50_percent_arrows_to_short_range_bale(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(
            primary_archetype=PlanArchetype.POUNDAGE_INCREASE,
            weeks=6,
            current_lbs=36.0,
            target_lbs=40.0,
        )
        plan = engine.generate_plan(req)

        week1 = plan.microcycles[0]
        short_range_arrows = sum(
            b.prescribed_arrows
            for s in week1.sessions
            for b in s.blocks
            if b.distance_m <= 5
        )
        assert short_range_arrows >= 0.50 * week1.target_arrows


class TestRangeScheduleAndWADivisionRules:
    """Verify DayAccess distance routing and WA division-specific match play rules."""

    def test_short_distance_days_never_receive_70m_or_50m_scored_or_match_blocks(self) -> None:
        engine = PeriodizationEngineService()
        faults = [FormFault.COLLAPSING_BOW_ARM, FormFault.BACK_TENSION_LOSS]
        req = _make_generate_request(
            division=BowDivision.RECURVE,
            primary_archetype=PlanArchetype.COMPETITION_PEAK,
            weeks=6,
            faults=faults,
        )
        plan = engine.generate_plan(req)

        for micro in plan.microcycles:
            for session in micro.sessions:
                if session.max_distance_m < 18:
                    block_types = {b.block_type for b in session.blocks}
                    assert SessionBlockType.SCORED_DISTANCE.value not in block_types
                    assert SessionBlockType.MATCH_SIMULATION.value not in block_types
                    assert SessionBlockType.TECHNICAL_BLANK_BALE.value in block_types

                    for block in session.blocks:
                        assert block.distance_m <= session.max_distance_m

                    tech_blocks = [
                        b
                        for b in session.blocks
                        if b.block_type == SessionBlockType.TECHNICAL_BLANK_BALE.value
                    ]
                    assert any(
                        b.drill is not None
                        and b.drill.requires_cv_video is True
                        and bool(
                            {f.value for f in faults}.intersection(set(b.drill.faults_addressed))
                        )
                        for b in tech_blocks
                    )

    def test_recurve_and_barebow_match_blocks_use_wa_set_system(self) -> None:
        engine = PeriodizationEngineService()
        for division in (BowDivision.RECURVE, BowDivision.BAREBOW):
            req = _make_generate_request(
                division=division,
                primary_archetype=PlanArchetype.COMPETITION_PEAK,
                weeks=6,
                baseline_volume=240,
            )
            plan = engine.generate_plan(req)
            roadmap = engine.to_roadmap_response(plan)

            match_blocks = [
                b
                for m in roadmap.microcycles
                for s in m.sessions
                for b in s.blocks
                if b.block_type == SessionBlockType.MATCH_SIMULATION
            ]
            assert len(match_blocks) > 0
            for mb in match_blocks:
                assert mb.drill is not None
                assert "Set-System" in mb.drill.title
                assert mb.match_play_spec is not None
                assert mb.match_play_spec.scoring_system == MatchScoringSystem.SET_SYSTEM
                assert mb.match_play_spec.target_set_points_to_win == 6
                assert mb.match_play_spec.arrows_per_end_or_set == 3

    def test_compound_match_blocks_use_15_arrow_cumulative_inner_10_rules(self) -> None:
        engine = PeriodizationEngineService()
        indoor_schedule = [
            DayAccess(day_of_week=2, duration_minutes=90, max_distance_meters=18),
            DayAccess(day_of_week=5, duration_minutes=120, max_distance_meters=18),
        ]
        req = _make_generate_request(
            division=BowDivision.COMPOUND,
            primary_archetype=PlanArchetype.COMPETITION_PEAK,
            weeks=6,
            baseline_volume=240,
            schedule=indoor_schedule,
            round_format=RoundFormat.WA_18M_INDOOR,
        )
        plan = engine.generate_plan(req)
        roadmap = engine.to_roadmap_response(plan)

        match_blocks = [
            b
            for m in roadmap.microcycles
            for s in m.sessions
            for b in s.blocks
            if b.block_type == SessionBlockType.MATCH_SIMULATION
        ]
        assert len(match_blocks) > 0
        for mb in match_blocks:
            assert mb.drill is not None
            assert "Cumulative" in mb.drill.title
            assert mb.prescribed_arrows == 15
            assert mb.match_play_spec is not None
            assert mb.match_play_spec.scoring_system == MatchScoringSystem.CUMULATIVE_15_ARROW
            assert mb.match_play_spec.total_match_arrows == 15
            assert mb.match_play_spec.inner_10_active_18m is True


class TestSmartRecalibrationEngine:
    """Verify evaluate_recalibration triggers for low volume, high RPE/pain, and CV form degradation."""

    def test_recalibration_triggers_on_actual_volume_below_50_percent(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(primary_archetype=PlanArchetype.STAMINA_BUILDER, weeks=6)
        plan = engine.generate_plan(req)

        week1 = plan.microcycles[0]
        # Log only ~20% of prescribed arrows in Week 1
        for session in week1.sessions:
            session.status = SessionStatus.COMPLETED.value
            session.rpe_score = 5
            for block in session.blocks:
                block.actual_arrows = max(1, block.prescribed_arrows // 5)
                block.completed = True

        proposal = engine.evaluate_recalibration(plan.id)
        assert proposal.recalibration_flag is True
        assert "low_volume_adherence_lt_50_pct" in proposal.triggers_detected
        assert len(proposal.proposed_adjustments) >= 1
        assert proposal.proposed_adjustments[0].proposed_target_arrows == week1.target_arrows

    def test_recalibration_triggers_on_three_consecutive_high_rpe_sessions(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(primary_archetype=PlanArchetype.STAMINA_BUILDER, weeks=6)
        plan = engine.generate_plan(req)

        week1 = plan.microcycles[0]
        for idx, session in enumerate(week1.sessions):
            session.status = SessionStatus.COMPLETED.value
            session.rpe_score = 8 if idx < 3 else 6
            for block in session.blocks:
                block.actual_arrows = block.prescribed_arrows
                block.completed = True

        proposal = engine.evaluate_recalibration(plan.id)
        assert proposal.recalibration_flag is True
        assert "rpe_spike_3_consecutive" in proposal.triggers_detected
        assert proposal.proposed_adjustments[0].is_deload_week is True
        assert proposal.proposed_adjustments[0].blank_bale_ratio is not None
        assert proposal.proposed_adjustments[0].blank_bale_ratio >= 0.50

    def test_recalibration_triggers_on_non_empty_pain_flags(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(primary_archetype=PlanArchetype.COMPETITION_PEAK, weeks=6)
        plan = engine.generate_plan(req)

        first_session = plan.microcycles[0].sessions[0]
        first_session.status = SessionStatus.COMPLETED.value
        first_session.rpe_score = 6
        first_session.pain_flags_json = {"bow_shoulder": 4}
        for block in first_session.blocks:
            block.actual_arrows = block.prescribed_arrows

        proposal = engine.evaluate_recalibration(plan.id)
        assert proposal.recalibration_flag is True
        assert "pain_flag_detected" in proposal.triggers_detected
        assert proposal.proposed_adjustments[0].is_deload_week is True

    def test_recalibration_triggers_on_cv_form_degradation_above_5_degrees(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(
            primary_archetype=PlanArchetype.POUNDAGE_INCREASE,
            weeks=6,
            current_lbs=36.0,
            target_lbs=40.0,
        )
        plan = engine.generate_plan(req)

        week1 = plan.microcycles[0]
        cv_job_id = uuid.uuid4()
        engine.register_cv_job_degradation(cv_job_id, 6.8)

        for session in week1.sessions:
            session.status = SessionStatus.COMPLETED.value
            session.rpe_score = 6
            for block in session.blocks:
                block.actual_arrows = block.prescribed_arrows
                block.completed = True
        week1.sessions[0].blocks[1].linked_cv_job_id = cv_job_id

        proposal = engine.evaluate_recalibration(plan.id)
        assert proposal.recalibration_flag is True
        assert "cv_form_degradation_gt_5_deg" in proposal.triggers_detected
        assert "30%" in (proposal.recalibration_reason or "")
        assert proposal.proposed_adjustments[0].blank_bale_ratio == 0.50

    def test_recalibration_skips_coach_locked_microcycles(self) -> None:
        engine = PeriodizationEngineService()
        req = _make_generate_request(primary_archetype=PlanArchetype.STAMINA_BUILDER, weeks=6)
        plan = engine.generate_plan(req)

        plan.microcycles[0].coach_locked = True
        plan.microcycles[0].sessions[0].status = SessionStatus.COMPLETED.value
        plan.microcycles[0].sessions[0].pain_flags_json = {"draw_shoulder": 5}

        proposal = engine.evaluate_recalibration(plan.id)
        assert proposal.recalibration_flag is True
        assert 1 in proposal.coach_locked_weeks_skipped
        assert all(adj.week_number != 1 for adj in proposal.proposed_adjustments)

