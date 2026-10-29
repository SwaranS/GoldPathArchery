"""FastAPI router for the Training Plans module with BackgroundTasks and strict role checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, status

from app.schemas.training_plan import (
    ApplyRecalibrationRequest,
    BowDivision,
    CoachOverrideRequest,
    GeneratePlanRequest,
    MicrocycleRoadmapItem,
    SessionLogUpdateRequest,
    TrainingPlanRoadmapResponse,
    TrainingSessionDetailResponse,
)
from app.services.periodization_engine import PeriodizationEngineService

router = APIRouter(prefix="/api/v1/training-plans", tags=["training-plans"])

_default_engine_service = PeriodizationEngineService()


async def get_periodization_service() -> PeriodizationEngineService:
    """Dependency provider for PeriodizationEngineService."""
    return _default_engine_service


@dataclass
class ActorContext:
    """Authenticated caller identity and role for permission enforcement."""

    actor_id: Optional[UUID]
    role: Literal["athlete", "coach"]


async def get_current_actor(
    x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
    x_actor_role: Optional[str] = Header(default=None, alias="X-Actor-Role"),
) -> ActorContext:
    """Extract caller identity and role from request headers."""
    parsed_id: Optional[UUID] = None
    if x_actor_id:
        try:
            parsed_id = UUID(x_actor_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Actor-Id UUID header.",
            ) from exc

    normalized_role = (x_actor_role or "athlete").strip().lower()
    if normalized_role not in ("athlete", "coach"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Unsupported role '{normalized_role}'. Expected 'athlete' or 'coach'.",
        )
    return ActorContext(
        actor_id=parsed_id,
        role="coach" if normalized_role == "coach" else "athlete",
    )


def _verify_plan_access(
    actor: ActorContext,
    athlete_id: UUID,
    coach_id: Optional[UUID],
) -> None:
    """Ensure caller is either the owning athlete or the linked coach."""
    if actor.actor_id is None:
        if actor.role == "coach":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Coach operations require an explicit X-Actor-Id header.",
            )
        return

    if actor.role == "athlete" and actor.actor_id == athlete_id:
        return
    if actor.role == "coach" and coach_id is not None and actor.actor_id == coach_id:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Actor does not have permission to access or modify this training plan.",
    )


def _verify_coach_override_permission(
    actor: ActorContext,
    coach_id: Optional[UUID],
) -> None:
    """Strictly enforce that only the linked coach can perform microcycle coach-override actions."""
    if actor.role != "coach":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Coach override permission denied: athletes cannot override or lock microcycles.",
        )
    if actor.actor_id is None or coach_id is None or actor.actor_id != coach_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Coach override permission denied: caller is not the linked coach for this plan.",
        )


async def _run_generate_full_plan_bg(
    service: PeriodizationEngineService,
    plan_id: UUID,
    request: GeneratePlanRequest,
) -> None:
    """Async background task wrapper for PeriodizationEngineService.generate_full_plan."""
    service.generate_full_plan(plan_id, request)


async def _run_evaluate_recalibration_bg(
    service: PeriodizationEngineService,
    plan_id: UUID,
) -> None:
    """Async background task wrapper for PeriodizationEngineService.evaluate_recalibration."""
    service.evaluate_recalibration(plan_id)


@router.post(
    "/generate",
    response_model=TrainingPlanRoadmapResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_training_plan(
    request: GeneratePlanRequest,
    background_tasks: BackgroundTasks,
    actor: ActorContext = Depends(get_current_actor),
    service: PeriodizationEngineService = Depends(get_periodization_service),
) -> TrainingPlanRoadmapResponse:
    """
    Validate GeneratePlanRequest, persist initial TrainingPlan record, and dispatch
    PeriodizationEngineService.generate_full_plan via FastAPI BackgroundTasks.
    """
    _verify_plan_access(actor, request.athlete_id, request.coach_id)
    initial_plan = service.create_initial_plan(request)
    background_tasks.add_task(_run_generate_full_plan_bg, service, initial_plan.id, request)
    return service.to_roadmap_response(initial_plan)


@router.get(
    "/{plan_id}/roadmap",
    response_model=TrainingPlanRoadmapResponse,
    status_code=status.HTTP_200_OK,
)
async def get_training_plan_roadmap(
    plan_id: UUID,
    actor: ActorContext = Depends(get_current_actor),
    service: PeriodizationEngineService = Depends(get_periodization_service),
) -> TrainingPlanRoadmapResponse:
    """
    Return macrocycle phases, weekly planned vs. actual arrow volume arrays,
    pillar breakdown percentages, and any active RecalibrationProposalResponse.
    """
    try:
        plan = service.get_plan(plan_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Training plan {plan_id} not found.",
        ) from exc

    _verify_plan_access(actor, plan.athlete_id, plan.coach_id)
    return service.to_roadmap_response(plan)


@router.get(
    "/sessions/{session_id}",
    response_model=TrainingSessionDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def get_training_session_detail(
    session_id: UUID,
    actor: ActorContext = Depends(get_current_actor),
    service: PeriodizationEngineService = Depends(get_periodization_service),
) -> TrainingSessionDetailResponse:
    """Return the hydrated daily session with ordered SessionBlock items and drill instructions."""
    try:
        plan, _micro, session = service.get_session_with_context(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Training session {session_id} not found.",
        ) from exc

    _verify_plan_access(actor, plan.athlete_id, plan.coach_id)
    division_str = plan.baseline_json.get("bow_division", BowDivision.RECURVE.value)
    return service.to_session_detail_response(session, BowDivision(division_str))


@router.patch(
    "/sessions/{session_id}/log",
    response_model=TrainingSessionDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def log_training_session(
    session_id: UUID,
    payload: SessionLogUpdateRequest,
    background_tasks: BackgroundTasks,
    actor: ActorContext = Depends(get_current_actor),
    service: PeriodizationEngineService = Depends(get_periodization_service),
) -> TrainingSessionDetailResponse:
    """
    Support Mode A (Quick-Log: actual arrows, RPE 1-10, pain flags) and Mode B (Live Runner:
    linking scorecard_id, cv_job_id, and SPT hold reps). Triggers evaluate_recalibration in background.
    """
    try:
        plan, _micro, _sess = service.get_session_with_context(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Training session {session_id} not found.",
        ) from exc

    _verify_plan_access(actor, plan.athlete_id, plan.coach_id)
    updated_plan, updated_session = service.log_session(session_id, payload)
    background_tasks.add_task(_run_evaluate_recalibration_bg, service, updated_plan.id)

    division_str = updated_plan.baseline_json.get("bow_division", BowDivision.RECURVE.value)
    return service.to_session_detail_response(updated_session, BowDivision(division_str))


@router.post(
    "/{plan_id}/recalibrate",
    response_model=TrainingPlanRoadmapResponse,
    status_code=status.HTTP_200_OK,
)
async def apply_plan_recalibration(
    plan_id: UUID,
    payload: Optional[ApplyRecalibrationRequest] = Body(default=None),
    actor: ActorContext = Depends(get_current_actor),
    service: PeriodizationEngineService = Depends(get_periodization_service),
) -> TrainingPlanRoadmapResponse:
    """Apply an approved recalibration diff to future unlocked TrainingMicrocycle and TrainingSession rows."""
    try:
        plan = service.get_plan(plan_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Training plan {plan_id} not found.",
        ) from exc

    _verify_plan_access(actor, plan.athlete_id, plan.coach_id)
    updated_plan = service.apply_recalibration(plan_id, payload)
    return service.to_roadmap_response(updated_plan)


@router.patch(
    "/microcycles/{microcycle_id}/coach-override",
    response_model=MicrocycleRoadmapItem,
    status_code=status.HTTP_200_OK,
)
async def coach_override_microcycle(
    microcycle_id: UUID,
    payload: CoachOverrideRequest,
    actor: ActorContext = Depends(get_current_actor),
    service: PeriodizationEngineService = Depends(get_periodization_service),
) -> MicrocycleRoadmapItem:
    """Allow a linked coach to lock/modify weekly volume or swap drills on a microcycle."""
    try:
        plan, _micro = service.get_microcycle_with_context(microcycle_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Training microcycle {microcycle_id} not found.",
        ) from exc

    _verify_coach_override_permission(actor, plan.coach_id)

    try:
        updated_plan, updated_micro = service.apply_coach_override(microcycle_id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    division_str = updated_plan.baseline_json.get("bow_division", BowDivision.RECURVE.value)
    division = BowDivision(division_str)
    return MicrocycleRoadmapItem(
        id=updated_micro.id,
        plan_id=updated_micro.plan_id,
        mesocycle_id=updated_micro.mesocycle_id,
        week_number=updated_micro.week_number,
        target_arrows=updated_micro.target_arrows,
        actual_arrows=updated_micro.actual_arrows,
        is_deload_week=updated_micro.is_deload_week,
        coach_locked=updated_micro.coach_locked,
        sessions=[
            service.to_session_detail_response(sess, division)
            for sess in updated_micro.sessions
        ],
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application with the Training Plans router registered."""
    fastapi_app = FastAPI(
        title="GoldPathArchery API",
        version="1.0.0",
        description="Periodized World Archery Training Plans, Live Session Runner & Smart Recalibration Engine.",
    )
    fastapi_app.include_router(router)
    return fastapi_app


app = create_app()

