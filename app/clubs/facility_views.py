from azure.core.exceptions import AzureError
from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from . import facilities as service
from .facility_forms import FORMS, CalendarForm, PhotoForm, PhotoActionForm, GroupForm
from .models import ClubFacility
from .security import admin_session_redirect


@never_cache
@require_GET
def listing(request, club_id):
    club, facilities = service.visible_facilities(request.user, club_id)
    if service.is_admin(request.user, club):
        challenge = admin_session_redirect(request)
        if challenge is not None:
            return challenge
    if request.GET.get("format") == "json":
        return JsonResponse({"facilities": facilities})
    return render(request, "clubs/facilities.html", {"club": club, "facilities": facilities})


@never_cache
@require_GET
def detail(request, facility_id):
    facility = service.facility_for(request.user, facility_id)
    if service.is_admin(request.user, facility.club):
        challenge = admin_session_redirect(request)
        if challenge is not None:
            return challenge
    payload = service.detail(request.user, facility_id)
    if request.GET.get("format") == "json":
        return JsonResponse(payload)
    return render(request, "clubs/facility.html", {"facility": payload})


@never_cache
@require_GET
def calendar(request, area_id):
    area = service.area_for(request.user, area_id)
    if service.is_admin(request.user, area.facility.club):
        challenge = admin_session_redirect(request)
        if challenge is not None:
            return challenge
    initial = {"starts_on": timezone.localtime(timezone.now(), timezone=service.ZoneInfo(area.facility.timezone)).date(), "days": 7}
    form = CalendarForm(request.GET if "starts_on" in request.GET or "days" in request.GET else initial)
    payload = None
    if form.is_valid():
        try:
            payload = service.calendar(request.user, area.pk, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
    if request.GET.get("format") == "json":
        return JsonResponse(payload if payload is not None else {"error": "Choose valid calendar dates."}, status=200 if payload else 400)
    return render(request, "clubs/facility_calendar.html", {"area_name": area.name, "form": form, "calendar": payload})


@never_cache
@require_GET
def photo(request, photo_id):
    record = service.photo_for(request.user, photo_id)
    if service.is_admin(request.user, record.facility.club):
        challenge = admin_session_redirect(request)
        if challenge is not None:
            return challenge
    try:
        content = service.photo_bytes(request.user, photo_id)
    except FileNotFoundError:
        raise Http404 from None
    except (OSError, ImproperlyConfigured, AzureError):
        return HttpResponse("Facility photo storage is temporarily unavailable.", status=503)
    response = HttpResponse(content, content_type="image/jpeg")
    response["Content-Disposition"] = 'inline; filename="facility.jpg"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@never_cache
@login_required
@require_GET
def manage(request, club_id):
    club = service.managed(request.user, club_id)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    facilities = club.facilities.prefetch_related("areas__rules", "areas__exceptions").order_by("name", "pk")
    return render(request, "clubs/facility_manage.html", {"club": club, "facilities": facilities})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def edit(request, club_id, kind="facility", object_id=None, parent_id=None):
    club = service.managed(request.user, club_id)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    if kind not in FORMS:
        raise Http404
    scope = {"club": club} if kind == "facility" else {"facility__club": club} if kind == "area" else {"area__facility__club": club}
    instance = get_object_or_404(service.MODELS[kind], pk=object_id, **scope) if object_id else None
    if not instance and kind != "facility":
        if kind == "area":
            get_object_or_404(ClubFacility, pk=parent_id, club=club, active=True)
        else:
            get_object_or_404(service.ShootingArea, pk=parent_id, facility__club=club, active=True, facility__active=True)
    form = FORMS[kind](request.POST if request.method == "POST" else None, instance=instance,
        initial={"version": instance.version if instance else None}, club=club)
    status = 200
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        version = data.pop("version", None)
        try:
            service.save(request.user, club.pk, kind, data, object_id=object_id, parent_id=parent_id, version=version)
            return redirect("clubs:facility-manage", club_id=club.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
            status = 409 if isinstance(exc, service.FacilityConflict) else 200
    return render(request, "clubs/facility_edit.html", {"club": club, "kind": kind, "form": form}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def photos(request, club_id, facility_id):
    club = service.managed(request.user, club_id)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    facility = get_object_or_404(ClubFacility, pk=facility_id, club=club, active=True)
    uploading = request.POST.get("action") == "upload"
    form = PhotoForm(request.POST if request.method == "POST" and uploading else None,
        request.FILES if uploading else None, initial={"version": facility.version}, club=club)
    action_form = PhotoActionForm(request.POST if request.method == "POST" and not uploading else None)
    current = form if uploading else action_form
    status = 200
    if request.method == "POST" and current.is_valid():
        try:
            data = current.cleaned_data
            if uploading:
                service.upload_photo(request.user, club.pk, facility.pk, data["upload"], caption=data["caption"],
                    audience=data["audience"], primary=data["primary"], version=data["version"], access_group=data["access_group"])
            else:
                # Bind both facility and club, not only a posted photo identifier.
                get_object_or_404(service.FacilityPhoto, pk=data["photo"], facility=facility)
                service.photo_action(request.user, club.pk, data["photo"], data["action"], data["version"])
            return redirect("clubs:facility-photos", club_id=club.pk, facility_id=facility.pk)
        except ValidationError as exc:
            current.add_error(None, exc)
            status = 409 if isinstance(exc, service.FacilityConflict) else 200
        except (OSError, ImproperlyConfigured, AzureError):
            current.add_error(None, "Private facility photo storage is unavailable. Try again later.")
    return render(request, "clubs/facility_photos.html", {"club": club, "facility": facility, "form": form,
        "action_form": action_form, "photos": facility.photos.filter(active=True).order_by("-primary", "created_at")}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def group(request, club_id, group_id=None):
    club = service.managed(request.user, club_id)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    existing = get_object_or_404(service.FacilityAccessGroup, club=club, pk=group_id) if group_id else None
    initial = {"name": existing.name, "active": existing.active, "version": existing.version,
        "members": list(existing.members.filter(active=True).values_list("pk", flat=True))} if existing else {}
    form = GroupForm(request.POST if request.method == "POST" else None, club=club, initial=initial)
    status = 200
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            service.save_group(request.user, club.pk, name=data["name"], member_ids=list(data["members"].values_list("pk", flat=True)),
                active=data["active"], group_id=group_id, version=data["version"])
            return redirect("clubs:facility-manage", club_id=club.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
            status = 409 if isinstance(exc, service.FacilityConflict) else 200
    return render(request, "clubs/facility_edit.html", {"club": club, "kind": "facility access group", "form": form}, status=status)
