"""Club-scoped venue administration and privacy-safe availability projection."""
from datetime import date, datetime, time, timedelta, timezone as utc
from decimal import Decimal, InvalidOperation
import uuid
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, F
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.models import AthleteProfile
from accounts.permissions import eligible_actor, can, accessible_athletes
from . import services, memberships
from .models import (Club, ClubMembership, ClubFacility, ShootingArea,
    FacilityAvailabilityRule, FacilityAvailabilityException, FacilityPhoto, FacilityPhotoUpload, FacilityAccessGroup)
from .storage import PrivateEvidenceStore, normalize_upload

AUDIENCES = {"public", "members", "coaches", "admins", "group"}
MODELS = {"facility": ClubFacility, "area": ShootingArea,
    "rule": FacilityAvailabilityRule, "exception": FacilityAvailabilityException}
FIELDS = {
    "facility": {"name", "description", "address", "latitude", "longitude", "timezone", "audience", "location_audience", "active"},
    "area": {"name", "kind", "disciplines", "distances_m", "lane_capacity", "target_capacity", "audience", "active"},
    "rule": {"weekday", "starts_on", "ends_on", "start_time", "end_time", "priority", "audience", "active"},
    "exception": {"starts_on", "ends_on", "kind", "replacement_slots", "reason", "priority", "audience", "active"},
}
for _fields in FIELDS.values():
    _fields.add("access_group")
FIELDS["facility"].add("location_group")


class FacilityConflict(ValidationError):
    pass


def enabled():
    services.enabled()
    if not getattr(settings, "CLUB_FACILITIES_ENABLED", False):
        raise Http404


def check_version(obj, expected):
    if type(expected) is not int or expected != obj.version:
        raise FacilityConflict("This record changed. Reload the current page before saving.")


def is_admin(actor, club):
    return services.can_manage(actor, club)


def is_member(actor, club):
    if not eligible_actor(actor):
        return False
    if ClubMembership.objects.filter(club=club, user=actor, active=True).exists():
        return True
    # Guardian representation never implies the guardian has joined personally.
    ids = [a.pk for a in accessible_athletes(actor) if can(actor, a, "manage_grants")]
    return ClubMembership.objects.filter(club=club, athlete_id__in=ids, active=True).exists()


def club_visible(actor, club):
    return memberships.live_club(club) and (club.visibility == "public" or is_member(actor, club))


def audience_allowed(actor, club, audience, group=None):
    if audience not in AUDIENCES or (audience == "group") != bool(group) or (group and group.club_id != club.pk):
        return False
    if not club_visible(actor, club):
        return False
    if is_admin(actor, club):
        return True
    if audience == "public":
        return True
    if audience == "members":
        return is_member(actor, club)
    if audience == "coaches":
        return memberships.has_role(actor, club, {"coach"})
    if audience == "group" and group and group.active and group.club_id == club.pk and eligible_actor(actor):
        ids = [a.pk for a in accessible_athletes(actor) if can(actor, a, "manage_grants")]
        return group.members.filter(active=True, club=club).filter(Q(user=actor) | Q(athlete_id__in=ids)).exists()
    return False


def managed(actor, club_id, *, lock=False):
    enabled()
    qs = Club.objects.select_for_update() if lock else Club.objects
    club = get_object_or_404(qs, pk=club_id)
    if not is_admin(actor, club):
        raise Http404
    return club


def facility_for(actor, facility_id):
    enabled()
    facility = get_object_or_404(ClubFacility.objects.select_related("club"), pk=facility_id, active=True)
    if not audience_allowed(actor, facility.club, facility.audience, facility.access_group):
        raise Http404
    return facility


def area_for(actor, area_id):
    area = get_object_or_404(ShootingArea.objects.select_related("facility__club"), pk=area_id, active=True)
    facility_for(actor, area.facility_id)
    if not audience_allowed(actor, area.facility.club, area.audience, area.access_group):
        raise Http404
    return area


def visible_facilities(actor, club_id):
    enabled()
    club = get_object_or_404(Club, pk=club_id)
    if not club_visible(actor, club):
        raise Http404
    return club, [facility_payload(actor, f) for f in club.facilities.filter(active=True).order_by("name", "pk")
        if audience_allowed(actor, club, f.audience, f.access_group)]


def facility_payload(actor, facility):
    # No raw model is handed to public templates or JSON serializers.
    result = {"id": facility.pk, "name": facility.name, "description": facility.description, "timezone": facility.timezone}
    if audience_allowed(actor, facility.club, facility.location_audience, facility.location_group):
        result.update(address=facility.address, latitude=facility.latitude, longitude=facility.longitude)
    return result


