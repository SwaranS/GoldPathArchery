"""Transactional scoring boundary. Configuration is copied, never dereferenced on resume."""
import hashlib
import json
import math
import uuid
from collections import Counter, defaultdict
from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import AthleteProfile
from accounts.permissions import can
from .equipment_services import revision_snapshot
from .models import (
    ArrowShot, Equipment, MutationReceipt, PhysicalArrow, RoundDefinition,
    ScoreChangeAudit, ScoringSession, ScoringRuleSet, TargetFace,
)


class Conflict(Exception):
    pass


def authorize(actor, athlete, write=False):
    if not can(actor, athlete, "log_scores" if write else "view"):
        raise PermissionDenied


def stage_snapshot(target, rules, distance, ends, arrows):
    target.full_clean()
    rules.full_clean()
    if not target.active or not rules.active:
        raise ValidationError("Choose active target and scoring rules.")
    if not math.isfinite(distance) or distance <= 0 or not 1 <= ends <= 100 or not 1 <= arrows <= 36:
        raise ValidationError("Use positive distance, 1–100 ends and 1–36 arrows per end.")
    return dict(distance_m=distance, ends=ends, arrows_per_end=arrows,
                diameter_cm=target.diameter_cm, layout=target.layout,
                geometry=deepcopy(target.geometry), rules=deepcopy(rules.rules),
                target_name=target.name, rules_name=rules.name)


@transaction.atomic
def start(actor, athlete, data):
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete.pk)
    authorize(actor, athlete, True)
    mode, context = data["mode"], data["context"]
    if mode not in ("round", "custom") or context not in ("training", "competition"):
        raise ValidationError("Invalid session mode or context.")
    division = data.get("division", athlete.discipline)
    if division not in ("recurve", "compound", "barebow"):
        raise ValidationError("Choose a bow division.")
    if mode == "round":
        definition = RoundDefinition.objects.get(pk=data["round"], active=True)
        stages = [stage_snapshot(s.target, s.rules, s.distance_m, s.ends, s.arrows_per_end)
                  for s in definition.stages.select_related("target", "rules")]
        if not stages:
            raise ValidationError("The round needs at least one stage.")
        name, division = definition.name, definition.division
        category, verification_required = definition.category, definition.verification_required
    else:
        if context != "training":
            raise ValidationError("Custom training uses the training context.")
        stages = [stage_snapshot(TargetFace.objects.get(pk=data["target"]),
                  ScoringRuleSet.objects.get(pk=data["rules"]), float(data["distance_m"]),
                  int(data["ends"]), int(data["arrows_per_end"]))]
        name, category, verification_required = "Custom training", data.get("category", ""), False
    equipment = {}
    for field, kind in (("bow", "bow"), ("arrow_set", "arrow_set")):
        if data.get(field):
            item = Equipment.objects.get(pk=data[field], athlete=athlete, kind=kind, active=True)
            if kind == "bow" and item.division != division:
                raise ValidationError("Bow division must match the session.")
            equipment[field] = revision_snapshot(item)
    snapshot = dict(evaluator=1, name=name, division=division, category=category,
                    verification_required=verification_required, stages=stages)
    session = ScoringSession.objects.create(athlete=athlete, mode=mode, context=context,
                                           snapshot=snapshot, equipment=equipment)
    ScoreChangeAudit.objects.create(session=session, actor=actor, operation="start", after=snapshot)
    return session


def slots(session):
    position = 0
    for stage_index, stage in enumerate(session.snapshot["stages"]):
        for end in range(1, stage["ends"] + 1):
            for arrow in range(1, stage["arrows_per_end"] + 1):
                yield position, stage_index, end, arrow, stage
                position += 1


def score_options(stage):
    return {"M": (0, False), **{z["symbol"]: (z["points"], z.get("x", False)) for z in stage["rules"]["zones"]}}


def suggest(stage, x, y, spot):
    if not all(math.isfinite(v) and -1 <= v <= 1 for v in (x, y)):
        raise ValidationError("Tap inside the target canvas.")
    spots = stage["geometry"]["spots"]
    if not 0 <= spot < len(spots):
        raise ValidationError("Choose a valid face spot.")
    cx, cy, radius = spots[spot]
    distance = math.hypot(x - cx, y - cy) / radius
    # A mathematical point on the line earns the inner value. No shaft calibration is implied.
    return next((z["symbol"] for z in stage["rules"]["zones"] if distance <= z["radius"] + 1e-12), "M")


def shot_state(shot):
    if shot is None:
        return {}
    return {k: getattr(shot, k) for k in ("position", "symbol", "points", "is_x", "x", "y", "spot", "suggested_symbol", "arrow_id", "arrow_snapshot")}


