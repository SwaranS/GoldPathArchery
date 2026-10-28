from datetime import date
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from .models import AthleteProfile, CoachRelationship, GuardianLink, RelationshipAudit, UserRole
from .plan_models import PlanSetup

class PlansTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="plan-owner")
        self.coach = User.objects.create_user(username="plan-coach")
        self.parent = User.objects.create_user(username="plan-parent")
        self.stranger = User.objects.create_user(username="plan-stranger")
        self.athlete = AthleteProfile.objects.create(account=self.owner, display_name="Test Archer",
            birth_date=date(2000, 1, 1), discipline="barebow", goals="Profile goals",
            availability="Saturday", transitioned_at=timezone.now())
        UserRole.objects.create(user=self.owner, role="archer")
        self.url = reverse("athlete-plans", args=[self.athlete.pk])
        self.client.force_login(self.owner)

    def data(self, **updates):
        self.athlete.refresh_from_db()
        data = dict(version=self.athlete.version, goals="Improve consistency", experience="Two years",
            weekly_sessions=0, weekly_arrows=0, availability="Saturday, 90 minutes",
            range_access="Indoor 18m", equipment="Barebow and arrows", duration_days=84,
            review_day=1, competition_date="", action="submit")
        data.update(updates)
        return data

    def test_empty_state_and_own_navigation(self):
        response = self.client.get(self.url)
        self.assertContains(response, "No plan yet")
        self.assertContains(response, "Set up a training plan")
        self.assertEqual(response.context["setup_form"].initial["goals"], "Profile goals")
        self.assertContains(response, reverse("my-plans"))
        self.assertRedirects(self.client.get(reverse("my-plans")), self.url)
        self.assertFalse(PlanSetup.objects.exists())

    def test_partial_draft_resume_submit_and_replay(self):
        response = self.client.post(self.url, self.data(action="save", experience="", equipment=""))
        self.assertRedirects(response, self.url)
        self.assertIsNone(PlanSetup.objects.get().submitted_at)
        self.assertContains(self.client.get(self.url), "Draft saved")
        self.assertRedirects(self.client.post(self.url, self.data()), self.url)
        setup = PlanSetup.objects.get()
        self.assertIsNotNone(setup.submitted_at)
        self.assertEqual(setup.weekly_arrows, 0)
        response = self.client.get(self.url)
        self.assertContains(response, "Setup submitted")
        self.assertContains(response, "preparation has not started")
        self.assertNotContains(response, 'name="action"')
        self.client.post(self.url, self.data(goals="Do not overwrite"))
        setup.refresh_from_db()
        self.assertEqual(setup.goals, "Improve consistency")
        self.assertEqual(PlanSetup.objects.count(), 1)
        self.assertEqual(RelationshipAudit.objects.filter(operation="submit_plan_setup").count(), 1)

    def test_validation_keeps_input(self):
        response = self.client.post(self.url, self.data(experience="", weekly_arrows=""))
        self.assertContains(response, "Complete this before submitting")
        self.assertContains(response, "Improve consistency")
        self.assertFalse(PlanSetup.objects.exists())
        for changes in ({"duration_days": -1}, {"duration_days": 366}, {"weekly_arrows": -1}):
            response = self.client.post(self.url, self.data(**changes))
            self.assertTrue(response.context["setup_form"].errors)
        self.assertFalse(PlanSetup.objects.exists())

    def test_stale_tab_no_overwrite(self):
        old = self.data(action="save")
        self.client.post(self.url, old)
        response = self.client.post(self.url, dict(old, goals="Stale edit"))
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Stale edit", status_code=409)
        self.assertEqual(PlanSetup.objects.get().goals, "Improve consistency")

    def test_coach_read_only_and_revocation(self):
        link = CoachRelationship.objects.create(athlete=self.athlete, coach=self.coach, plan_edit=True)
        self.client.post(self.url, self.data(action="save"))
        self.client.force_login(self.coach)
        response = self.client.get(self.url)
        self.assertContains(response, "Planning brief")
        self.assertContains(response, "Improve consistency")
        self.assertNotContains(response, 'name="action"')
        for private in ("birth_date", "2000-01-01", self.owner.username):
            self.assertNotContains(response, private)
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 404)
        link.revoked_at = timezone.now()
        link.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_parent_age_boundary_and_adult_grant(self):
        today = timezone.localdate()
        self.athlete.birth_date = date(today.year - 15, 1, 1)
        self.athlete.transitioned_at = None
        self.athlete.save()
        link = GuardianLink.objects.create(athlete=self.athlete, parent=self.parent, managing=True)
        self.client.force_login(self.parent)
        self.assertRedirects(self.client.post(self.url, self.data(action="save")), self.url)
        self.athlete.birth_date = date(today.year - 16, 1, 1)
        self.athlete.save()
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        link.refresh_from_db()
        self.assertEqual(link.access, "view")
        link.access = "edit"
        link.adult_grant = True
        link.save()
        self.assertRedirects(self.client.post(self.url, self.data()), self.url)

    def test_junior_additional_roles_do_not_enable_writes(self):
        today = timezone.localdate()
        self.athlete.birth_date = date(today.year - 15, 1, 1)
        self.athlete.save()
        for role in ("coach", "parent"):
            UserRole.objects.create(user=self.owner, role=role)
        response = self.client.get(self.url)
        self.assertContains(response, "read-only")
        self.assertNotContains(response, 'name="action"')
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 404)
        self.athlete.birth_date = date(today.year - 13, 1, 1)
        self.athlete.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_unrelated_closed_inactive_login_and_csrf(self):
        UserRole.objects.create(user=self.stranger, role="archer")
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 404)
        self.assertContains(self.client.get(reverse("my-plans")), "Start with your athlete profile")
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(self.url, self.data()).status_code, 403)
        self.client.force_login(self.owner)
        self.athlete.closed_at = timezone.now()
        self.athlete.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 404)
        self.owner.is_active = False
        self.owner.save()
        self.assertEqual(self.client.get(self.url).status_code, 302)