def detail(actor, facility_id):
    facility = facility_for(actor, facility_id)
    payload = facility_payload(actor, facility)
    payload["areas"] = [{"id": a.pk, "name": a.name, "kind": a.kind,
        "disciplines": a.disciplines, "distances_m": a.distances_m,
        "lane_capacity": a.lane_capacity, "target_capacity": a.target_capacity}
        for a in facility.areas.filter(active=True).order_by("name", "pk")
        if audience_allowed(actor, facility.club, a.audience, a.access_group)]
    payload["photos"] = [{"id": p.pk, "caption": p.caption, "primary": p.primary}
        for p in facility.photos.filter(active=True).order_by("-primary", "created_at", "pk")
        if audience_allowed(actor, facility.club, p.audience, p.access_group)]
    return payload


def slots(value):
    if not isinstance(value, list) or not value or len(value) > 20:
        raise ValidationError("Replacement hours require 1–20 time windows.")
    result = []
    try:
        for entry in value:
            if not isinstance(entry, dict) or set(entry) != {"start", "end"}:
                raise ValueError
            start, end = time.fromisoformat(entry["start"]), time.fromisoformat(entry["end"])
            if start.tzinfo or end.tzinfo or start >= end:
                raise ValueError
            result.append((start, end))
        result.sort()
        if any(a[1] > b[0] for a, b in zip(result, result[1:])):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValidationError('Use non-overlapping same-day windows: [{"start":"09:00","end":"12:00"}].') from None
    return result


def dates_overlap(a_start, a_end, b_start, b_end):
    return a_start <= (b_end or date.max) and b_start <= (a_end or date.max)


def validate(obj, kind):
    if kind == "exception" and obj.kind == "closed" and obj.replacement_slots is None:
        obj.replacement_slots = []
    obj.full_clean()
    club_id = obj.club_id if kind == "facility" else obj.facility.club_id if kind == "area" else obj.area.facility.club_id
    validate_group(obj.audience, obj.access_group, club_id)
    if kind == "facility":
        validate_group(obj.location_audience, obj.location_group, club_id)
    if kind == "facility":
        if (obj.latitude is None) != (obj.longitude is None):
            raise ValidationError("Provide both coordinates or neither.")
        if not obj.name.strip():
            raise ValidationError("Enter a facility name.")
    if kind == "area":
        if not isinstance(obj.disciplines, list) or not obj.disciplines or any(not isinstance(d, str) or d not in {"recurve", "compound", "barebow"} for d in obj.disciplines) or len(set(obj.disciplines)) != len(obj.disciplines):
            raise ValidationError("Choose valid, distinct disciplines.")
        if not isinstance(obj.distances_m, list) or not obj.distances_m or len(obj.distances_m) > 100:
            raise ValidationError("Provide 1–100 distances in metres.")
        try:
            if any(isinstance(d, bool) or not Decimal(str(d)).is_finite() or not 0 < Decimal(str(d)) <= 1000 for d in obj.distances_m):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValidationError("Distances must be positive finite metres, up to 1000.") from None
        if not 1 <= obj.lane_capacity <= 1000 or not 1 <= obj.target_capacity <= 1000:
            raise ValidationError("Lane and target capacities must be 1–1000.")
    if kind == "rule" and obj.active:
        for other in obj.area.rules.filter(active=True, weekday=obj.weekday, priority=obj.priority).exclude(pk=obj.pk):
            if dates_overlap(obj.starts_on, obj.ends_on, other.starts_on, other.ends_on) and obj.start_time < other.end_time and other.start_time < obj.end_time:
                raise ValidationError("Rules at the same priority cannot overlap. Use a higher seasonal priority or separate hours.")
    if kind == "exception":
        if obj.kind == "replace":
            slots(obj.replacement_slots)
        elif obj.replacement_slots:
            raise ValidationError("A closure cannot have replacement hours.")
        if not obj.reason.strip():
            raise ValidationError("Record a reason for this exception.")
        if obj.active:
            for other in obj.area.exceptions.filter(active=True, priority=obj.priority).exclude(pk=obj.pk):
                if dates_overlap(obj.starts_on, obj.ends_on, other.starts_on, other.ends_on):
                    raise ValidationError("Exceptions at the same priority cannot overlap dates.")


