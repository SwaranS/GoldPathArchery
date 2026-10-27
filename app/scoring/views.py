import json
from datetime import date
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.models import AthleteProfile
from accounts.permissions import accessible_athletes, can
from . import services
from .forms import ArrowForm, EquipmentForm, StartForm
from .models import Equipment, PhysicalArrow, ScoringSession


def errors(view):
    @never_cache
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except (PermissionDenied, ObjectDoesNotExist):
            raise Http404("Unavailable.")
        except services.Conflict as error:
            return JsonResponse({"error": str(error)}, status=409)
        except ValidationError as error:
            return JsonResponse({"error": "; ".join(error.messages)}, status=400)
        except (ValueError, TypeError, KeyError, OverflowError, IntegrityError):
            return JsonResponse({"error": "Invalid request. Reload and review your entries."}, status=400)
    return wrapped


def athlete_for(request, pk, write=False):
    athlete = get_object_or_404(accessible_athletes(request.user), pk=pk)
    services.authorize(request.user, athlete, write)
    return athlete


@login_required
@require_http_methods(["GET", "POST"])
@errors
def start(request, athlete_id):
    athlete = athlete_for(request, athlete_id, True)
    form = StartForm(request.POST or None, athlete=athlete)
    if request.method == "POST" and form.is_valid():
        try:
            session = services.start(request.user, athlete, form.service_data())
            return redirect("scoring-session", session_id=session.pk)
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, "scoring/start.html", dict(athlete=athlete, form=form))


@login_required
@require_GET
@errors
def history(request, athlete_id):
    athlete = athlete_for(request, athlete_id)
    sessions = list(ScoringSession.objects.filter(athlete=athlete).select_related("athlete").prefetch_related("shots").order_by("-started_at"))
    start_date = date.fromisoformat(request.GET["from"]) if request.GET.get("from") else None
    end_date = date.fromisoformat(request.GET["to"]) if request.GET.get("to") else None
    if start_date and end_date and start_date > end_date:
        raise ValidationError("Start date must precede end date.")
    rows = [dict(session=s, stats=services.statistics(s), key=services.comparison_key(s)[:12]) for s in sessions]
    return render(request, "scoring/history.html", dict(athlete=athlete, rows=rows,
        bests=services.personal_bests(sessions), comparisons=services.arrow_comparisons(sessions, start_date, end_date),
        writable=can(request.user, athlete, "log_scores")))


@login_required
@require_GET
@errors
def session(request, session_id):
    obj = get_object_or_404(ScoringSession.objects.select_related("athlete"), pk=session_id)
    services.authorize(request.user, obj.athlete)
    stats = services.statistics(obj)
    arrows = PhysicalArrow.objects.filter(arrow_set_id=obj.equipment.get("arrow_set", {}).get("id"),
        arrow_set__athlete=obj.athlete).filter(
            Q(arrow_set__active=True, active=True) | Q(pk__in=obj.shots.values("arrow_id")))
    shot_data = [{**services.shot_state(s), "arrow": s.arrow_id} for s in obj.shots.all()]
    payload = dict(version=obj.version, stages=obj.snapshot["stages"], shots=shot_data, next_position=stats["next_position"],
                   slots=[dict(position=p, stage=i, end=e, arrow=a) for p, i, e, a, _ in services.slots(obj)])
    return render(request, "scoring/session.html", dict(session=obj, stats=stats, payload=payload, arrows=arrows,
        writable=can(request.user, obj.athlete, "log_scores")))


@login_required
@require_POST
@errors
def save(request, session_id):
    data = json.loads(request.body)
    obj = services.mutate(request.user, session_id, data)
    stats = services.statistics(obj)
    return JsonResponse(dict(version=obj.version, status=obj.status, total=stats["total"], count=stats["count"],
                             average=stats["average"], tens=stats["tens"], xs=stats["xs"], nines=stats["nines"]))


@login_required
@require_http_methods(["GET", "POST"])
@errors
@transaction.atomic
def equipment(request, athlete_id):
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    services.authorize(request.user, athlete, True)
    form = EquipmentForm(request.POST if request.POST.get("action") == "equipment" else None)
    arrow_form = ArrowForm(request.POST if request.POST.get("action") == "arrow" else None, athlete=athlete)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "equipment" and form.is_valid():
            item = form.save(commit=False)
            item.athlete = athlete
            item.save()
            return redirect("scoring-equipment", athlete_id=athlete.pk)
        if action == "arrow" and arrow_form.is_valid():
            arrow_form.save()
            return redirect("scoring-equipment", athlete_id=athlete.pk)
        if action in ("archive", "restore"):
            item = get_object_or_404(Equipment, pk=request.POST["item"], athlete=athlete)
            item.active = action == "restore"
            item.save(update_fields=["active"])
            return redirect("scoring-equipment", athlete_id=athlete.pk)
    return render(request, "scoring/equipment.html", dict(athlete=athlete, form=form, arrow_form=arrow_form,
        items=Equipment.objects.filter(athlete=athlete).prefetch_related("arrows")))