@transaction.atomic
def mutate(actor, session_id, data):
    # Athlete lock is shared with relationship mutations; grants are checked inside it.
    athlete_id = ScoringSession.objects.values_list("athlete_id", flat=True).get(pk=session_id)
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    verifying = data.get("action") == "verify" and actor.is_active and actor.is_staff and actor.has_perm("scoring.change_scoringsession")
    if not verifying:
        authorize(actor, athlete, True)
    session = ScoringSession.objects.select_for_update().get(pk=session_id)
    key = uuid.UUID(str(data["key"]))
    receipt = MutationReceipt.objects.filter(session=session, key=key).first()
    if receipt:
        if receipt.payload != data:
            raise Conflict("Retry key already used for different data.")
        return session
    if int(data["version"]) != session.version:
        raise Conflict("The session changed. Reload before editing.")
    action = data["action"]
    if session.verified_at and action not in ("delete", "restore"):
        raise ValidationError("Verified competition scores are locked.")
    if session.deleted_at and action != "restore":
        raise ValidationError("Restore this session first.")
    reason = str(data.get("reason", ""))[:500]
    if action == "shot":
        if session.status not in ("draft",):
            raise ValidationError("Resume or reopen the session before scoring.")
        position = int(data["position"])
        slot = next((s for s in slots(session) if s[0] == position), None)
        if slot is None:
            raise ValidationError("Shot is outside this round.")
        stage = slot[4]
        shot = session.shots.filter(position=position).first()
        before = shot_state(shot)
        x = y = spot = None
        suggested = ""
        if data.get("method") == "tap":
            x, y, spot = float(data["x"]), float(data["y"]), int(data["spot"])
            suggested = suggest(stage, x, y, spot)
            symbol = data.get("symbol") or suggested
            if symbol != suggested and not reason:
                raise ValidationError("Explain the observed score override.")
        elif data.get("method") == "manual":
            symbol = data["symbol"]
        else:
            raise ValidationError("Choose manual or tap entry.")
        if symbol not in score_options(stage):
            raise ValidationError("Score is not valid for these rules.")
        arrow = None
        if data.get("arrow"):
            candidates = PhysicalArrow.objects.select_related("arrow_set").filter(
                arrow_set__athlete=athlete, arrow_set_id=session.equipment.get("arrow_set", {}).get("id"))
            # Preserve historical identity when correcting an existing archived arrow;
            # new assignments still require active equipment.
            if shot is None or str(shot.arrow_id) != str(data["arrow"]):
                candidates = candidates.filter(active=True, arrow_set__active=True)
            arrow = candidates.get(pk=data["arrow"])
        points, is_x = score_options(stage)[symbol]
        if shot is None:
            shot = ArrowShot(session=session, position=position)
        shot.symbol, shot.points, shot.is_x = symbol, points, is_x
        shot.x, shot.y, shot.spot, shot.suggested_symbol = x, y, spot, suggested
        previous_arrow_id = shot.arrow_id
        shot.arrow = arrow
        if arrow is None:
            shot.arrow_snapshot = {}
        elif previous_arrow_id != arrow.pk or not shot.arrow_snapshot:
            shot.arrow_snapshot = dict(id=arrow.pk, identifier=arrow.identifier, set_id=arrow.arrow_set_id,
                                       set_name=session.equipment["arrow_set"]["name"],
                                       set_revision_id=session.equipment["arrow_set"].get("revision_id"))
        shot.save()
        after = shot_state(shot)
    else:
        before = dict(status=session.status, invalidated=session.invalidated, deleted=bool(session.deleted_at), verified=bool(session.verified_at))
        if action in ("pause", "resume", "review"):
            if session.status == "completed":
                raise ValidationError("Reopen completed training before changing it.")
            session.status = {"pause": "paused", "resume": "draft", "review": "review"}[action]
        elif action == "complete":
            if session.status != "review":
                raise ValidationError("Review scores before completion.")
            if session.shots.count() != sum(s["ends"] * s["arrows_per_end"] for s in session.snapshot["stages"]):
                raise ValidationError("Record every arrow before completion; blanks are not misses.")
            session.status, session.completed_at = "completed", timezone.now()
        elif action == "reopen":
            if session.context != "training" or session.status != "completed":
                raise ValidationError("Only completed training can be reopened.")
            session.status, session.completed_at = "draft", None
        elif action == "verify":
            if not actor.is_staff or not actor.has_perm("scoring.change_scoringsession"):
                raise PermissionDenied
            if session.context != "competition" or session.status != "completed" or session.invalidated:
                raise ValidationError("Only valid completed competition results can be verified.")
            session.verified_at, session.verified_by = timezone.now(), actor
        elif action in ("delete", "restore"):
            if data.get("confirmed") is not True:
                raise ValidationError("Confirm deletion or restoration.")
            session.deleted_at = timezone.now() if action == "delete" else None
        elif action == "invalidate":
            session.invalidated = True
        else:
            raise ValidationError("Unknown session action.")
        after = dict(status=session.status, invalidated=session.invalidated, deleted=bool(session.deleted_at), verified=bool(session.verified_at))
    # CAS also rejects competing writes on databases without SELECT FOR UPDATE support.
    updated = ScoringSession.objects.filter(pk=session.pk, version=session.version).update(version=F("version") + 1)
    if not updated:
        raise Conflict("Concurrent edit. Reload before retrying.")
    session.version += 1
    session.save(update_fields=["status", "completed_at", "invalidated", "deleted_at", "verified_at", "verified_by"])
    ScoreChangeAudit.objects.create(session=session, actor=actor, operation=action, before=before, after=after, reason=reason)
    MutationReceipt.objects.create(session=session, key=key, payload=data)
    return session


