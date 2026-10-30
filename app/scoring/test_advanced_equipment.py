from datetime import date
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from accounts.models import AthleteProfile, User, CoachRelationship
from . import advanced_equipment as a
from .component_specs import CATEGORIES, NUMBERS, validate_specs, STATUSES
from .models import EquipmentActivity


class ComponentTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="component-owner")
        self.other = User.objects.create_user(username="component-other")
        self.athlete = AthleteProfile.objects.create(account=self.owner, display_name="Owner", birth_date=date(1990, 1, 1), discipline="recurve")

    def test_category_schemas_and_units(self):
        for category in CATEGORIES:
            specs = {k: 2 for k in NUMBERS[category].split()}
            with self.subTest(category=category):
                item = a.save_component(self.owner, self.athlete.pk, category, dict(name=category, specs=specs))
                self.assertEqual(item.revisions.first().specs, specs)
                for bad in ({"length": 3}, {"unknown": 1}, {"discipline": "longbow"}):
                    with self.assertRaises(ValidationError): validate_specs(category, bad)
                for key in NUMBERS[category].split():
                    for value in (True, -1, 0, "3", float("inf")):
                        with self.assertRaises(ValidationError): validate_specs(category, {key: value})
        with self.assertRaises(ValidationError): validate_specs("string", {"strand_count": 1.5})

    def test_revision_noop_stale_and_history(self):
        item = a.save_component(self.owner, self.athlete.pk, "riser", dict(name="Riser"))
        old = item.revisions.first()
        a.save_component(self.owner, self.athlete.pk, "riser", dict(name="Riser"), component_id=item.pk, expected_revision=old.pk)
        self.assertEqual(item.revisions.count(), 1)
        a.save_component(self.owner, self.athlete.pk, "riser", dict(name="New", specs={"length_in": 25}), component_id=item.pk, expected_revision=old.pk)
        self.assertEqual(item.revisions.count(), 2)
        old.refresh_from_db(); self.assertEqual(old.name, "Riser")
        with self.assertRaises(ValidationError): old.save()
        with self.assertRaises(ValidationError):
            a.save_component(self.owner, self.athlete.pk, "riser", dict(name="Stale"), component_id=item.pk, expected_revision=old.pk)
        self.assertEqual(EquipmentActivity.objects.count(), 2)

    def test_permissions_lifecycle_and_both_routes(self):
        item = a.save_component(self.owner, self.athlete.pk, "riser", dict(name="Private riser"))
        CoachRelationship.objects.create(athlete=self.athlete, coach=self.other)
        with self.assertRaises(PermissionDenied):
            a.save_component(self.other, self.athlete.pk, "riser", dict(name="Forbidden"))
        for status in STATUSES:
            a.set_component_status(self.owner, self.athlete.pk, item.pk, status)
        with self.assertRaises(ValidationError): a.set_component_status(self.owner, self.athlete.pk, item.pk, "invalid")
        self.client.force_login(self.owner)
        for route in ("athlete-equipment", "scoring-equipment"):
            url = reverse(route, args=[self.athlete.pk])
            self.assertContains(self.client.get(url), "Private riser")
            response = self.client.post(url, dict(action="component", category="string", name="Spare string", specs='{"strand_count": 16}'))
            self.assertEqual(response.status_code, 302)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(url), "Save component")
        self.assertEqual(self.client.post(url, dict(action="component", category="string", name="Forbidden")).status_code, 404)


