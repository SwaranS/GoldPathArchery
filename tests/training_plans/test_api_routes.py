"""FastAPI TestClient and AsyncClient integration tests for Training Plans API routes (Task 3)."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

import pytest

from app.api.v1.routers.training_plans import get_periodization_service
from app.main import app
from app.services.periodization_engine import PeriodizationEngineService


class _ASGIResponse:
    """HTTP response returned by _InProcessASGIClient."""

    def __init__(self, status_code: int, headers: dict[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = body
        self.text = body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


def _drive_coroutine(coro: Any) -> Any:
    """Drive a pure-Python ASGI coroutine to completion without OS socketpairs."""
    try:
        while True:
            coro.send(None)
    except StopIteration as exc:
        return exc.value


class _InProcessASGIClient:
    """Fast in-process ASGI client that executes FastAPI apps & BackgroundTasks without OS sockets."""

    def __init__(self, asgi_app: Any) -> None:
        self._app = asgi_app

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> _ASGIResponse:
        parsed = urlsplit(url)
        raw_body = b""
        req_headers: list[tuple[bytes, bytes]] = [(b"host", b"testserver")]
        if json_body is not None:
            raw_body = json.dumps(json_body).encode("utf-8")
            req_headers.append((b"content-type", b"application/json"))
            req_headers.append((b"content-length", str(len(raw_body)).encode("ascii")))
        if headers:
            for k, v in headers.items():
                req_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": parsed.path,
            "raw_path": parsed.path.encode("ascii"),
            "query_string": parsed.query.encode("ascii"),
            "headers": req_headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }

        body_sent = False
        status_code = 500
        resp_headers: dict[str, str] = {}
        body_chunks: list[bytes] = []

        async def receive() -> dict[str, Any]:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                for hk, hv in message.get("headers", []):
                    resp_headers[hk.decode("latin-1").lower()] = hv.decode("latin-1")
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))

        _drive_coroutine(self._app(scope, receive, send))
        return _ASGIResponse(status_code, resp_headers, b"".join(body_chunks))

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> _ASGIResponse:
        return self.request("GET", url, headers=headers)

    def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> _ASGIResponse:
        return self.request("POST", url, json_body=json, headers=headers)

    def patch(
        self,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> _ASGIResponse:
        return self.request("PATCH", url, json_body=json, headers=headers)


@pytest.fixture()
def engine_service() -> PeriodizationEngineService:
    service = PeriodizationEngineService()

    async def _override_service() -> PeriodizationEngineService:
        return service

    app.dependency_overrides[get_periodization_service] = _override_service
    yield service
    app.dependency_overrides.clear()


@pytest.fixture()
def client(engine_service: PeriodizationEngineService) -> _InProcessASGIClient:
    return _InProcessASGIClient(app)


def _build_generate_payload(
    *,
    athlete_id: uuid.UUID | None = None,
    coach_id: uuid.UUID | None = None,
    primary_archetype: str = "competition_peak",
    secondary_archetype: str | None = None,
    weeks: int = 8,
    current_lbs: float = 38.0,
    target_lbs: float = 38.0,
) -> dict[str, Any]:
    start = date(2026, 11, 2)
    target = start + timedelta(days=weeks * 7)
    return {
        "athlete_id": str(athlete_id or uuid.uuid4()),
        "coach_id": str(coach_id) if coach_id else None,
        "baseline": {
            "bow_division": "recurve",
            "current_draw_weight_lbs": current_lbs,
            "target_draw_weight_lbs": target_lbs,
            "current_weekly_arrow_volume": 200,
            "identified_faults": ["collapsing_bow_arm", "plucking_release"],
            "weekly_schedule": [
                {"day_of_week": 1, "duration_minutes": 60, "max_distance_meters": 5},
                {"day_of_week": 3, "duration_minutes": 60, "max_distance_meters": 10},
                {"day_of_week": 5, "duration_minutes": 120, "max_distance_meters": 70},
                {"day_of_week": 6, "duration_minutes": 120, "max_distance_meters": 70},
            ],
        },
        "goal": {
            "primary_archetype": primary_archetype,
            "secondary_archetype": secondary_archetype,
            "round_format": "wa_720_70m",
            "start_date": start.isoformat(),
            "target_event_date": target.isoformat(),
            "competition_tier": "A",
        },
    }


class TestGenerateAndRoadmapEndpoints:
    """Verify POST /generate (202 + BackgroundTasks + Poundage Lockout) and GET /roadmap."""

    def test_generate_plan_returns_202_and_builds_full_plan_in_background(
        self,
        client: TestClient,
    ) -> None:
        athlete_id = uuid.uuid4()
        coach_id = uuid.uuid4()
        payload = _build_generate_payload(athlete_id=athlete_id, coach_id=coach_id, weeks=8)

        resp = client.post(
            "/api/v1/training-plans/generate",
            json=payload,
            headers={"X-Actor-Id": str(athlete_id), "X-Actor-Role": "athlete"},
        )
        assert resp.status_code == 202
        initial_data = resp.json()
        plan_id = initial_data["id"]

        # BackgroundTasks executes after response in TestClient; fetch roadmap to verify hydration
        roadmap_resp = client.get(
            f"/api/v1/training-plans/{plan_id}/roadmap",
            headers={"X-Actor-Id": str(athlete_id), "X-Actor-Role": "athlete"},
        )
        assert roadmap_resp.status_code == 200
        roadmap = roadmap_resp.json()

        assert roadmap["status"] == "active"
        assert len(roadmap["mesocycles"]) >= 2
        assert len(roadmap["microcycles"]) == 8
        assert len(roadmap["weekly_planned_arrows"]) == 8
        assert len(roadmap["weekly_actual_arrows"]) == 8
        assert all(v > 0 for v in roadmap["weekly_planned_arrows"])
        assert all(v == 0 for v in roadmap["weekly_actual_arrows"])
        assert set(roadmap["pillar_breakdown_pct"].keys()) == {
            "scored_distance",
            "technical_blank_bale",
            "spt_conditioning",
            "match_simulation",
        }
        assert pytest.approx(sum(roadmap["pillar_breakdown_pct"].values()), abs=0.5) == 100.0

    def test_generate_blocks_poundage_increase_secondary_focus_when_comp_peak_under_6_weeks(
        self,
        client: TestClient,
    ) -> None:
        payload = _build_generate_payload(
            primary_archetype="competition_peak",
            secondary_archetype="poundage_increase",
            weeks=5,  # 35 days (< 6 weeks / 42 days)
        )
        resp = client.post("/api/v1/training-plans/generate", json=payload)
        assert resp.status_code == 422
        assert "Poundage Lockout Violation" in str(resp.json())


class TestSessionDetailAndDualModeLogging:
    """Verify GET /sessions/{session_id} and PATCH /sessions/{session_id}/log (Mode A & Mode B)."""

    def test_get_session_detail_returns_ordered_blocks_and_drill_instructions(
        self,
        client: TestClient,
    ) -> None:
        athlete_id = uuid.uuid4()
        payload = _build_generate_payload(athlete_id=athlete_id, weeks=6)
        gen_resp = client.post(
            "/api/v1/training-plans/generate",
            json=payload,
            headers={"X-Actor-Id": str(athlete_id), "X-Actor-Role": "athlete"},
        )
        plan_id = gen_resp.json()["id"]
        roadmap = client.get(f"/api/v1/training-plans/{plan_id}/roadmap").json()

        first_session_id = roadmap["microcycles"][0]["sessions"][0]["id"]
        sess_resp = client.get(
            f"/api/v1/training-plans/sessions/{first_session_id}",
            headers={"X-Actor-Id": str(athlete_id), "X-Actor-Role": "athlete"},
        )
        assert sess_resp.status_code == 200
        sess_data = sess_resp.json()

        blocks = sess_data["blocks"]
        assert len(blocks) >= 2
        assert [b["block_order"] for b in blocks] == sorted(b["block_order"] for b in blocks)
        for blk in blocks:
            assert blk["drill"] is not None
            assert len(blk["drill"]["instructions"]) > 10

    def test_patch_session_log_mode_a_quick_log_triggers_background_recalibration(
        self,
        client: TestClient,
    ) -> None:
        athlete_id = uuid.uuid4()
        payload = _build_generate_payload(athlete_id=athlete_id, weeks=6)
        plan_id = client.post("/api/v1/training-plans/generate", json=payload).json()["id"]
        roadmap = client.get(f"/api/v1/training-plans/{plan_id}/roadmap").json()
        session_id = roadmap["microcycles"][0]["sessions"][0]["id"]

        # Mode A (Quick-Log): actual_arrows, RPE 1-10, and pain_flags
        log_resp = client.patch(
            f"/api/v1/training-plans/sessions/{session_id}/log",
            json={
                "status": "completed",
                "actual_arrows": 90,
                "rpe_score": 9,
                "pain_flags": {"bow_shoulder": 4},
                "notes": "Quick-log session with mild bow shoulder pinch.",
            },
            headers={"X-Actor-Id": str(athlete_id), "X-Actor-Role": "athlete"},
        )
        assert log_resp.status_code == 200
        logged_sess = log_resp.json()
        assert logged_sess["status"] == "completed"
        assert logged_sess["rpe_score"] == 9
        assert logged_sess["pain_flags_json"]["bow_shoulder"] == 4
        assert sum(b["actual_arrows"] for b in logged_sess["blocks"]) == 90

        # Verify background recalibration evaluated the pain flag and attached proposal to roadmap
        updated_roadmap = client.get(f"/api/v1/training-plans/{plan_id}/roadmap").json()
        assert updated_roadmap["recalibration_flag"] is True
        assert updated_roadmap["weekly_actual_arrows"][0] == 90
        assert updated_roadmap["active_recalibration_proposal"] is not None
        assert "pain_flag_detected" in updated_roadmap["active_recalibration_proposal"]["triggers_detected"]

    def test_patch_session_log_mode_b_live_runner_links_scorecard_cv_job_and_spt_reps(
        self,
        client: TestClient,
    ) -> None:
        athlete_id = uuid.uuid4()
        payload = _build_generate_payload(athlete_id=athlete_id, weeks=6)
        plan_id = client.post("/api/v1/training-plans/generate", json=payload).json()["id"]
        roadmap = client.get(f"/api/v1/training-plans/{plan_id}/roadmap").json()

        # Select a full-range session (day_of_week=5, 70m)
        full_session = roadmap["microcycles"][0]["sessions"][2]
        session_id = full_session["id"]
        blocks = full_session["blocks"]

        scorecard_id = uuid.uuid4()
        cv_job_id = uuid.uuid4()

        block_updates = []
        for blk in blocks:
            block_updates.append(
                {
                    "block_id": blk["id"],
                    "actual_arrows": blk["prescribed_arrows"],
                    "completed": True,
                    "scorecard_id": str(scorecard_id) if blk["block_type"] == "scored_distance" else None,
                    "cv_job_id": str(cv_job_id) if blk["block_type"] == "technical_blank_bale" else None,
                    "spt_hold_reps": 8 if blk["block_type"] == "spt_conditioning" else None,
                    "cv_form_degradation_deg": 6.5 if blk["block_type"] == "technical_blank_bale" else None,
                }
            )

        log_resp = client.patch(
            f"/api/v1/training-plans/sessions/{session_id}/log",
            json={
                "status": "completed",
                "rpe_score": 6,
                "blocks": block_updates,
            },
            headers={"X-Actor-Id": str(athlete_id), "X-Actor-Role": "athlete"},
        )
        assert log_resp.status_code == 200
        logged = log_resp.json()

        scored_blk = next(b for b in logged["blocks"] if b["block_type"] == "scored_distance")
        tech_blk = next(b for b in logged["blocks"] if b["block_type"] == "technical_blank_bale")
        assert scored_blk["linked_scorecard_id"] == str(scorecard_id)
        assert tech_blk["linked_cv_job_id"] == str(cv_job_id)

        # CV form degradation > 5.0 deg triggers background recalibration
        updated_roadmap = client.get(f"/api/v1/training-plans/{plan_id}/roadmap").json()
        assert updated_roadmap["recalibration_flag"] is True
        assert (
            "cv_form_degradation_gt_5_deg"
            in updated_roadmap["active_recalibration_proposal"]["triggers_detected"]
        )


class TestRecalibrateAndCoachOverrideEndpoints:
    """Verify POST /{plan_id}/recalibrate and PATCH /microcycles/{id}/coach-override role checks."""

    def test_apply_recalibration_updates_unlocked_microcycles_and_clears_flag(
        self,
        client: TestClient,
    ) -> None:
        athlete_id = uuid.uuid4()
        coach_id = uuid.uuid4()
        payload = _build_generate_payload(athlete_id=athlete_id, coach_id=coach_id, weeks=6)
        plan_id = client.post("/api/v1/training-plans/generate", json=payload).json()["id"]
        roadmap = client.get(f"/api/v1/training-plans/{plan_id}/roadmap").json()

        week1_original_arrows = roadmap["microcycles"][0]["target_arrows"]
        first_session_id = roadmap["microcycles"][0]["sessions"][0]["id"]

        # Trigger pain flag recalibration
        client.patch(
            f"/api/v1/training-plans/sessions/{first_session_id}/log",
            json={"status": "completed", "actual_arrows": 60, "rpe_score": 9, "pain_flags": {"lower_back": 5}},
        )

        recal_resp = client.post(
            f"/api/v1/training-plans/{plan_id}/recalibrate",
            json={"approved": True},
            headers={"X-Actor-Id": str(athlete_id), "X-Actor-Role": "athlete"},
        )
        assert recal_resp.status_code == 200
        recal_roadmap = recal_resp.json()

        assert recal_roadmap["recalibration_flag"] is False
        assert recal_roadmap["microcycles"][0]["target_arrows"] < week1_original_arrows
        assert recal_roadmap["microcycles"][0]["is_deload_week"] is True

    def test_coach_override_enforces_strict_role_checks_and_allows_linked_coach(
        self,
        client: TestClient,
        engine_service: PeriodizationEngineService,
    ) -> None:
        athlete_id = uuid.uuid4()
        coach_id = uuid.uuid4()
        unlinked_coach_id = uuid.uuid4()

        payload = _build_generate_payload(athlete_id=athlete_id, coach_id=coach_id, weeks=6)
        plan_id = client.post("/api/v1/training-plans/generate", json=payload).json()["id"]
        roadmap = client.get(f"/api/v1/training-plans/{plan_id}/roadmap").json()

        microcycle_id = roadmap["microcycles"][1]["id"]
        first_block_id = roadmap["microcycles"][1]["sessions"][0]["blocks"][1]["id"]
        new_drill_id = str(engine_service.drills[6].id)  # Poundage Step-Up Blank Bale drill

        # 1. Athlete attempting coach-override MUST receive 403 Forbidden
        athlete_resp = client.patch(
            f"/api/v1/training-plans/microcycles/{microcycle_id}/coach-override",
            json={"coach_locked": True, "target_arrows": 180},
            headers={"X-Actor-Id": str(athlete_id), "X-Actor-Role": "athlete"},
        )
        assert athlete_resp.status_code == 403

        # 2. Unlinked coach attempting coach-override MUST receive 403 Forbidden
        unlinked_resp = client.patch(
            f"/api/v1/training-plans/microcycles/{microcycle_id}/coach-override",
            json={"coach_locked": True, "target_arrows": 180},
            headers={"X-Actor-Id": str(unlinked_coach_id), "X-Actor-Role": "coach"},
        )
        assert unlinked_resp.status_code == 403

        # 3. Linked coach succeeds in locking week, modifying volume, and swapping a drill
        coach_resp = client.patch(
            f"/api/v1/training-plans/microcycles/{microcycle_id}/coach-override",
            json={
                "coach_locked": True,
                "target_arrows": 180,
                "drill_swaps": [
                    {
                        "block_id": first_block_id,
                        "new_drill_id": new_drill_id,
                        "prescribed_arrows": 42,
                    }
                ],
            },
            headers={"X-Actor-Id": str(coach_id), "X-Actor-Role": "coach"},
        )
        assert coach_resp.status_code == 200
        updated_micro = coach_resp.json()
        assert updated_micro["coach_locked"] is True
        swapped_block = next(
            b for b in updated_micro["sessions"][0]["blocks"] if b["id"] == first_block_id
        )
        assert swapped_block["drill_id"] == new_drill_id
        assert swapped_block["prescribed_arrows"] == 42


def test_async_client_end_to_end_flow(client: _InProcessASGIClient) -> None:
    """Verify coach & athlete end-to-end ASGI flow."""
    athlete_id = uuid.uuid4()
    coach_id = uuid.uuid4()
    payload = _build_generate_payload(athlete_id=athlete_id, coach_id=coach_id, weeks=6)

    gen_res = client.post(
        "/api/v1/training-plans/generate",
        json=payload,
        headers={"X-Actor-Id": str(athlete_id), "X-Actor-Role": "athlete"},
    )
    assert gen_res.status_code == 202
    plan_id = gen_res.json()["id"]

    roadmap_res = client.get(
        f"/api/v1/training-plans/{plan_id}/roadmap",
        headers={"X-Actor-Id": str(coach_id), "X-Actor-Role": "coach"},
    )
    assert roadmap_res.status_code == 200
    assert len(roadmap_res.json()["microcycles"]) == 6

