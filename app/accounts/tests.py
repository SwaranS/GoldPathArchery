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

    def test_no_self_selected_coach_access(self):
        response = self.client.post(reverse("account-profile"), {"roles": ["archer", "coach"]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.user.role_assignments.filter(role="coach").exists())

    def test_admin_assigned_coach_role_preserved(self):
        UserRole.objects.create(user=self.user, role="coach")
        self.client.post(reverse("account-profile"), {"roles": ["parent"]})
        self.assertEqual(set(self.user.role_assignments.values_list("role", flat=True)), {"coach", "parent"})

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("account-profile")).status_code, 302)