class ConfigurationTests(ComponentTests):
    def test_versions_reuse_defaults_and_frozen_membership(self):
        item = a.save_component(self.owner, self.athlete.pk, "riser", dict(name="Riser", specs={"length_in": 25}))
        old = item.revisions.first()
        with self.assertRaises(ValidationError):
            a.save_configuration(self.owner, self.athlete.pk, "Indoor", "recurve", [old.pk])
        config = a.save_configuration(self.owner, self.athlete.pk, "Indoor", "recurve", [old.pk], acknowledged=True)
        rev = config.revisions.first()
        a.save_configuration(self.owner, self.athlete.pk, "Outdoor", "recurve", [old.pk], acknowledged=True)
        a.save_configuration(self.owner, self.athlete.pk, "Indoor", "recurve", [old.pk], configuration_id=config.pk, expected_revision=rev.pk, acknowledged=True)
        self.assertEqual(config.revisions.count(), 1)
        a.save_component(self.owner, self.athlete.pk, "riser", dict(name="Revised", specs={"length_in": 27}), component_id=item.pk, expected_revision=old.pk)
        self.assertEqual(rev.components.get().pk, old.pk)
        a.set_default(self.owner, self.athlete.pk, config.pk)
        a.save_configuration(self.owner, self.athlete.pk, "Renamed", "recurve", [old.pk], configuration_id=config.pk, expected_revision=rev.pk, acknowledged=True)
        self.assertEqual(config.revisions.count(), 2)
        a.set_component_status(self.owner, self.athlete.pk, item.pk, "in_repair")
        self.assertFalse(a.configuration_available(config.revisions.first(), self.athlete))
        with self.assertRaises(ValidationError): a.set_default(self.owner, self.athlete.pk, config.pk)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("athlete-equipment", args=[self.athlete.pk])), "Unavailable for new scores")

    def test_compatibility_and_private_references(self):
        item = a.save_component(self.owner, self.athlete.pk, "limbs", dict(name="Compound limbs", specs={"discipline": "compound"}))
        with self.assertRaises(ValidationError):
            a.save_configuration(self.owner, self.athlete.pk, "Invalid", "recurve", [item.revisions.first().pk], acknowledged=True)
        for division in ("recurve", "compound", "barebow"):
            a.save_configuration(self.owner, self.athlete.pk, division, division, [], acknowledged=True)
        with self.assertRaises(ValidationError): a.save_configuration(self.owner, self.athlete.pk, "Longbow", "longbow", [], acknowledged=True)
        other_athlete = AthleteProfile.objects.create(account=self.other, display_name="Other", birth_date=date(1990, 1, 1), discipline="recurve")
        with self.assertRaises(ValidationError):
            a.save_configuration(self.other, other_athlete.pk, "Private", "compound", [item.revisions.first().pk], acknowledged=True)


from .test_equipment import EquipmentTests
from . import services as scoring, equipment_services as legacy
from .forms import StartForm
import uuid
from copy import deepcopy

class ConfigurationScoringTests(EquipmentTests):
    def config(self):
        item = a.save_component(self.owner, self.athlete.pk, "riser", dict(name="Scoring riser"))
        config = a.save_configuration(self.owner, self.athlete.pk, "Match", "recurve", [item.revisions.first().pk], preferred_arrows_id=self.arrows.pk, acknowledged=True)
        return item, config

    def test_default_snapshot_and_first_arrow_lock(self):
        item, config = self.config()
        a.set_default(self.owner, self.athlete.pk, config.pk)
        form = StartForm(athlete=self.athlete)
        self.assertEqual(form.fields["configuration"].initial, config.pk)
        self.assertEqual(form.fields["arrow_set"].initial, self.arrows.pk)
        session = self.start()
        def change(**data):
            session.refresh_from_db()
            return scoring.mutate(self.owner, session.pk, dict(action="equipment", key=str(uuid.uuid4()), version=session.version, **data))
        change(configuration=config.pk, arrow_set=self.arrows.pk)
        session.refresh_from_db(); original = deepcopy(session.equipment)
        arrow = self.arrow()
        self.shot(session, 0, arrow)
        for data in (dict(configuration=config.pk), dict(bow=self.bow.pk), dict(arrow_set=self.arrows.pk), {}):
            with self.assertRaises(ValidationError): change(**data)
        a.save_component(self.owner, self.athlete.pk, "riser", dict(name="Changed"), component_id=item.pk, expected_revision=item.revisions.first().pk)
        a.set_component_status(self.owner, self.athlete.pk, item.pk, "retired")
        session.refresh_from_db(); self.assertEqual(session.equipment, original)
        with self.assertRaises(ValidationError): a.configuration_snapshot(config.revisions.first(), self.athlete)

    def test_exact_marks_and_stale_versions(self):
        item, config = self.config()
        revision = config.revisions.first()
        mark = legacy.save_mark(self.owner, self.athlete.pk, dict(configuration_revision=revision.pk, distance=18, distance_unit="m", mark="4"))
        self.assertTrue(legacy.workspace(self.owner, self.athlete.pk)["advanced_marks"][0].current_setup)
        a.save_configuration(self.owner, self.athlete.pk, "Changed", "recurve", [item.revisions.first().pk], configuration_id=config.pk, expected_revision=revision.pk, acknowledged=True)
        self.assertFalse(legacy.workspace(self.owner, self.athlete.pk)["advanced_marks"][0].current_setup)
        with self.assertRaises(ValidationError):
            legacy.save_mark(self.owner, self.athlete.pk, dict(configuration_revision=revision.pk, distance=18, distance_unit="m", mark="Stale"))
        mark.refresh_from_db(); self.assertEqual(mark.configuration_revision_id, revision.pk)


