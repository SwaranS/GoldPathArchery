from datetime import date
from django.test import TestCase
from django.urls import reverse
from accounts.models import User, AthleteProfile, CoachRelationship
from .equipment_services import save_equipment

class EquipmentPageTests(TestCase):
    sections = ("overview", "configurations", "components", "arrow-sets", "sight-marks", "maintenance", "sharing", "purchases", "history", "comparisons")

    def setUp(self):
        self.user = User.objects.create_user(username="page-owner")
        self.athlete = AthleteProfile.objects.create(account=self.user, display_name="Page athlete", birth_date=date(1990, 1, 1), discipline="recurve")
        self.client.force_login(self.user)

    def url(self, section, route="athlete-equipment-section"):
        return reverse(route, args=[self.athlete.pk, section])

    def test_pages_navigation_and_separate_forms(self):
        actions = {"configurations": "configuration", "components": "component", "arrow-sets": "arrow", "sight-marks": "mark", "maintenance": "maintenance", "sharing": "share_invite", "purchases": "purchase"}
        for section in self.sections:
            page = self.client.get(self.url(section))
            self.assertEqual(page.status_code, 200, section)
            self.assertContains(page, f'data-equipment-section="{section}"')
            self.assertContains(page, f'href="{self.url(section)}" data-equipment-link="{section}" aria-current="page"')
            for target in self.sections:
                self.assertContains(page, f'href="{self.url(target)}"')
            for target, action in actions.items():
                snippet = f'name="action" value="{action}"'
                if target == section:
                    self.assertContains(page, snippet)
                else:
                    self.assertNotContains(page, snippet)
        for route in ("athlete-equipment", "scoring-equipment"):
            overview = self.client.get(reverse(route, args=[self.athlete.pk]))
            self.assertContains(overview, "My Equipment")
            self.assertNotContains(overview, 'name="action"')
        self.assertEqual(self.client.get(self.url("unknown")).status_code, 404)

    def test_saves_errors_filters_and_inventory_stay_on_page(self):
        component = self.url("components")
        invalid = self.client.post(component, {"action": "component", "category": "riser", "name": ""})
        self.assertContains(invalid, "This field is required")
        self.assertContains(invalid, 'data-equipment-section="components"')
        saved = self.client.post(component, {"action": "component", "category": "riser", "name": "Page riser"})
        self.assertRedirects(saved, component)
        arrows = self.url("arrow-sets")
        saved = self.client.post(arrows, {"action": "equipment", "kind": "arrow_set", "name": "Page arrows"})
        self.assertRedirects(saved, arrows)
        save_equipment(self.user, self.athlete.pk, {"kind": "bow", "name": "Page bow", "division": "recurve"})
        self.assertContains(self.client.get(arrows), "Page arrows")
        self.assertNotContains(self.client.get(arrows), "Page bow")
        self.assertContains(self.client.get(self.url("configurations")), "Page bow")
        self.assertNotContains(self.client.get(component, {"search": "absent"}), "Page riser")

    def test_permissions_apply_to_each_route(self):
        coach = User.objects.create_user(username="page-coach")
        CoachRelationship.objects.create(athlete=self.athlete, coach=coach)
        self.client.force_login(coach)
        for section in self.sections:
            for route in ("athlete-equipment-section", "scoring-equipment-section"):
                page = self.client.get(self.url(section, route))
                self.assertEqual(page.status_code, 404 if section == "purchases" else 200)
                self.assertEqual(self.client.post(self.url(section, route), {"action": "component"}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url("components")).status_code, 302)
