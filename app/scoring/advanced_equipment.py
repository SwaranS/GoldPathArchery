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
    if component.status != "active":
        return False
    if component.owner_id == athlete.pk:
        return True
    return connected(component.owner, athlete) and EquipmentShare.objects.filter(component=component,
        owner_id=component.owner_id, recipient=athlete, status="approved").exists()


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
    list(EquipmentComponent.objects.select_for_update().filter(pk__in=[r.component_id for r in revisions]).order_by("pk"))
    if len(revisions) != len(ids) or len({r.component_id for r in revisions}) != len(ids):
        raise ValidationError("Invalid component selection.")
    for revision in revisions:
        revision.component.refresh_from_db()
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
            **{k: getattr(m.component_revision, k) for k in COMPONENT_FIELDS if k not in ("serial_reference", "notes")})
            for m in revision.members.select_related("component", "component_revision")])


def scoring_equipment(athlete, data, division):
    from .equipment_services import revision_snapshot
    result = {}
    if data.get("configuration"):
        config = BowConfiguration.objects.get(pk=data["configuration"], owner=athlete, active=True)
        revision = config.revisions.first()
        if revision.division != division:
            raise ValidationError("Configuration division must match the session.")
        if data.get("bow"):
            raise ValidationError("Choose either a configuration or a basic bow.")
        result["configuration"] = configuration_snapshot(revision, athlete)
    for key, kind in (("bow", "bow"), ("arrow_set", "arrow_set")):
        if data.get(key):
            item = Equipment.objects.get(pk=data[key], athlete=athlete, kind=kind, active=True)
            if kind == "bow" and item.division != division:
                raise ValidationError("Bow division must match the session.")
            result[key] = revision_snapshot(item)
    return result


from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone
from accounts.models import AthleteProfile, GuardianLink, CoachRelationship
from .models import EquipmentShare, EquipmentTransfer


def connected(left, right):
    if left.pk == right.pk or left.closed_at or right.closed_at:
        return False
    # Existing explicit relationship links only; never self-selected roles.
    parents = GuardianLink.objects.filter(athlete=left, revoked_at__isnull=True, access__in=["view", "edit"]).values("parent_id")
    return (GuardianLink.objects.filter(athlete=right, parent_id__in=parents, revoked_at__isnull=True, access__in=["view", "edit"]).exists()
        or CoachRelationship.objects.filter(athlete=left, coach_id=right.account_id, revoked_at__isnull=True).exists()
        or CoachRelationship.objects.filter(athlete=right, coach_id=left.account_id, revoked_at__isnull=True).exists())


def lock_pair(left_id, right_id):
    rows = list(AthleteProfile.objects.select_for_update().filter(pk__in=[left_id, right_id]).order_by("pk"))
    if len(rows) != 2:
        raise ValidationError("Choose a connected recipient.")
    by_id = {str(r.pk): r for r in rows}
    left, right = by_id[str(left_id)], by_id[str(right_id)]
    if not connected(left, right):
        raise ValidationError("Choose a connected recipient.")
    return left, right


@transaction.atomic
def invite_component(actor, athlete_id, component_id, recipient_id, *, transfer=False, permit_photos=False):
    owner, recipient = lock_pair(athlete_id, recipient_id)
    authorize(actor, owner, True)
    component = EquipmentComponent.objects.select_for_update().get(pk=component_id, owner=owner)
    if component.status != "active":
        raise ValidationError("Only active components can be shared or transferred.")
    if transfer:
        if component.transfers.filter(status="pending").exists():
            raise ValidationError("A transfer is already pending.")
        obj = EquipmentTransfer.objects.create(component=component, sender=owner, recipient=recipient, initiated_by=actor)
    else:
        if component.shares.filter(recipient=recipient, status__in=["pending", "approved"]).exists():
            raise ValidationError("This share already exists.")
        obj = EquipmentShare.objects.create(component=component, owner=owner, recipient=recipient, initiated_by=actor, permit_photos=permit_photos)
    activity(actor, owner, "transfer.invited" if transfer else "share.invited", component, invitation=obj.pk)
    return obj


@transaction.atomic
def decide_invitation(actor, athlete_id, invitation_id, decision, *, transfer=False):
    model = EquipmentTransfer if transfer else EquipmentShare
    candidate = model.objects.get(pk=invitation_id)
    source_id = candidate.sender_id if transfer else candidate.owner_id
    # Cancellation/revocation remains possible after connection revocation.
    rows = list(AthleteProfile.objects.select_for_update().filter(pk__in=[source_id, candidate.recipient_id]).order_by("pk"))
    athletes = {r.pk: r for r in rows}
    source, recipient = athletes[source_id], athletes[candidate.recipient_id]
    obj = model.objects.select_for_update().get(pk=invitation_id)
    component = EquipmentComponent.objects.select_for_update().get(pk=obj.component_id)
    source_action = decision in ("cancelled", "revoked")
    acting = source if source_action else recipient
    if str(athlete_id) != str(acting.pk):
        raise PermissionDenied
    authorize(actor, acting, True)
    allowed = ("accepted", "cancelled", "rejected") if transfer else ("approved", "revoked", "rejected")
    if decision not in allowed or (obj.status != "pending" and not (not transfer and obj.status == "approved" and decision == "revoked")):
        raise ValidationError("Invitation already decided or invalid action.")
    if decision in ("accepted", "approved"):
        if component.owner_id != source.pk or component.status != "active" or not connected(source, recipient):
            raise ValidationError("Invitation is no longer available.")
        if transfer:
            component.owner = recipient; component.save()
            EquipmentShare.objects.filter(component=component, status__in=["pending", "approved"]).update(status="revoked", decided_by=actor, decided_at=timezone.now())
            # New owner's revision records the ownership transition without modifying older versions.
            previous = component.revisions.first()
            ComponentRevision.objects.create(component=component, owner_at_revision=recipient, actor=actor,
                number=previous.number + 1, **{k: getattr(previous, k) for k in COMPONENT_FIELDS})
    obj.status, obj.decided_by, obj.decided_at = decision, actor, timezone.now()
    obj.save()
    event = ("transfer." if transfer else "share.") + decision
    activity(actor, source, event, component, invitation=obj.pk)
    activity(actor, recipient, event, component, invitation=obj.pk)
    return obj


def shared_components(actor, athlete):
    authorize(actor, athlete)
    rows = EquipmentShare.objects.filter(recipient=athlete, status="approved", component__status="active").select_related("component__owner", "owner")
    # Explicit safe payload: excludes serials, private notes, purchases and histories.
    result = []
    for share in rows:
        if share.owner_id != share.component.owner_id or not connected(share.owner, athlete):
            continue
        rev = share.component.revisions.first()
        result.append(dict(id=share.component_id, name=rev.name, category=share.component.category,
            manufacturer=rev.manufacturer, model=rev.model, specs=rev.specs, revision_id=rev.pk))
    return result
