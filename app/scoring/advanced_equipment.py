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


from .models import BowConfiguration, ConfigurationRevision, ConfigurationMember, AthleteEquipmentDefaults, Equipment

# Category rules establish discipline restrictions only where unambiguous.
CATEGORY_DIVISIONS = {category: {"recurve", "compound", "barebow"} for category in (
    "riser", "limbs", "string", "sight", "stabiliser", "arrow_rest", "plunger", "clicker", "scope_peep", "damper", "release_tab", "other")}
CATEGORY_DIVISIONS.update(sight={"recurve", "compound"}, scope_peep={"compound"},
    clicker={"recurve"}, plunger={"recurve", "barebow"})


def compatibility(division, revisions):
    if division not in ("recurve", "compound", "barebow"):
        raise ValidationError("Choose recurve, compound or barebow.")
    warnings = []
    for revision in revisions:
        category, specs = revision.component.category, revision.specs
        if division not in CATEGORY_DIVISIONS[category] or (specs.get("discipline") and specs["discipline"] != division):
            raise ValidationError("A component is incompatible with this discipline.")
        warnings.append(f"fit_unverified:{revision.pk}")
    interfaces = {r.specs["interface"].strip().lower() for r in revisions if r.component.category in ("riser", "limbs") and r.specs.get("interface")}
    if len(interfaces) > 1:
        warnings.append("interface_mismatch")
    # A saved configuration is not a physical fit or safety certification.
    if not revisions:
        warnings.append("no_components")
    return sorted(warnings)


def available(component, athlete):
    return component.status == "active" and component.owner_id == athlete.pk


def configuration_available(revision, athlete):
    return (revision.configuration.owner_id == athlete.pk and revision.configuration.active and
        all(available(m.component, athlete) for m in revision.members.select_related("component")))


@transaction.atomic
def save_configuration(actor, athlete_id, name, division, revision_ids, *, configuration_id=None,
        expected_revision=None, preferred_arrows_id=None, acknowledged=False, reason=""):
    athlete = locked_athlete(actor, athlete_id)
    if configuration_id:
        config = BowConfiguration.objects.select_for_update().get(pk=configuration_id, owner=athlete)
        previous = config.revisions.first()
        if previous.pk != expected_revision or not config.active:
            raise ValidationError("Configuration changed or is archived; reload first.")
    else:
        config = BowConfiguration.objects.create(owner=athlete)
        previous = None
    ids = list(revision_ids)
    if len(ids) != len(set(ids)):
        raise ValidationError("Select each component revision once.")
    revisions = list(ComponentRevision.objects.filter(pk__in=ids).select_related("component"))
    if len(revisions) != len(ids) or len({r.component_id for r in revisions}) != len(ids):
        raise ValidationError("Invalid component selection.")
    for revision in revisions:
        if not available(revision.component, athlete):
            raise ValidationError("A selected component is unavailable.")
    arrows = Equipment.objects.get(pk=preferred_arrows_id, athlete=athlete, kind="arrow_set", active=True) if preferred_arrows_id else None
    warnings = compatibility(division, revisions)
    if warnings and acknowledged is not True:
        raise ValidationError("Acknowledge unverified physical fit: " + ", ".join(warnings))
    if previous and (previous.name, previous.division, previous.preferred_arrows_id,
        set(previous.components.values_list("pk", flat=True))) == (name, division, arrows.pk if arrows else None, set(ids)):
        return config
    revision = ConfigurationRevision.objects.create(configuration=config, number=previous.number + 1 if previous else 1,
        name=name, division=division, preferred_arrows=arrows, actor=actor, warnings=warnings,
        acknowledged=acknowledged, reason=reason)
    for component_revision in revisions:
        ConfigurationMember.objects.create(revision=revision, component=component_revision.component, component_revision=component_revision)
    activity(actor, athlete, "configuration.revised", configuration=config.pk, revision=revision.number)
    return config


@transaction.atomic
def set_default(actor, athlete_id, configuration_id=None):
    athlete = locked_athlete(actor, athlete_id)
    config = BowConfiguration.objects.get(pk=configuration_id, owner=athlete, active=True) if configuration_id else None
    if config and not configuration_available(config.revisions.first(), athlete):
        raise ValidationError("The configuration is unavailable.")
    AthleteEquipmentDefaults.objects.update_or_create(athlete=athlete, defaults={"configuration": config})
    activity(actor, athlete, "configuration.default", configuration=config.pk if config else None)


@transaction.atomic
def archive_configuration(actor, athlete_id, configuration_id, active):
    athlete = locked_athlete(actor, athlete_id)
    config = BowConfiguration.objects.select_for_update().get(pk=configuration_id, owner=athlete)
    if config.active != active:
        config.active = active; config.save(update_fields=["active"])
        activity(actor, athlete, "configuration.status", configuration=config.pk, active=active)
    return config


def configuration_snapshot(revision, athlete):
    if not configuration_available(revision, athlete):
        raise ValidationError("Configuration contains unavailable components.")
    return dict(id=revision.configuration_id, revision_id=revision.pk, revision=revision.number,
        name=revision.name, division=revision.division, warnings=revision.warnings, rule_version=revision.rule_version,
        components=[dict(id=m.component_id, revision_id=m.component_revision_id, revision=m.component_revision.number,
            owner_id=str(m.component_revision.owner_at_revision_id), category=m.component.category,
            **{k: getattr(m.component_revision, k) for k in COMPONENT_FIELDS if k != "serial_reference"})
            for m in revision.members.select_related("component", "component_revision")])