@transaction.atomic
def save(actor, club_id, kind, data, *, object_id=None, parent_id=None, version=None):
    club = managed(actor, club_id, lock=True)
    if kind not in MODELS or set(data) - FIELDS[kind]:
        raise ValidationError("Choose permitted facility fields.")
    model = MODELS[kind]
    scope = {"club": club} if kind == "facility" else {"facility__club": club} if kind == "area" else {"area__facility__club": club}
    if object_id:
        obj = get_object_or_404(model.objects.select_for_update(), pk=object_id, **scope)
        check_version(obj, version)
        obj.version += 1
    else:
        if kind == "facility":
            obj = model(club=club)
        elif kind == "area":
            obj = model(facility=get_object_or_404(ClubFacility, pk=parent_id, club=club, active=True))
        else:
            obj = model(area=get_object_or_404(ShootingArea, pk=parent_id, facility__club=club,
                facility__active=True, active=True))
    for key, value in data.items():
        setattr(obj, key, value)
    validate(obj, kind)
    obj.save()
    services.audit(actor, None, "facility." + kind + (".updated" if object_id else ".created"), obj.pk, club=club)
    return obj


def wall_time(day, value, zone):
    """Reject gaps and folds rather than choosing a hidden DST interpretation."""
    naive = datetime.combine(day, value)
    candidates = []
    for fold in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold)
        if local.astimezone(utc.utc).astimezone(zone).replace(tzinfo=None) == naive:
            candidates.append(local)
    if not candidates or len({c.utcoffset() for c in candidates}) != 1:
        raise ValidationError("These local hours cross an ambiguous or nonexistent clock time. Confirm replacement hours with the club.")
    return candidates[0]


def event_conflicts(*, area, starts_at, ends_at, actor, provider=None):
    """M6 provider contract. Provider must return only actor-authorized summaries.

    None explicitly means event checks are not connected, rather than no conflicts.
    A future provider receives the scoped area and aware UTC interval.
    """
    if provider is None:
        return None
    return provider(area=area, starts_at=starts_at, ends_at=ends_at, actor=actor)


def calendar(actor, area_id, starts_on, days=7, *, event_provider=None):
    area = area_for(actor, area_id)
    if not isinstance(starts_on, date) or isinstance(starts_on, datetime) or type(days) is not int or not 1 <= days <= 31:
        raise ValidationError("Choose a start date and 1–31 days.")
    if starts_on > date.max - timedelta(days=days - 1):
        raise ValidationError("The requested date range exceeds the calendar.")
    club, zone = area.facility.club, ZoneInfo(area.facility.timezone)
    rules = list(area.rules.filter(active=True))
    exceptions = list(area.exceptions.filter(active=True))
    result = []
    for offset in range(days):
        day = starts_on + timedelta(days=offset)
        row = {"date": day, "slots": [], "notice": ""}
        overrides = [e for e in exceptions if e.starts_on <= day <= e.ends_on]
        windows = []
        if overrides:
            exception = max(overrides, key=lambda e: (e.priority, e.created_at, str(e.pk)))
            if audience_allowed(actor, club, exception.audience, exception.access_group):
                row["notice"] = exception.reason
                if exception.kind == "replace":
                    windows = slots(exception.replacement_slots)
            # A hidden closure/replacement must still suppress ordinary public hours.
        else:
            candidates = [r for r in rules if r.weekday == day.weekday() and r.starts_on <= day and (r.ends_on is None or day <= r.ends_on)]
            if candidates:
                priority = max(r.priority for r in candidates)
                windows = [(r.start_time, r.end_time) for r in candidates if r.priority == priority and audience_allowed(actor, club, r.audience, r.access_group)]
        for start, end in sorted(windows):
            try:
                local_start, local_end = wall_time(day, start, zone), wall_time(day, end, zone)
            except ValidationError:
                row["notice"] = "Availability needs confirmation because of a clock change."
                continue
            utc_start, utc_end = local_start.astimezone(utc.utc), local_end.astimezone(utc.utc)
            if utc_end <= utc_start:
                row["notice"] = "Availability needs confirmation because of a clock change."
                continue
            row["slots"].append({"start": local_start.isoformat(), "end": local_end.isoformat(),
                "start_label": local_start.strftime("%H:%M (UTC%z)"), "end_label": local_end.strftime("%H:%M (UTC%z)"),
                "start_utc": utc_start.isoformat(), "end_utc": utc_end.isoformat(),
                "conflicts": event_conflicts(area=area, starts_at=utc_start, ends_at=utc_end, actor=actor, provider=event_provider)})
        result.append(row)
    return {"area": area.name, "timezone": area.facility.timezone, "days": result,
        "event_checks_connected": event_provider is not None}


