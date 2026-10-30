"""Equipment boundary: stable identities, append-only specifications and live grants."""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef

from accounts.models import AthleteProfile
from accounts.permissions import can, training_fields
from .models import Equipment, EquipmentRevision, PhysicalArrow, SightMark


SPEC_FIELDS = (
    "name", "division", "details", "brand", "model", "handedness", "draw_weight",
    "draw_weight_unit", "draw_length", "draw_length_unit", "spine", "length", "length_unit",
    "point_weight", "point_weight_unit", "shaft_diameter", "shaft_diameter_unit",
)


def authorize(actor, athlete, write=False):
    if not can(actor, athlete, "edit_profile" if write else "view"):
        raise PermissionDenied


def locked_athlete(actor, athlete_id):
    athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
    authorize(actor, athlete, True)
    return athlete


def current_revision(item):
    return item.revisions.order_by("-number").first()


def revision_snapshot(item):
    revision = current_revision(item)
    # Compatibility for equipment created by older integrations after the migration.
    if revision is None:
        return dict(id=item.pk, name=item.name, division=item.division, details=item.details)
    result = {field: getattr(revision, field) for field in SPEC_FIELDS}
    result = {key: str(value) if isinstance(value, Decimal) else value for key, value in result.items()}
    return dict(id=item.pk, revision_id=revision.pk, revision=revision.number, **result)


@transaction.atomic
def save_equipment(actor, athlete_id, data, *, item_id=None, expected_revision=None):
    athlete = locked_athlete(actor, athlete_id)
    if set(data) - {"kind", *SPEC_FIELDS}:
        raise ValidationError("Unsupported equipment fields.")
    if item_id:
        item = Equipment.objects.get(pk=item_id, athlete=athlete)
        if not item.active:
            raise ValidationError("Restore equipment before revising it.")
        previous = current_revision(item)
        if str(previous.pk if previous else "") != str(expected_revision or ""):
            raise ValidationError("This equipment changed. Reload before saving a revision.")
        if data.get("kind", item.kind) != item.kind:
            raise ValidationError("An equipment identity cannot change type.")
    else:
        item = Equipment(athlete=athlete, kind=data.get("kind", ""))
        previous = None
    # A revision is a complete specification, never a partial overwrite.
    revision = EquipmentRevision(equipment=item, number=(previous.number + 1 if previous else 1),
                                 **{field: data[field] for field in SPEC_FIELDS if field in data})
    item.name, item.division, item.details = revision.name, revision.division, revision.details
    item.full_clean()
    item.save()
    revision.equipment = item
    revision.full_clean()
    if previous and all(getattr(previous, field) == getattr(revision, field) for field in SPEC_FIELDS):
        return item
    revision.save()
    return item


@transaction.atomic
def save_arrow(actor, athlete_id, data):
    athlete = locked_athlete(actor, athlete_id)
    item = Equipment.objects.get(pk=data["arrow_set"], athlete=athlete, kind="arrow_set", active=True)
    arrow = PhysicalArrow(arrow_set=item, identifier=data["identifier"], notes=data.get("notes", ""))
    arrow.full_clean()
    arrow.save()
    return arrow


@transaction.atomic
def save_mark(actor, athlete_id, data):
    athlete = locked_athlete(actor, athlete_id)
    revisions = {}
    for field, kind in (("bow_revision", "bow"), ("arrow_revision", "arrow_set")):
        if data.get(field):
            revision = EquipmentRevision.objects.select_related("equipment").get(
                pk=data[field], equipment__athlete=athlete, equipment__kind=kind, equipment__active=True)
            if revision.pk != current_revision(revision.equipment).pk:
                raise ValidationError("The setup changed. Reload and choose its current revision.")
            revisions[field] = revision
    if data.get("configuration_revision"):
        from .models import ConfigurationRevision
        from .advanced_equipment import configuration_available
        revision = ConfigurationRevision.objects.select_related("configuration").get(pk=data["configuration_revision"], configuration__owner=athlete)
        if revision.pk != revision.configuration.revisions.first().pk or not configuration_available(revision, athlete):
            raise ValidationError("Choose the current available configuration version.")
        revisions["configuration_revision"] = revision
    mark = SightMark(athlete=athlete, **revisions, **{key: data[key] for key in (
        "distance", "distance_unit", "mark", "sight_extension", "windage", "date", "notes") if key in data})
    mark.full_clean()
    mark.save()
    return mark


