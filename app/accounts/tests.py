from itertools import combinations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import UserRole


class RoleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="member", password="test-password")
        self.client.force_login(self.user)

    def test_archer_and_parent_at_once(self):
        response = self.client.post(reverse("account-profile"), {"roles": ["archer", "parent"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(self.user.role_assignments.values_list("role", flat=True)), {"archer", "parent"})

    def test_all_nonempty_role_combinations_round_trip(self):
        roles = ["archer", "parent", "coach"]
        for count in range(1, 4):
            for chosen in combinations(roles, count):
                with self.subTest(chosen=chosen):
                    response = self.client.post(reverse("account-profile"), {"roles": list(chosen)})
                    self.assertRedirects(response, reverse("account-profile"))
                    self.assertEqual(set(self.user.role_assignments.values_list("role", flat=True)), set(chosen))
                    response = self.client.get(reverse("account-profile"))
                    self.assertEqual(set(response.context["form"]["roles"].value()), set(chosen))
                    self.assertContains(response, "Parent/Guardian")
                    self.assertContains(response, "Coach")

    def test_existing_coach_can_be_retained_or_removed(self):
        UserRole.objects.create(user=self.user, role="coach")
        self.client.post(reverse("account-profile"), {"roles": ["coach", "parent"]})
        self.assertEqual(set(self.user.role_assignments.values_list("role", flat=True)), {"coach", "parent"})
        self.client.post(reverse("account-profile"), {"roles": ["parent"]})
        self.assertEqual(set(self.user.role_assignments.values_list("role", flat=True)), {"parent"})

    def test_invalid_or_empty_selection_leaves_roles_unchanged(self):
        UserRole.objects.create(user=self.user, role="coach")
        for data in ({"roles": ["archer", "administrator"]}, {"roles": []}, {}):
            with self.subTest(data=data):
                response = self.client.post(reverse("account-profile"), data)
                self.assertEqual(response.status_code, 200)
                self.assertIn("roles", response.context["form"].errors)
                self.assertEqual(list(self.user.role_assignments.values_list("role", flat=True)), ["coach"])

    def test_role_selection_does_not_grant_authority(self):
        for roles in (["coach"], ["coach", "parent", "archer"]):
            with self.subTest(roles=roles):
                for _ in range(2):
                    self.client.post(reverse("account-profile"), {"roles": roles})
                self.user.refresh_from_db()
                self.assertEqual(self.user.role_assignments.count(), len(roles))
                self.assertFalse(self.user.is_staff)
                self.assertFalse(self.user.is_superuser)
                self.assertFalse(self.user.groups.exists())
                self.assertFalse(self.user.user_permissions.exists())
                self.assertEqual(self.user.get_all_permissions(), set())
                self.assertFalse(self.user.has_perm("accounts.view_user", self.user))

    def test_saving_only_changes_current_user(self):
        other = get_user_model().objects.create_user(username="other")
        UserRole.objects.create(user=other, role="archer")
        self.client.post(reverse("account-profile"), {"roles": ["coach"]})
        self.assertEqual(list(other.role_assignments.values_list("role", flat=True)), ["archer"])

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("account-profile")).status_code, 302)
        self.assertEqual(self.client.post(reverse("account-profile"), {"roles": ["coach"]}).status_code, 302)
        self.assertFalse(self.user.role_assignments.exists())