class FacilityPhotoStore(PrivateEvidenceStore):
    def __init__(self):
        super().__init__(prefix="CLUB_FACILITY_PHOTO")


def upload_photo(actor, club_id, facility_id, upload, *, caption, audience, primary, version, access_group=None):
    enabled()
    if transaction.get_connection().in_atomic_block:
        raise ValidationError("Photo upload requires a durable upload intent outside an outer transaction.")
    managed(actor, club_id)
    content = normalize_upload(upload)
    store = FacilityPhotoStore()
    key = uuid.uuid4().hex + ".jpg"
    intent = FacilityPhotoUpload.objects.create(storage_key=key)
    try:
        store.put(content, key=key)
        with transaction.atomic():
            club = managed(actor, club_id, lock=True)
            facility = get_object_or_404(ClubFacility.objects.select_for_update(), pk=facility_id, club=club, active=True)
            check_version(facility, version)
            if facility.photos.filter(active=True).count() >= 20:
                raise ValidationError("A facility may have at most 20 active photos.")
            validate_group(audience, access_group, club.pk)
            photo = FacilityPhoto(facility=facility, caption=caption, audience=audience, access_group=access_group, primary=primary, storage_key=key)
            if primary:
                facility.photos.filter(primary=True, active=True).update(primary=False, version=F("version") + 1)
            photo.full_clean()
            photo.save()
            facility.version += 1
            facility.save(update_fields=["version"])
            intent.delete()
            services.audit(actor, None, "facility.photo.created", photo.pk, club=club)
            return photo
    except Exception:
        try:
            store.delete(key)
            intent.delete()
        except Exception:
            pass  # The separate cleanup command retries this durable intent.
        raise


@transaction.atomic
def photo_action(actor, club_id, photo_id, action, version):
    club = managed(actor, club_id, lock=True)
    photo = get_object_or_404(FacilityPhoto.objects.select_for_update(), pk=photo_id, facility__club=club, active=True)
    check_version(photo, version)
    if action == "primary":
        photo.facility.photos.filter(active=True, primary=True).exclude(pk=photo.pk).update(primary=False, version=F("version") + 1)
        photo.primary = True
    elif action == "archive":
        photo.active, photo.primary = False, False
    else:
        raise ValidationError("Choose a permitted photo action.")
    photo.version += 1
    photo.save()
    services.audit(actor, None, "facility.photo." + action, photo.pk, club=club)


def photo_for(actor, photo_id):
    enabled()
    photo = get_object_or_404(FacilityPhoto.objects.select_related("facility__club"), pk=photo_id, active=True, facility__active=True)
    facility_for(actor, photo.facility_id)
    if not audience_allowed(actor, photo.facility.club, photo.audience, photo.access_group):
        raise Http404
    return photo


def photo_bytes(actor, photo_id):
    return FacilityPhotoStore().get(photo_for(actor, photo_id).storage_key)


def cleanup_uploads(*, apply=False, limit=100):
    if not 1 <= limit <= 1000:
        raise ValidationError("Choose a cleanup limit from 1 to 1000.")
    pending = FacilityPhotoUpload.objects.filter(created_at__lt=timezone.now()-timedelta(hours=24)).order_by("created_at")[:limit]
    count = 0
    store = FacilityPhotoStore() if apply else None
    for intent in pending:
        # Never delete any linked photo, including an archived historical image.
        if FacilityPhoto.objects.filter(storage_key=intent.storage_key).exists():
            if apply:
                intent.delete()
            continue
        if apply:
            store.delete(intent.storage_key)
            intent.delete()
        count += 1
    return count


def validate_group(audience, group, club_id):
    if (audience == "group") != bool(group) or (group and group.club_id != club_id):
        raise ValidationError("Select a facility access group from this club only when using the group audience.")


@transaction.atomic
def save_group(actor, club_id, *, name, member_ids, active=True, group_id=None, version=None):
    club = managed(actor, club_id, lock=True)
    group = get_object_or_404(FacilityAccessGroup.objects.select_for_update(), pk=group_id, club=club) if group_id else FacilityAccessGroup(club=club)
    if group_id:
        check_version(group, version)
        group.version += 1
    ids = set(member_ids)
    members = ClubMembership.objects.filter(club=club, active=True, pk__in=ids)
    if members.count() != len(ids):
        raise ValidationError("Access groups may contain only active memberships in this club.")
    group.name, group.active = name.strip(), active
    group.full_clean()
    group.save()
    group.members.set(members)
    services.audit(actor, None, "facility.group.updated" if group_id else "facility.group.created", group.pk, club=club)
    return group