@transaction.atomic
def set_active(actor, athlete_id, entity, item_id, active):
    athlete = locked_athlete(actor, athlete_id)
    if entity == "equipment":
        obj = Equipment.objects.get(pk=item_id, athlete=athlete)
    elif entity == "arrow":
        obj = PhysicalArrow.objects.get(pk=item_id, arrow_set__athlete=athlete)
        if active and not obj.arrow_set.active:
            raise ValidationError("Restore the arrow set before restoring an arrow.")
    elif entity == "mark":
        obj = SightMark.objects.get(pk=item_id, athlete=athlete)
    else:
        raise ValidationError("Unknown equipment action.")
    obj.active = active
    obj.save(update_fields=["active"])
    return obj


def workspace(actor, athlete_id, *, bow=None):
    athlete = AthleteProfile.objects.get(pk=athlete_id)
    authorize(actor, athlete)
    items = list(Equipment.objects.filter(athlete=athlete).prefetch_related("revisions", "arrows").order_by("kind", "name", "pk"))
    current = {}
    for item in items:
        revisions = list(item.revisions.all())
        item.history = revisions
        item.current = revisions[0] if revisions else None
        current[item.pk] = item.current.pk if item.current else None
        item.specifications = specification_rows(item.current)
        for revision in revisions:
            revision.specifications = specification_rows(revision)
    marks = SightMark.objects.filter(athlete=athlete).select_related(
        "bow_revision__equipment", "arrow_revision__equipment", "configuration_revision__configuration")
    if bow:
        # A foreign/invalid filter cannot disclose another athlete's setup.
        selected = Equipment.objects.get(pk=bow, athlete=athlete, kind="bow")
        marks = marks.filter(bow_revision__equipment=selected)
    rows = list(marks.filter(configuration_revision__isnull=True))
    for mark in rows:
        mark.current_setup = (mark.bow_revision.equipment.active and
            current.get(mark.bow_revision.equipment_id) == mark.bow_revision_id and
            (not mark.arrow_revision_id or (mark.arrow_revision.equipment.active and
             current.get(mark.arrow_revision.equipment_id) == mark.arrow_revision_id)))
    rows.sort(key=lambda mark: (mark.bow_revision.equipment_id,
        mark.distance * (Decimal("0.9144") if mark.distance_unit == "yd" else 1), -mark.pk))
    advanced_marks = list(marks.filter(configuration_revision__isnull=False))
    from .advanced_equipment import configuration_available
    for mark in advanced_marks:
        rev = mark.configuration_revision
        mark.current_setup = (rev.pk == rev.configuration.revisions.first().pk and configuration_available(rev, athlete)
            and (not mark.arrow_revision_id or (mark.arrow_revision.equipment.active and current.get(mark.arrow_revision.equipment_id) == mark.arrow_revision_id)))
    return dict(athlete=training_fields(athlete), items=items, marks=rows, advanced_marks=advanced_marks,
        bows=[item for item in items if item.kind == "bow"], selected_bow=str(bow or ""),
        writable=can(actor, athlete, "edit_profile"), permissions={"edit_profile": can(actor, athlete, "edit_profile")},
        active_tab="equipment")


def specification_rows(revision):
    if not revision:
        return []
    rows = []
    for field in SPEC_FIELDS:
        value = getattr(revision, field)
        if value is None or value == "" or field.endswith("_unit"):
            continue
        unit = getattr(revision, field + "_unit", "")
        rows.append((revision._meta.get_field(field).verbose_name.capitalize(), f"{value} {unit}".strip()))
    return rows


def revision_choices(athlete, kind):
    # Highest revision per identity; revisions never become separate equipment identities.
    newer = EquipmentRevision.objects.filter(equipment_id=OuterRef("equipment_id"), number__gt=OuterRef("number"))
    return EquipmentRevision.objects.filter(equipment__athlete=athlete, equipment__kind=kind,
        equipment__active=True).filter(~Exists(newer))
