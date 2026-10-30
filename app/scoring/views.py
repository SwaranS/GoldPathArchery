import json
from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.models import AthleteProfile
from accounts.permissions import accessible_athletes, can
from . import services, equipment_services, advanced_equipment
from .forms import ArrowForm, EquipmentForm, SightMarkForm, StartForm
from .models import PhysicalArrow, ScoringSession


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
    arrows = PhysicalArrow.objects.select_related("arrow_set").filter(arrow_set_id=obj.equipment.get("arrow_set", {}).get("id"),
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
def equipment(request, athlete_id):
    context = equipment_services.workspace(request.user, athlete_id, bow=request.GET.get("bow"))
    if request.method == "POST" and not context["writable"]:
        raise PermissionDenied
    edit_id = request.POST.get("item") if request.POST.get("action") == "revise" else request.GET.get("edit")
    editing = next((item for item in context["items"] if str(item.pk) == str(edit_id)), None)
    if (edit_id and editing is None) or (request.POST.get("action") == "revise" and not edit_id):
        raise Http404("Unavailable.")
    initial = {}
    if editing:
        initial = {field: getattr(editing.current, field) for field in equipment_services.SPEC_FIELDS} if editing.current else dict(
            name=editing.name, division=editing.division, details=editing.details)
        initial.update(kind=editing.kind, expected_revision=editing.current.pk if editing.current else None)
    action = request.POST.get("action")
    form = EquipmentForm(request.POST if action in ("equipment", "revise") else None, initial=initial)
    arrow_form = ArrowForm(request.POST if action == "arrow" else None, athlete=athlete_id)
    mark_form = SightMarkForm(request.POST if action == "mark" else None, athlete=athlete_id)
    if request.method == "POST":
        active_form = {"equipment": form, "revise": form, "arrow": arrow_form, "mark": mark_form}.get(action)
        try:
            if active_form and active_form.is_valid():
                if action in ("equipment", "revise"):
                    equipment_services.save_equipment(request.user, athlete_id, form.service_data(),
                        item_id=editing.pk if editing else None,
                        expected_revision=form.cleaned_data.get("expected_revision"))
                elif action == "arrow":
                    equipment_services.save_arrow(request.user, athlete_id, dict(
                        arrow_set=arrow_form.cleaned_data["arrow_set"].pk,
                        identifier=arrow_form.cleaned_data["identifier"], notes=arrow_form.cleaned_data["notes"]))
                else:
                    equipment_services.save_mark(request.user, athlete_id, {
                        key: value.pk if hasattr(value, "pk") else value for key, value in mark_form.cleaned_data.items()})
                messages.success(request, "Equipment record saved.")
                return redirect("scoring-equipment", athlete_id=athlete_id)
            if action in ("archive", "restore"):
                equipment_services.set_active(request.user, athlete_id, request.POST.get("entity", "equipment"),
                    request.POST["item"], action == "restore")
                messages.success(request, "Record archived." if action == "archive" else "Record restored.")
                return redirect("scoring-equipment", athlete_id=athlete_id)
            if active_form is None:
                raise ValidationError("Unknown equipment action.")
        except ValidationError as error:
            if active_form:
                active_form.add_error(None, "; ".join(error.messages))
            else:
                context["action_error"] = "; ".join(error.messages)
    from .forms import ComponentForm
    from .models import EquipmentComponent
    from .component_specs import NUMBERS, TEXT, STATUSES
    athlete = AthleteProfile.objects.get(pk=athlete_id)
    components = list(advanced_equipment.component_workspace(request.user, athlete))
    component_edit = next((c for c in components if str(c.pk) == str(request.GET.get("component_edit", request.POST.get("component_id", "")))), None)
    component_initial = {}
    if component_edit:
        rev = component_edit.revisions.first()
        component_initial = {k: getattr(rev, k) for k in advanced_equipment.COMPONENT_FIELDS}
        component_initial.update(category=component_edit.category, expected_revision=rev.pk)
    component_form = ComponentForm(request.POST if action == "component" else None, initial=component_initial)
    if request.method == "POST" and action in ("component", "component_status"):
        try:
            if action == "component" and component_form.is_valid():
                data = component_form.cleaned_data
                advanced_equipment.save_component(request.user, athlete_id, data["category"],
                    {k: data[k] for k in advanced_equipment.COMPONENT_FIELDS},
                    component_id=request.POST.get("component_id") or None, expected_revision=data["expected_revision"])
                return redirect("athlete-equipment", athlete_id=athlete_id)
            elif action == "component_status":
                advanced_equipment.set_component_status(request.user, athlete_id, request.POST["component_id"], request.POST["status"], request.POST.get("reason", ""))
                return redirect("athlete-equipment", athlete_id=athlete_id)
        except ValidationError as error:
            component_form.add_error(None, "; ".join(error.messages))
    context.pop("action_error", None) if action in ("component", "component_status") else None
    context.update(components=components, component_form=component_form, component_edit=component_edit,
        component_statuses=[(v, v.replace("_", " ").title()) for v in STATUSES],
        component_schema=[(k, NUMBERS[k] + " " + TEXT[k]) for k in NUMBERS])
    from .forms import ConfigurationForm
    from .models import BowConfiguration, AthleteEquipmentDefaults
    configs = list(BowConfiguration.objects.filter(owner=athlete).prefetch_related("revisions__members__component_revision"))
    config_edit = next((c for c in configs if str(c.pk) == str(request.GET.get("configuration_edit", request.POST.get("configuration_id", "")))), None)
    config_initial = {}
    if config_edit:
        rev = config_edit.revisions.first()
        config_initial = dict(name=rev.name, division=rev.division, components=list(rev.components.all()),
            preferred_arrows=rev.preferred_arrows_id, expected_revision=rev.pk)
    configuration_form = ConfigurationForm(request.POST if action == "configuration" else None, athlete=athlete, actor=request.user, initial=config_initial)
    if request.method == "POST" and action in ("configuration", "configuration_default", "configuration_status"):
        try:
            if action == "configuration" and configuration_form.is_valid():
                d = configuration_form.cleaned_data
                advanced_equipment.save_configuration(request.user, athlete_id, d["name"], d["division"],
                    [r.pk for r in d["components"]], configuration_id=request.POST.get("configuration_id") or None,
                    expected_revision=d["expected_revision"], preferred_arrows_id=d["preferred_arrows"].pk if d["preferred_arrows"] else None,
                    acknowledged=d["acknowledged"], reason=d["reason"])
                return redirect("athlete-equipment", athlete_id=athlete_id)
            elif action == "configuration_default":
                advanced_equipment.set_default(request.user, athlete_id, request.POST.get("configuration_id") or None)
                return redirect("athlete-equipment", athlete_id=athlete_id)
            elif action == "configuration_status":
                advanced_equipment.archive_configuration(request.user, athlete_id, request.POST["configuration_id"], request.POST.get("active") == "true")
                return redirect("athlete-equipment", athlete_id=athlete_id)
        except ValidationError as error:
            configuration_form.add_error(None, "; ".join(error.messages))
        context.pop("action_error", None)
    for c in configs:
        c.current = c.revisions.first()
        c.available = advanced_equipment.configuration_available(c.current, athlete)
    context.update(configurations=configs, configuration_form=configuration_form, configuration_edit=config_edit,
        equipment_default=AthleteEquipmentDefaults.objects.filter(athlete=athlete).first())
    from .models import EquipmentShare, EquipmentTransfer
    from django.db.models import Q
    if request.method == "POST" and action in ("share_invite", "transfer_invite", "invitation_decide"):
        try:
            if action == "invitation_decide":
                advanced_equipment.decide_invitation(request.user, athlete_id, request.POST["invitation_id"], request.POST["decision"], transfer=request.POST.get("transfer") == "true")
            else:
                advanced_equipment.invite_component(request.user, athlete_id, request.POST["component_id"], request.POST["recipient_id"], transfer=action == "transfer_invite", permit_photos=request.POST.get("permit_photos") == "on")
            return redirect("athlete-equipment", athlete_id=athlete_id)
        except ValidationError as error:
            context["action_error"] = "; ".join(error.messages)
    context.update(shared_components=advanced_equipment.shared_components(request.user, athlete),
        shares=EquipmentShare.objects.filter(Q(owner=athlete) | Q(recipient=athlete)).order_by("-pk"),
        transfers=EquipmentTransfer.objects.filter(Q(sender=athlete) | Q(recipient=athlete)).order_by("-pk"))
    from .forms import MaintenanceForm, PurchaseForm
    from .models import EquipmentPhoto, EquipmentMaintenanceEntry, EquipmentPurchaseRecord
    maintenance_form = MaintenanceForm(request.POST if action == "maintenance" else None, athlete=athlete)
    purchase_form = PurchaseForm(request.POST if action == "purchase" else None, athlete=athlete)
    if request.method == "POST" and action in ("maintenance", "purchase", "photo", "photo_remove"):
        context.pop("action_error", None)
        try:
            if action in ("maintenance", "purchase"):
                active_form = maintenance_form if action == "maintenance" else purchase_form
                if active_form.is_valid():
                    d = active_form.cleaned_data.copy(); component_id = d.pop("component").pk
                    for key in ("replacement", "receipt", "correction_of"):
                        if key in d:
                            value = d.pop(key)
                            if value:
                                d[key + "_id"] = value.pk if hasattr(value, "pk") else value
                    fn = advanced_equipment.add_maintenance if action == "maintenance" else advanced_equipment.add_purchase
                    fn(request.user, athlete_id, component_id, d)
                    return redirect("athlete-equipment", athlete_id=athlete_id)
            elif action == "photo":
                if not request.FILES.get("image"):
                    raise ValidationError("Choose an image to upload.")
                advanced_equipment.upload_photo(request.user, athlete_id, request.FILES["image"],
                    component_id=request.POST.get("component_id") or None, configuration_id=request.POST.get("configuration_id") or None,
                    primary=request.POST.get("primary") == "on", receipt=request.POST.get("receipt") == "on")
                return redirect("athlete-equipment", athlete_id=athlete_id)
            else:
                advanced_equipment.remove_photo(request.user, athlete_id, request.POST["photo_id"])
                return redirect("athlete-equipment", athlete_id=athlete_id)
        except ValidationError as error:
            context["action_error"] = "; ".join(error.messages)
    private_access = False
    try:
        advanced_equipment.private_authorize(request.user, athlete); private_access = True
    except PermissionDenied:
        pass
    context.update(maintenance_form=maintenance_form, purchase_form=purchase_form, private_purchase_access=private_access,
        maintenance_entries=EquipmentMaintenanceEntry.objects.filter(owner=athlete).select_related("component").order_by("-event_date", "-pk")[:100],
        purchase_entries=EquipmentPurchaseRecord.objects.filter(owner=athlete).order_by("-pk")[:100] if private_access else [],
        photos=EquipmentPhoto.objects.filter(Q(component__owner=athlete) | Q(configuration__owner=athlete), active=True, receipt=False),
        receipts=EquipmentPhoto.objects.filter(owner=athlete, active=True, receipt=True) if private_access else [])
    context.update(form=form, arrow_form=arrow_form, mark_form=mark_form, editing=editing)
    return render(request, "scoring/equipment.html", context)


@login_required
@require_GET
@errors
def equipment_media(request, photo_id):
    from django.http import HttpResponse
    content = advanced_equipment.photo_bytes(request.user, photo_id, request.GET.get("athlete"))
    response = HttpResponse(content, content_type="image/jpeg")
    response["Content-Disposition"] = 'inline; filename="equipment.jpg"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
