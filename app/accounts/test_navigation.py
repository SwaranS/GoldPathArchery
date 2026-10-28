from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AthleteProfile, CoachRelationship, GuardianLink, UserRole


class WorkspaceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="member")
        self.client.force_login(self.user)

    def roles(self, *roles):
        self.user.role_assignments.all().delete()
        for role in roles:
            UserRole.objects.create(user=self.user, role=role)

    def athlete(self, name="Own", age=25, **kwargs):
        today = timezone.localdate()
        return AthleteProfile.objects.create(
            display_name=name, birth_date=date(today.year-age, 1, 1),
            discipline="recurve", **kwargs,
        )

    def test_archer_home_and_connections(self):
        self.roles("archer")
        own = self.athlete(account=self.user)
        response = self.client.get(reverse("home"), follow=True)
        self.assertEqual(response.request["PATH_INFO"], reverse("athlete-detail", args=[own.pk]))
        nav = response.content.decode().split('<nav aria-label="Main navigation">')[1].split('</nav>')[0]
        for label in ("My profile", "My connections", "My account"):
            self.assertIn(label, nav)
        for label in ("My athletes", "Family", "Coaching"):
            self.assertNotIn(label, nav)
        self.assertRedirects(self.client.get(reverse("workspace", args=["archer"])+"?connections=1"),
                             reverse("athlete-detail", args=[own.pk])+"#connections")

    def test_archer_setup_is_separate(self):
        self.roles("archer", "parent")
        response = self.client.get(reverse("workspace", args=["archer"]))
        self.assertTrue(response.context["can_create_own"])
        self.assertFalse(response.context["can_create_child"])
        response = self.client.get(reverse("workspace", args=["parent"]))
        self.assertFalse(response.context["can_create_own"])
        self.assertTrue(response.context["can_create_child"])

    def test_coaching_only_lists_active_coach_links(self):
        self.roles("coach")
        linked = self.athlete("Linked")
        revoked = self.athlete("Revoked")
        unrelated = self.athlete("Unrelated")
        CoachRelationship.objects.create(athlete=linked, coach=self.user, plan_edit=True)
        CoachRelationship.objects.create(athlete=revoked, coach=self.user, revoked_at=timezone.now())
        response = self.client.get(reverse("workspace", args=["coach"]))
        self.assertContains(response, "Linked")
        self.assertContains(response, "Can edit plans")
        self.assertNotContains(response, "Revoked")
        self.assertNotContains(response, "Unrelated")
        for athlete in (revoked, unrelated):
            self.assertEqual(self.client.get(reverse("athlete-detail", args=[athlete.pk])).status_code, 404)
        response = self.client.get(reverse("athlete-detail", args=[linked.pk]))
        self.assertNotIn("form", response.context)
        self.assertNotContains(response, "Save profile")
        self.assertFalse(response.context["permissions"]["log_scores"])

    def test_role_alone_provides_empty_coaching(self):
        self.roles("coach")
        self.athlete("Private")
        response = self.client.get(reverse("workspace", args=["coach"]))
        self.assertContains(response, "No coaching connections yet")
        self.assertNotContains(response, "Private")

    def test_family_and_role_removal_keep_explicit_access(self):
        self.roles("parent")
        for name in ("Child one", "Child two"):
            child = self.athlete(name, age=10)
            GuardianLink.objects.create(athlete=child, parent=self.user, managing=True)
        self.athlete("Other child", age=10)
        response = self.client.get(reverse("workspace", args=["parent"]))
        self.assertContains(response, "Child one")
        self.assertContains(response, "Child two")
        self.assertNotContains(response, "Other child")
        self.roles("archer")
        self.assertEqual(self.client.get(reverse("workspace", args=["parent"])).status_code, 404)
        self.assertContains(self.client.get(reverse("athletes")), "Child one")
        self.assertContains(self.client.get(reverse("account-profile")), "All linked athletes")

    def test_workspace_choice_and_stale_preference(self):
        self.roles("archer", "parent", "coach")
        self.assertContains(self.client.get(reverse("workspace-home")), "Choose your workspace")
        self.client.get(reverse("workspace", args=["coach"]))
        self.assertRedirects(self.client.get(reverse("workspace-home")), reverse("workspace", args=["coach"]))
        self.roles("parent")
        self.assertRedirects(self.client.get(reverse("workspace-home")), reverse("workspace", args=["parent"]))

    def test_junior_other_roles_do_not_enable_creation(self):
        self.roles("archer", "parent", "coach")
        own = self.athlete(age=15, account=self.user)
        response = self.client.get(reverse("athlete-detail", args=[own.pk]))
        self.assertNotIn("form", response.context)
        response = self.client.get(reverse("workspace", args=["parent"]))
        self.assertFalse(response.context["can_create_child"])
        self.assertFalse(response.context["can_create_own"])

    def test_age_review_precedes_workspace_choice(self):
        self.roles("archer", "parent")
        own = self.athlete(account=self.user, transitioned_at=timezone.now(), parent_review_required=True)
        self.assertRedirects(self.client.get(reverse("workspace-home")), reverse("athlete-detail", args=[own.pk]))

    def test_closed_profile_has_no_duplicate_setup(self):
        self.roles("archer")
        self.athlete(account=self.user, closed_at=timezone.now())
        response = self.client.get(reverse("workspace", args=["archer"]))
        self.assertFalse(response.context["can_create_own"])

    def test_unknown_workspace_and_coach_creation_denied(self):
        self.roles("coach")
        self.assertEqual(self.client.get(reverse("workspace", args=["unknown"])).status_code, 404)
        self.assertEqual(self.client.post(reverse("workspace", args=["coach"]), {}).status_code, 404)

    def test_scoped_creation_preserves_invalid_input_and_target_type(self):
        self.roles("archer", "parent")
        own_url = reverse("workspace", args=["archer"])
        family_url = reverse("workspace", args=["parent"])
        response = self.client.post(own_url, {"display_name": "Keep my input"})
        self.assertContains(response, "Keep my input")
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(self.client.post(own_url, {"child": "on"}).status_code, 404)
        self.assertEqual(self.client.post(family_url, {}).status_code, 404)
        data = {"display_name": "New archer", "birth_date": "2000-01-01",
                "timezone": "Europe/Dublin", "discipline": "recurve"}
        response = self.client.post(own_url, data)
        own = AthleteProfile.objects.get(account=self.user)
        self.assertRedirects(response, reverse("athlete-detail", args=[own.pk]))
        data.update(display_name="New child", birth_date="2020-01-01", child="on", declaration="on")
        response = self.client.post(family_url, data)
        child = AthleteProfile.objects.get(display_name="New child")
        self.assertRedirects(response, reverse("athlete-detail", args=[child.pk]))
        self.assertTrue(GuardianLink.objects.filter(athlete=child, parent=self.user).exists())
