from datetime import date

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AthleteProfile, CoachRelationship, GuardianLink, UserRole


class AthleteSwitcherTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="switcher-member")
        self.client.force_login(self.user)

    def role(self, *roles):
        for role in roles:
            UserRole.objects.get_or_create(user=self.user, role=role)

    def athlete(self, name, own=False, child=False, **kwargs):
        return AthleteProfile.objects.create(
            display_name=name, account=self.user if own else None,
            birth_date=date(2020 if child else 2000, 1, 1), discipline="recurve",
            transitioned_at=None if child else timezone.now(), **kwargs)

    def page(self, athlete):
        return self.client.get(reverse("athlete-detail", args=[athlete.pk]))

    def assert_hidden(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_athlete_switcher"])
        self.assertNotContains(response, "Switch athlete")
        self.assertNotContains(response, "Switch User")
        self.assertNotContains(response, '<details class="athlete-switcher">')
        self.assertNotContains(response, '<div class="athlete-banner-actions">')

    def test_archer_own_profile_only_hidden_and_editing_works(self):
        self.role("archer")
        own = self.athlete("Own Archer", own=True)
        self.assert_hidden(self.page(own))
        self.assert_hidden(self.client.get(reverse("account-profile")))
        self.assertContains(self.page(own), "Save profile")
        response = self.client.post(reverse("athlete-detail", args=[own.pk]), {
            "version": own.version, "display_name": "Updated own", "discipline": "barebow",
            "goals": "Practice", "availability": "Saturday"})
        self.assertRedirects(response, reverse("athlete-detail", args=[own.pk]))
        own.refresh_from_db()
        self.assertEqual(own.display_name, "Updated own")

    def test_parent_two_children_list_and_current_selection(self):
        self.role("parent")
        first = self.athlete("First child", child=True)
        second = self.athlete("Second child", child=True)
        for athlete in (first, second):
            GuardianLink.objects.create(athlete=athlete, parent=self.user, managing=True)
        response = self.page(first)
        self.assertTrue(response.context["show_athlete_switcher"])
        self.assertContains(response, "Switch athlete")
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "First child<span")
        self.assertContains(response, "(current athlete)")
        options = response.context["athlete_switcher_options"]
        self.assertEqual({option["id"] for option in options}, {str(first.pk), str(second.pk)})
        self.assertContains(response, reverse("athlete-detail", args=[second.pk]))
        switched = self.page(second)
        self.assertContains(switched, "Second child<span")
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.user.pk)
        self.assertContains(self.client.get(reverse("account-profile")), "Switch athlete")

    def test_archer_parent_own_and_child_visible(self):
        self.role("archer", "parent")
        own = self.athlete("Own", own=True)
        child = self.athlete("Child", child=True)
        GuardianLink.objects.create(athlete=child, parent=self.user, managing=True)
        self.assertContains(self.page(own), "Switch athlete")

    def test_coach_one_then_two_and_revocation(self):
        self.role("coach")
        first = self.athlete("First linked")
        second = self.athlete("Second linked")
        CoachRelationship.objects.create(athlete=first, coach=self.user)
        self.assert_hidden(self.page(first))
        second_link = CoachRelationship.objects.create(athlete=second, coach=self.user)
        self.assertContains(self.page(first), "Switch athlete")
        second_link.revoked_at = timezone.now()
        second_link.save()
        self.assert_hidden(self.page(first))
        self.assertEqual(self.page(second).status_code, 404)

    def test_no_profiles_or_multiple_roles_only_hidden(self):
        self.role("archer", "parent", "coach")
        self.assert_hidden(self.client.get(reverse("account-profile")))
        own = self.athlete("Only own", own=True)
        self.assert_hidden(self.page(own))

    def test_switcher_excludes_unshared_revoked_closed_and_no_access(self):
        self.role("archer", "parent", "coach")
        own = self.athlete("Own", own=True)
        # Search-hidden profiles remain accessible to explicitly linked people.
        linked = self.athlete("Linked hidden child", child=True, hidden=True)
        GuardianLink.objects.create(athlete=linked, parent=self.user, managing=True)
        unrelated = self.athlete("Hidden unrelated", hidden=True)
        revoked = self.athlete("Revoked")
        CoachRelationship.objects.create(athlete=revoked, coach=self.user, revoked_at=timezone.now())
        closed = self.athlete("Closed", closed_at=timezone.now())
        CoachRelationship.objects.create(athlete=closed, coach=self.user)
        none = self.athlete("No access", child=True)
        GuardianLink.objects.create(athlete=none, parent=self.user, access="none")
        response = self.page(own)
        self.assertEqual({option["id"] for option in response.context["athlete_switcher_options"]},
                         {str(own.pk), str(linked.pk)})
        for target in (unrelated, revoked, closed, none):
            self.assertNotContains(response, target.display_name)
            url = reverse("athlete-detail", args=[target.pk])
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {"version": target.version,
                "display_name": "Forbidden change", "discipline": "recurve"}).status_code, 404)
            target.refresh_from_db()
            self.assertNotEqual(target.display_name, "Forbidden change")

    def test_role_removal_does_not_hide_valid_multiple_relationships(self):
        self.role("archer")
        own = self.athlete("Own", own=True)
        linked = self.athlete("Previously linked")
        CoachRelationship.objects.create(athlete=linked, coach=self.user)
        self.assertContains(self.page(own), "Switch athlete")

    def test_role_selection_still_works_and_does_not_create_access(self):
        own = self.athlete("Only own", own=True)
        other = self.athlete("Unshared")
        response = self.client.post(reverse("account-profile"), {"roles": ["archer", "coach", "parent"]})
        self.assertRedirects(response, reverse("account-profile"))
        self.assert_hidden(self.page(own))
        self.assertEqual(self.page(other).status_code, 404)