def statistics(session):
    shots = list(session.shots.all())
    by_position = {s.position: s for s in shots}
    ends = {}
    for pos, index, end, arrow, stage in slots(session):
        key = (index, end)
        row = ends.setdefault(key, dict(stage=index + 1, end=end, distance=stage["distance_m"], total=0, shots=[]))
        shot = by_position.get(pos)
        row["shots"].append(dict(position=pos, arrow=arrow, shot=shot))
        if shot:
            row["total"] += shot.points
    total = sum(s.points for s in shots)
    expected = sum(s["ends"] * s["arrows_per_end"] for s in session.snapshot["stages"])
    running = 0
    for row in ends.values():
        running += row["total"]
        row["running"] = running
    return dict(total=total, maximum=sum(s["ends"] * s["arrows_per_end"] * max(z["points"] for z in s["rules"]["zones"]) for s in session.snapshot["stages"]),
                count=len(shots), expected=expected, average=round(total / len(shots), 2) if shots else None,
                tens=sum(s.points == 10 for s in shots), xs=sum(s.is_x for s in shots), nines=sum(s.points == 9 for s in shots),
                distribution=dict(Counter(s.symbol for s in shots)), ends=list(ends.values()),
                next_position=next((p for p in range(expected) if p not in by_position), 0))


def comparison_key(session):
    stages = [{k: v for k, v in s.items() if k not in ("target_name", "rules_name")} for s in session.snapshot["stages"]]
    comparable = dict(division=session.snapshot["division"], category=session.snapshot["category"],
                      evaluator=session.snapshot["evaluator"], stages=stages)
    return hashlib.sha256(json.dumps(comparable, sort_keys=True).encode()).hexdigest()


def personal_bests(sessions):
    """Derived live so corrections/deletion/invalidation cannot leave stale PB rows."""
    bests = {}
    for session in sessions:
        if session.status != "completed" or session.deleted_at or session.invalidated:
            continue
        if session.context == "competition" and session.snapshot["verification_required"] and not session.verified_at:
            continue
        stats = statistics(session)
        if stats["count"] != stats["expected"]:
            continue
        key = (session.context, comparison_key(session))
        previous = bests.get(key)
        if previous is None or stats["total"] > previous["total"]:
            bests[key] = dict(session=session, total=stats["total"], maximum=stats["maximum"])
    return list(bests.values())


def arrow_comparisons(sessions, start_date=None, end_date=None):
    groups = defaultdict(list)
    for session in sessions:
        if session.deleted_at or session.invalidated:
            continue
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(session.athlete.timezone)
        stages = {p: s for p, _, _, _, s in slots(session)}
        for shot in session.shots.all():
            date = shot.recorded_at.astimezone(zone).date()
            if not shot.arrow_snapshot or (start_date and date < start_date) or (end_date and date > end_date):
                continue
            stage = stages[shot.position]
            conditions = json.dumps(dict(stage=stage, bow=session.equipment.get("bow")), sort_keys=True)
            key = (shot.arrow_snapshot["id"], conditions)
            groups[key].append((shot, session, stage))
    return [dict(identifier=items[0][0].arrow_snapshot["identifier"], set_id=items[0][0].arrow_snapshot["set_id"], set_name=items[0][0].arrow_snapshot["set_name"],
                 bow=items[0][1].equipment.get("bow", {}).get("name", "Unspecified bow"),
                 bow_revision=items[0][1].equipment.get("bow", {}).get("revision"),
                 distance=items[0][2]["distance_m"], target=items[0][2]["target_name"], count=len(items),
                 average=round(sum(i[0].points for i in items) / len(items), 2)) for items in groups.values()]