from accounts.models import GuardianLink
class SharingTests(ComponentTests):
    def test_pending_approval_revocation_transfer_and_privacy(self):
        recipient = AthleteProfile.objects.create(account=self.other, display_name="Recipient", birth_date=date(1990, 1, 1), discipline="recurve")
        guardian = User.objects.create_user(username="shared-guardian")
        for athlete in (self.athlete, recipient):
            GuardianLink.objects.create(athlete=athlete, parent=guardian, access="view")
        component = a.save_component(self.owner, self.athlete.pk, "riser", dict(name="Shared riser", serial_reference="SECRET", notes="PRIVATE"))
        share = a.invite_component(self.owner, self.athlete.pk, component.pk, recipient.pk)
        self.assertEqual(a.shared_components(self.other, recipient), [])
        with self.assertRaises(ValidationError):
            a.save_configuration(self.other, recipient.pk, "Pending", "recurve", [component.revisions.first().pk], acknowledged=True)
        a.decide_invitation(self.other, recipient.pk, share.pk, "approved")
        payload = a.shared_components(self.other, recipient)
        self.assertEqual(payload[0]["name"], "Shared riser")
        self.assertNotIn("PRIVATE", str(payload)); self.assertNotIn("SECRET", str(payload))
        config = a.save_configuration(self.other, recipient.pk, "Shared", "recurve", [component.revisions.first().pk], acknowledged=True)
        snapshot = a.configuration_snapshot(config.revisions.first(), recipient)
        a.decide_invitation(self.owner, self.athlete.pk, share.pk, "revoked")
        self.assertEqual(a.shared_components(self.other, recipient), [])
        self.assertFalse(a.configuration_available(config.revisions.first(), recipient))
        self.assertEqual(snapshot["components"][0]["name"], "Shared riser")
        transfer = a.invite_component(self.owner, self.athlete.pk, component.pk, recipient.pk, transfer=True)
        component.refresh_from_db(); self.assertEqual(component.owner_id, self.athlete.pk)
        with self.assertRaises(PermissionDenied):
            a.decide_invitation(self.owner, recipient.pk, transfer.pk, "accepted", transfer=True)
        a.decide_invitation(self.other, recipient.pk, transfer.pk, "accepted", transfer=True)
        component.refresh_from_db(); self.assertEqual(component.owner_id, recipient.pk)
        self.assertEqual(component.revisions.first().owner_at_revision_id, recipient.pk)
        with self.assertRaises(ValidationError):
            a.decide_invitation(self.other, recipient.pk, transfer.pk, "accepted", transfer=True)

    def test_unconnected_and_cancelled_transfer(self):
        recipient = AthleteProfile.objects.create(account=self.other, display_name="Other", birth_date=date(1990, 1, 1), discipline="recurve")
        component = a.save_component(self.owner, self.athlete.pk, "string", dict(name="String"))
        with self.assertRaises(ValidationError): a.invite_component(self.owner, self.athlete.pk, component.pk, recipient.pk)
        CoachRelationship.objects.create(athlete=self.athlete, coach=self.other)
        transfer = a.invite_component(self.owner, self.athlete.pk, component.pk, recipient.pk, transfer=True)
        a.decide_invitation(self.owner, self.athlete.pk, transfer.pk, "cancelled", transfer=True)
        component.refresh_from_db(); self.assertEqual(component.owner_id, self.athlete.pk)
