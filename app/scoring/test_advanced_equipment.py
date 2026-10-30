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
