# GoldPathArchery — Training Plans Module Instructions (AGENTS.md)

## 1. Project Context & Architecture

You are an expert Python/FastAPI backend and web frontend architect working on **GoldPathArchery**.
We are building the `training_plans` module: a dynamic, periodized archery training plan generator, live session runner, and smart recalibration engine.

## 2. Strict Architectural Standards

- **Backend Stack**: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic for migrations.
- **Layer Separation**: Strictly enforce `Router (api/v1/routers/)` -> `Service Layer (services/)` -> `Repository / CRUD (repositories/)` -> `Models (models/)`. Never write database queries directly inside FastAPI route handlers.
- **Async Execution**: Plan generation (`POST /api/v1/training-plans/generate`) and post-session recalibration checks must be offloaded to background workers / `BackgroundTasks` (or Celery/Redis) rather than blocking HTTP request threads.
- **Testing**: Write `pytest` unit and integration tests for every service and endpoint (`tests/test_training_plans.py`).

## 3. World Archery (WA) Domain Laws (CRITICAL)

1. **Granular Ring Storage**: Never store only aggregated integer scores. Scored blocks must link to end-by-end arrow values (`X`, `10`, `9` ... `M`) to compute X-to-10 ratios and 1st-half vs. 2nd-half score decay.
2. **Division-Specific Match Play**:
   - `recurve` and `barebow` match-play drills MUST use the **Set System** (3 arrows/set, first to 6 set points).
   - `compound` match-play drills MUST use **Cumulative Scoring** (15 arrows total, inner-10 ring active for 18m indoor).
3. **Periodization & Safety Guardrails**:
   - **15% Weekly Volume Cap**: Weekly arrow volume must never increase by more than 15% week-over-week during progressive overload phases.
   - **3:1 Step-Loading Rule**: Every 3 weeks of progressive volume/load increase must be followed by 1 Deload/Assessment week (-25% to -30% arrow volume).
   - **Poundage Lockout**: If `target_draw_weight_lbs > current_draw_weight_lbs`, prohibit scheduling a mechanical bow weight increase within 6 weeks of an A-tier competition. When a poundage step-up occurs, shift >=50% of arrows to short-range/blank-bale (`<=5m`) for 7–10 days.
   - **Taper Window**: For `COMPETITION_PEAK` plans, Weeks -2 and -1 before `target_event_date` must reduce arrow volume by 30% and 45% respectively, and strip all heavy SPT Power/Endurance blocks to prevent DOMS.

## 4. Module File Boundaries

When executing tasks for the Training Plans feature, isolate changes to:

- `app/models/training_plan.py` (SQLAlchemy models)
- `app/schemas/training_plan.py` (Pydantic v2 request/response schemas)
- `app/services/periodization_engine.py` (Macrocycle/Microcycle/Session generator & recalibration logic)
- `app/api/v1/routers/training_plans.py` (FastAPI endpoints)
- `app/data/drill_catalog_seed.json` (Seed library for Technical, SPT, Scored, and Match drills)
- `tests/training_plans/` (Unit & API tests)

## 5. Human Checkpoints

- Always pause for Artifact Review before running Alembic database migrations or modifying existing `scorecard` or `biomechanics` tables.
