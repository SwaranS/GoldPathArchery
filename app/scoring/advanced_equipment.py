"""Advanced equipment mutations share the established athlete authorization boundary."""
from django.core.exceptions import ValidationError
from django.db import transaction
from .equipment_services import locked_athlete, authorize
from .models import EquipmentComponent, ComponentRevision, EquipmentActivity

COMPONENT_FIELDS = ("name", "manufacturer", "model", "serial_reference", "notes", "specs")


def activity(actor, athlete, event, component=None, **detail):
    return EquipmentActivity.objects.create(actor=actor, owner=athlete, event=event, component=component, detail=detail)


@transaction.atomic
def save_component(actor, athlete_id, category, data, *, component_id=None, expected_revision=None):
    athlete = locked_athlete(actor, athlete_id)
    if set(data) - set(COMPONENT_FIELDS):
        raise ValidationError("Unsupported component fields.")
    if component_id:
        component = EquipmentComponent.objects.select_for_update().get(pk=component_id, owner=athlete)
        previous = component.revisions.first()
        if component.category != category or previous.pk != expected_revision:
            raise ValidationError("The component changed. Reload before revising.")
    else:
        component = EquipmentComponent(owner=athlete, category=category)
        component.full_clean(); component.save()
        previous = None
    revision = ComponentRevision(component=component, owner_at_revision=athlete, actor=actor,
        number=previous.number + 1 if previous else 1, **data)
    revision.full_clean()
    if previous and all(getattr(previous, k) == getattr(revision, k) for k in COMPONENT_FIELDS):
        return component
    revision.save()
    activity(actor, athlete, "component.revised" if previous else "component.created", component, revision=revision.number)
    return component


@transaction.atomic
def set_component_status(actor, athlete_id, component_id, status, reason=""):
    athlete = locked_athlete(actor, athlete_id)
    component = EquipmentComponent.objects.select_for_update().get(pk=component_id, owner=athlete)
    before = component.status
    component.status = status
    component.full_clean()
    if status != before:
        component.save()
        activity(actor, athlete, "component.status", component, before=before, after=status, reason=str(reason)[:500])
    return component


def component_workspace(actor, athlete):
    authorize(actor, athlete)
    return EquipmentComponent.objects.filter(owner=athlete).prefetch_related("revisions").order_by("category", "pk")
