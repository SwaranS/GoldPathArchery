from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import resolve, reverse

from . import relationships as service
from .models import (
    AthleteProfile,
    CoachRelationship,
    GuardianLink,
    RelationshipAudit,
    RelationshipInvitation,
    RelationshipNotice,
    UserRole,
)
from .permissions import OPERATIONS, accessible_athletes, can

NOW = datetime(2026, 10, 26, 12, tzinfo=dt_timezone.utc)


class RelationshipTests(TestCase):
    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.owner = self.user("owner", "archer")
        self.parent = self.user("parent", "parent", "coach", "archer")
        self.coach = self.user("coach", "coach")
        self.stranger = self.user("stranger", "coach", "parent", "archer")
        self.junior = self.user("junior", "archer")
        self.adult = AthleteProfile.objects.create(
            account=self.owner,
            display_name="Private Adult",
            birth_date=date(2000, 1, 1),
            discipline="recurve",
            goals="Private goals",
            transitioned_at=NOW,
        )
        self.child = service.create_profile(
            self.parent,
            {
                "display_name": "Private Child",
                "birth_date": date(2011, 10, 27),
                "discipline": "barebow",
            },
            child=True,
            declaration=True,
        )

    def user(self, name, *roles, verified=True):
        user = get_user_model().objects.create_user(
            username=name, email=f"{name}@example.test", password="test-pass"
        )
        EmailAddress.objects.create(
            user=user, email=user.email, verified=verified, primary=True
        )
        for role in roles:
            UserRole.objects.create(user=user, role=role)
        return user

    def version(self, athlete):
        athlete.refresh_from_db()
        return athlete.version

    def invite(self, kind="coach", athlete=None, sender=None, recipient=None):
        athlete = athlete or self.adult
        sender = sender or self.owner
        recipient = recipient or self.coach
        return service.invite(
            sender, athlete.pk, kind, recipient.email.upper(), self.version(athlete)
        )

    def link_coach(self, athlete=None, sender=None):
        athlete = athlete or self.adult
        _, token = self.invite(athlete=athlete, sender=sender)
        service.accept(self.coach, token)
        return CoachRelationship.objects.get(athlete=athlete, coach=self.coach)

    def test_profiles_independent_multiple_children_and_all_roles(self):
        second = service.create_profile(
            self.parent,
            {
                "display_name": "Second child",
                "birth_date": date(2020, 2, 1),
                "discipline": "compound",
            },
            child=True,
            declaration=True,
        )
        own = service.create_profile(
            self.parent,
            {
                "display_name": "Parent as athlete",
                "birth_date": date(1980, 1, 1),
                "discipline": "recurve",
            },
        )
        self.assertIsNone(self.child.account_id)
        self.assertEqual(
            set(accessible_athletes(self.parent).values_list("pk", flat=True)),
            {self.child.pk, second.pk, own.pk},
        )
        self.assertEqual(self.parent.role_assignments.count(), 3)
        self.assertTrue(can(self.parent, second, "edit_profile"))
        self.assertFalse(own.parent_review_required)
        self.assertFalse(RelationshipNotice.objects.filter(athlete=own).exists())

    def test_guardian_declaration_and_own_age_requirements(self):
        data = {
            "display_name": "No consent",
            "birth_date": date(2013, 1, 1),
            "discipline": "barebow",
        }
        count = AthleteProfile.objects.count()
        with self.assertRaises(ValidationError):
            service.create_profile(self.parent, data, child=True)
        with self.assertRaises(ValidationError):
            service.create_profile(self.owner, data)
        with self.assertRaises(PermissionDenied):
            service.create_profile(self.coach, data, child=True, declaration=True)
        self.assertEqual(AthleteProfile.objects.count(), count)

    def test_role_and_admin_status_never_grant_unrelated_access(self):
        self.stranger.is_staff = self.stranger.is_superuser = True
        self.stranger.save()
        for operation in OPERATIONS:
            self.assertFalse(can(self.stranger, self.adult, operation), operation)
            self.assertFalse(can(self.stranger, self.child, operation), operation)
        self.assertFalse(accessible_athletes(self.stranger).exists())
        self.assertFalse(can(self.owner, self.adult, "invented_operation"))

    def test_parent_permissions_below_16(self):
        for operation in OPERATIONS:
            self.assertTrue(can(self.parent, self.child, operation), operation)
        self.assertFalse(can(self.coach, self.child, "view"))

    def test_private_coach_invitation_default_view_plan_grant_never_scoring(self):
        invitation, token = self.invite()
        self.assertFalse(can(self.coach, self.adult, "view"))
        self.assertNotEqual(invitation.token_digest, token)
        self.assertEqual(
            invitation.expires_at - invitation.created_at, timedelta(days=7)
        )
        service.accept(self.coach, token)
        link = CoachRelationship.objects.get(athlete=self.adult, coach=self.coach)
        self.assertTrue(can(self.coach, self.adult, "view"))
        for operation in OPERATIONS - {"view"}:
            self.assertFalse(can(self.coach, self.adult, operation), operation)
        service.set_grant(
            self.owner,
            self.adult.pk,
            "coach",
            link.pk,
            "edit",
            self.version(self.adult),
        )
        self.assertTrue(can(self.coach, self.adult, "edit_plan"))
        for operation in {
            "log_scores",
            "edit_profile",
            "manage_grants",
            "activate_plan",
            "export",
            "close",
        }:
            self.assertFalse(can(self.coach, self.adult, operation), operation)

    def test_forwarded_unverified_expired_replayed_and_revoked_invitations(self):
        invitation, token = self.invite()
        for recipient in [self.stranger, self.coach]:
            if recipient == self.coach:
                EmailAddress.objects.filter(user=recipient).update(verified=False)
            with self.assertRaises(PermissionDenied):
                service.accept(recipient, token)
            self.assertFalse(CoachRelationship.objects.exists())
        EmailAddress.objects.filter(user=self.coach).update(verified=True)
        RelationshipInvitation.objects.filter(pk=invitation.pk).update(expires_at=NOW)
        with self.assertRaises(PermissionDenied):
            service.accept(self.coach, token)
        invitation2, token2 = self.invite()
        service.revoke_invitation(
            self.owner, self.adult.pk, invitation2.pk, self.version(self.adult)
        )
        with self.assertRaises(PermissionDenied):
            service.accept(self.coach, token2)
        _, token3 = self.invite()
        service.accept(self.coach, token3)
        with self.assertRaises(PermissionDenied):
            service.accept(self.coach, token3)
        with self.assertRaises(PermissionDenied):
            service.accept(self.coach, "fabricated-token")

    def test_recipient_role_does_not_replace_acceptance(self):
        _, token = self.invite(recipient=self.junior)
        with self.assertRaises(PermissionDenied):
            service.accept(self.junior, token)
        self.assertFalse(CoachRelationship.objects.exists())

    def test_revocation_denies_live_and_old_urls_and_invalidates_pending_tokens(self):
        link = self.link_coach()
        _, pending_token = self.invite()
        service.set_grant(
            self.owner,
            self.adult.pk,
            "coach",
            link.pk,
            "none",
            self.version(self.adult),
        )
        self.assertFalse(can(self.coach, self.adult, "view"))
        self.client.force_login(self.coach)
        self.assertEqual(
            self.client.get(
                reverse("athlete-detail", args=[self.adult.pk])
            ).status_code,
            404,
        )
        with self.assertRaises(PermissionDenied):
            service.accept(self.coach, pending_token)
        with self.assertRaises(ValidationError):
            service.set_grant(
                self.owner,
                self.adult.pk,
                "coach",
                link.pk,
                "edit",
                self.version(self.adult),
            )
        # Only a fresh private invitation can restart an ended relationship, view-only.
        _, fresh = self.invite()
        service.accept(self.coach, fresh)
        link.refresh_from_db()
        self.assertIsNone(link.revoked_at)
        self.assertFalse(link.plan_edit)

    def test_coach_can_end_own_relationship_but_cannot_escalate_or_end_others(self):
        link = self.link_coach()
        with self.assertRaises(PermissionDenied):
            service.set_grant(
                self.coach,
                self.adult.pk,
                "coach",
                link.pk,
                "edit",
                self.version(self.adult),
            )
        with self.assertRaises(PermissionDenied):
            service.set_grant(
                self.stranger,
                self.adult.pk,
                "coach",
                link.pk,
                "none",
                self.version(self.adult),
            )
        service.set_grant(
            self.coach,
            self.adult.pk,
            "coach",
            link.pk,
            "none",
            self.version(self.adult),
        )
        self.assertFalse(can(self.coach, self.adult, "view"))

    def test_14_boundary_and_stable_junior_claim(self):
        AthleteProfile.objects.filter(pk=self.child.pk).update(
            birth_date=date(2012, 10, 27)
        )
        self.child.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            self.invite("claim", self.child, self.parent, self.junior)
        with patch(
            "django.utils.timezone.now",
            return_value=datetime(2026, 10, 27, 0, tzinfo=dt_timezone.utc),
        ):
            _, token = self.invite("claim", self.child, self.parent, self.junior)
            claimed = service.accept(self.junior, token)
            self.assertEqual(claimed.pk, self.child.pk)
            self.assertEqual(claimed.account_id, self.junior.pk)
            self.assertTrue(can(self.junior, claimed, "view"))
            for operation in OPERATIONS - {"view"}:
                self.assertFalse(can(self.junior, claimed, operation), operation)
            with self.assertRaises(PermissionDenied):
                service.create_profile(
                    self.junior,
                    {
                        "display_name": "Bypass",
                        "birth_date": date(2000, 1, 1),
                        "discipline": "recurve",
                    },
                )

    def test_existing_login_cannot_claim_another_profile(self):
        _, token = self.invite("claim", self.child, self.parent, self.owner)
        with self.assertRaises(PermissionDenied):
            service.accept(self.owner, token)
        self.child.refresh_from_db()
        self.assertIsNone(self.child.account_id)

    def test_local_midnight_16_transition_without_scheduler(self):
        AthleteProfile.objects.filter(pk=self.child.pk).update(
            birth_date=date(2010, 10, 27), timezone="Pacific/Auckland"
        )
        self.child.refresh_from_db()
        before = datetime(2026, 10, 26, 10, 59, tzinfo=dt_timezone.utc)
        birthday = before + timedelta(minutes=1)
        with patch("django.utils.timezone.now", return_value=before):
            self.assertEqual(self.child.age(), 15)
            self.assertTrue(can(self.parent, self.child, "edit_profile"))
        with patch("django.utils.timezone.now", return_value=birthday):
            self.assertEqual(self.child.age(), 16)
            self.assertTrue(can(self.parent, self.child, "view"))
            for operation in OPERATIONS - {"view"}:
                self.assertFalse(can(self.parent, self.child, operation), operation)
            # Transition persists view-only grants and notifications exactly once.
            service.transition(self.child.pk)
            service.transition(self.child.pk)
            link = GuardianLink.objects.get(athlete=self.child, parent=self.parent)
            self.assertEqual(link.access, "view")
            self.assertEqual(
                RelationshipNotice.objects.filter(athlete=self.child).count(), 1
            )
            self.assertEqual(
                RelationshipAudit.objects.filter(
                    athlete=self.child, operation="age_16_transition"
                ).count(),
                1,
            )

    def test_16_claim_parent_chooser_editing_and_revocation(self):
        AthleteProfile.objects.filter(pk=self.child.pk).update(
            birth_date=date(2010, 10, 26)
        )
        service.transition(self.child.pk)
        _, token = self.invite("claim", self.child, self.parent, self.junior)
        claimed = service.accept(self.junior, token)
        link = GuardianLink.objects.get(athlete=self.child, parent=self.parent)
        self.assertTrue(claimed.parent_review_required)
        self.assertTrue(can(self.junior, claimed, "edit_profile"))
        service.set_grant(
            self.junior, claimed.pk, "parent", link.pk, "edit", self.version(claimed)
        )
        self.assertTrue(can(self.parent, claimed, "log_scores"))
        for operation in {"export", "close", "manage_grants"}:
            self.assertFalse(can(self.parent, claimed, operation), operation)
        service.confirm_parent_review(self.junior, claimed.pk, self.version(claimed))
        claimed.refresh_from_db()
        self.assertFalse(claimed.parent_review_required)
        service.set_grant(
            self.junior, claimed.pk, "parent", link.pk, "none", self.version(claimed)
        )
        service.transition(claimed.pk)
        self.assertFalse(can(self.parent, claimed, "view"))
        link.refresh_from_db()
        self.assertIsNotNone(link.revoked_at)

    def test_revoked_parent_never_restored_at_16(self):
        second = self.user("secondparent", "parent")
        GuardianLink.objects.create(
            athlete=self.child, parent=second, managing=True, declared_at=NOW
        )
        link = self.child.guardians.get(parent=self.parent)
        service.set_grant(
            self.parent,
            self.child.pk,
            "parent",
            link.pk,
            "none",
            self.version(self.child),
        )
        AthleteProfile.objects.filter(pk=self.child.pk).update(
            birth_date=date(2010, 1, 1)
        )
        service.transition(self.child.pk)
        self.child.refresh_from_db()
        self.assertFalse(can(self.parent, self.child, "view"))
        self.assertFalse(
            RelationshipNotice.objects.filter(
                athlete=self.child, recipient=self.parent
            ).exists()
        )

    def test_last_managing_parent_cannot_orphan_child(self):
        link = self.child.guardians.get(parent=self.parent)
        for access in ["view", "none"]:
            with self.assertRaises(ValidationError):
                service.set_grant(
                    self.parent,
                    self.child.pk,
                    "parent",
                    link.pk,
                    access,
                    self.version(self.child),
                )
        link.refresh_from_db()
        self.assertEqual(link.access, "edit")
        self.assertIsNone(link.revoked_at)

    def test_guardian_acceptance_declaration_and_adult_parent_view_default(self):
        recipient = self.user("parent2", "parent")
        _, token = self.invite("parent", self.child, self.parent, recipient)
        with self.assertRaises(PermissionDenied):
            service.accept(recipient, token)
        service.accept(recipient, token, declaration=True)
        self.assertTrue(can(recipient, self.child, "edit_profile"))
        _, token = self.invite("parent", recipient=self.parent)
        service.accept(self.parent, token)
        self.assertTrue(can(self.parent, self.adult, "view"))
        self.assertFalse(can(self.parent, self.adult, "edit_profile"))

    def test_parent_sent_coach_invite_fails_after_16_or_parent_revocation(self):
        invitation, token = self.invite("coach", self.child, self.parent, self.coach)
        AthleteProfile.objects.filter(pk=self.child.pk).update(
            birth_date=date(2010, 1, 1)
        )
        with self.assertRaises(PermissionDenied):
            service.accept(self.coach, token)
        self.assertFalse(CoachRelationship.objects.exists())

    def test_closed_profiles_and_inactive_accounts_deny_access_and_acceptance(self):
        link = self.link_coach()
        _, token = self.invite(recipient=self.stranger)
        AthleteProfile.objects.filter(pk=self.adult.pk).update(closed_at=NOW)
        self.adult.refresh_from_db()
        for user in [self.owner, self.coach, self.stranger]:
            for operation in OPERATIONS:
                self.assertFalse(can(user, self.adult, operation))
        with self.assertRaises(PermissionDenied):
            service.accept(self.stranger, token)
        with self.assertRaises(PermissionDenied):
            service.set_grant(
                self.coach,
                self.adult.pk,
                "coach",
                link.pk,
                "none",
                self.version(self.adult),
            )
        self.parent.is_active = False
        self.parent.save()
        self.assertFalse(can(self.parent, self.child, "view"))

    def test_profile_validation_birth_timezone_and_no_age_tampering(self):
        for data in [
            {"birth_date": date(2010, 1, 1)},
            {"timezone": "UTC"},
            {"account_id": self.stranger.pk},
        ]:
            with self.assertRaises(ValidationError):
                service.update_profile(
                    self.owner, self.adult.pk, data, self.version(self.adult)
                )
        for birth, zone in [
            (date(2030, 1, 1), "UTC"),
            (date(2000, 1, 1), "invalid/timezone"),
        ]:
            athlete = AthleteProfile(
                display_name="Invalid",
                birth_date=birth,
                timezone=zone,
                discipline="barebow",
            )
            with self.assertRaises(ValidationError):
                athlete.full_clean()

    def test_conflicts_and_permission_failures_do_not_write(self):
        version = self.version(self.adult)
        service.update_profile(
            self.owner, self.adult.pk, {"goals": "New goals"}, version
        )
        count = RelationshipAudit.objects.count()
        with self.assertRaises(service.Conflict):
            service.update_profile(
                self.owner, self.adult.pk, {"goals": "Stale goals"}, version
            )
        with self.assertRaises(PermissionDenied):
            service.update_profile(
                self.stranger,
                self.adult.pk,
                {"goals": "Intrusion"},
                self.version(self.adult),
            )
        self.adult.refresh_from_db()
        self.assertEqual(self.adult.goals, "New goals")
        self.assertEqual(RelationshipAudit.objects.count(), count)

    def test_coach_pages_exclude_sensitive_fields_and_other_connections(self):
        self.link_coach()
        GuardianLink.objects.create(
            athlete=self.adult, parent=self.parent, access="view"
        )
        self.client.force_login(self.coach)
        response = self.client.get(reverse("athlete-detail", args=[self.adult.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Private goals")
        for private in [
            "birth_date",
            "2000-01-01",
            self.owner.email,
            self.parent.email,
        ]:
            self.assertNotContains(response, private)
        self.assertEqual(
            set(response.context["athlete"]),
            {"id", "display_name", "discipline", "goals", "availability", "version"},
        )
        self.assertEqual(len(response.context["guardians"]), 0)
        self.assertNotIn("invitations", response.context)

    def test_hidden_and_junior_profiles_are_not_discoverable_by_unrelated_roles(self):
        AthleteProfile.objects.filter(pk=self.adult.pk).update(hidden=True)
        self.client.force_login(self.stranger)
        response = self.client.get(reverse("athletes"))
        self.assertNotContains(response, "Private Adult")
        self.assertNotContains(response, "Private Child")
        for athlete in [self.adult, self.child]:
            self.assertEqual(
                self.client.get(
                    reverse("athlete-detail", args=[athlete.pk])
                ).status_code,
                404,
            )

    def test_direct_identifier_write_and_mismatched_relationship_target(self):
        link = self.link_coach()
        self.client.force_login(self.stranger)
        before = self.version(self.adult)
        endpoints = [
            (
                "athlete-detail",
                [self.adult.pk],
                {"goals": "Intrusion", "version": before},
            ),
            (
                "invitation-create",
                [self.adult.pk],
                {"kind": "coach", "email": self.stranger.email, "version": before},
            ),
            (
                "grant-update",
                [self.adult.pk, "coach", link.pk],
                {"access": "edit", "version": -1},
            ),
        ]
        for name, args, data in endpoints:
            self.assertEqual(
                self.client.post(reverse(name, args=args), data).status_code, 404
            )
        self.assertEqual(self.version(self.adult), before)
        self.client.force_login(self.parent)
        self.assertEqual(
            self.client.post(
                reverse("grant-update", args=[self.child.pk, "coach", link.pk]),
                {"access": "edit", "version": self.version(self.child)},
            ).status_code,
            404,
        )

    def test_http_invitation_flow_get_never_accepts_and_token_only_shown_once(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("invitation-create", args=[self.adult.pk]),
            {
                "kind": "coach",
                "email": self.coach.email,
                "version": self.version(self.adult),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        url = response.context["invitation_url"]
        path = "/" + url.split("/", 3)[3]
        self.client.force_login(self.stranger)
        self.assertNotContains(self.client.get(path), "Private Adult")
        self.assertEqual(self.client.post(path).status_code, 404)
        self.client.force_login(self.coach)
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertFalse(CoachRelationship.objects.exists())
        self.assertEqual(self.client.post(path).status_code, 302)
        self.assertEqual(self.client.post(path).status_code, 404)

    def test_creation_controls_follow_saved_roles_and_own_profile(self):
        user = self.user("archer-only", "archer")
        self.client.force_login(user)
        response = self.client.get(reverse("athletes"))
        self.assertContains(response, 'name="display_name"')
        self.assertNotContains(response, 'name="child"')
        self.assertNotContains(response, 'name="declaration"')
        self.client.post(reverse("account-profile"), {"roles": ["parent"]})
        response = self.client.get(reverse("athletes"))
        self.assertContains(response, 'name="child" value="on"')
        self.assertContains(response, 'name="declaration"')
        self.client.force_login(self.owner)
        response = self.client.get(reverse("athletes"))
        self.assertContains(response, self.adult.display_name)
        self.assertNotContains(response, 'name="display_name"')

    def test_archer_only_cannot_create_child_or_remove_unrelated_guardian(self):
        self.client.force_login(self.owner)
        count = AthleteProfile.objects.count()
        response = self.client.post(reverse("athletes"), {
            "display_name": "Denied child", "birth_date": "2020-01-01",
            "timezone": "Europe/Dublin", "discipline": "recurve",
            "child": "on", "declaration": "on",
        })
        self.assertContains(response, "Unable to create this profile.")
        self.assertEqual(AthleteProfile.objects.count(), count)
        link = GuardianLink.objects.get(athlete=self.child, parent=self.parent)
        response = self.client.post(reverse("grant-update", args=[
            self.child.pk, "parent", link.pk,
        ]), {"access": "none", "version": self.version(self.child)})
        self.assertEqual(response.status_code, 404)
        link.refresh_from_db()
        self.assertIsNone(link.revoked_at)

    def test_deselecting_parent_preserves_explicit_link_and_authorized_removal(self):
        GuardianLink.objects.create(
            athlete=self.child, parent=self.stranger, managing=True, declared_at=NOW,
        )
        self.client.force_login(self.parent)
        self.client.post(reverse("account-profile"), {"roles": ["archer"]})
        self.assertEqual(list(self.parent.role_assignments.values_list("role", flat=True)), ["archer"])
        self.assertTrue(can(self.parent, self.child, "edit_profile"))
        response = self.client.get(reverse("athletes"))
        self.assertContains(response, self.child.display_name)
        self.assertNotContains(response, 'name="child"')
        link = GuardianLink.objects.get(athlete=self.child, parent=self.parent)
        response = self.client.post(reverse("grant-update", args=[
            self.child.pk, "parent", link.pk,
        ]), {"access": "none", "version": self.version(self.child)})
        self.assertRedirects(response, reverse("athletes"))
        link.refresh_from_db()
        self.assertIsNotNone(link.revoked_at)
        self.assertFalse(can(self.parent, self.child, "view"))

    def test_http_create_missing_role_preserves_form_then_succeeds_after_role_saved(self):
        user = self.user("new-account")
        self.client.force_login(user)
        for child, role in [(False, "archer"), (True, "parent")]:
            with self.subTest(child=child):
                UserRole.objects.filter(user=user).delete()
                data = {
                    "display_name": "New profile",
                    "birth_date": "2015-02-01" if child else "2000-01-01",
                    "timezone": "Europe/Dublin",
                    "discipline": "recurve",
                }
                if child:
                    data.update(child="on", declaration="on")
                count = AthleteProfile.objects.count()
                response = self.client.post(reverse("athletes"), data)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Unable to create this profile.")
                self.assertContains(response, reverse("account-profile"))
                self.assertEqual(response.context["form"].data["display_name"], "New profile")
                self.assertTrue(response.context["form"].non_field_errors())
                self.assertEqual(AthleteProfile.objects.count(), count)
                self.client.post(reverse("account-profile"), {"roles": [role]})
                response = self.client.post(reverse("athletes"), data)
                athlete = AthleteProfile.objects.get(display_name="New profile", birth_date=data["birth_date"])
                self.assertRedirects(response, reverse("athlete-detail", args=[athlete.pk]))
                if child:
                    self.assertIsNone(athlete.account_id)
                    self.assertTrue(GuardianLink.objects.filter(athlete=athlete, parent=user, managing=True).exists())
                else:
                    self.assertEqual(athlete.account_id, user.pk)

    def test_http_create_ineligible_account_still_denied(self):
        for closed in [False, True]:
            with self.subTest(closed=closed):
                user = self.user(f"restricted-{closed}", "parent")
                AthleteProfile.objects.create(
                    account=user, display_name="Restricted", discipline="recurve",
                    birth_date=date(2000 if closed else 2011, 1, 1),
                    closed_at=NOW if closed else None,
                )
                self.client.force_login(user)
                count = AthleteProfile.objects.count()
                response = self.client.post(reverse("athletes"), {
                    "display_name": "Denied child", "birth_date": "2020-01-01",
                    "timezone": "Europe/Dublin", "discipline": "recurve",
                    "child": "on", "declaration": "on",
                })
                self.assertContains(response, "Unable to create this profile.")
                self.assertEqual(AthleteProfile.objects.count(), count)

    def test_http_multi_child_selector_and_profile_edit(self):
        self.client.force_login(self.parent)
        response = self.client.post(
            reverse("athletes"),
            {
                "display_name": "Second Child",
                "birth_date": "2015-02-01",
                "timezone": "Europe/Dublin",
                "discipline": "compound",
                "child": "on",
                "declaration": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse("athletes"))
        self.assertContains(response, "Private Child")
        self.assertContains(response, "Second Child")
        response = self.client.post(
            reverse("athlete-detail", args=[self.child.pk]),
            {
                "display_name": "Updated Child",
                "discipline": "barebow",
                "goals": "Practice",
                "version": self.version(self.child),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.child.refresh_from_db()
        self.assertEqual(self.child.display_name, "Updated Child")

    def test_login_csrf_and_post_only_relationship_actions(self):
        invitation, token = self.invite()
        url = reverse("invitation-create", args=[self.adult.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(url, {"kind": "coach"}).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(
            self.client.get(
                reverse("invitation-revoke", args=[self.adult.pk, invitation.pk])
            ).status_code,
            405,
        )
        self.assertFalse(CoachRelationship.objects.exists())

    def test_age_transition_command_is_idempotent(self):
        AthleteProfile.objects.filter(pk=self.child.pk).update(
            birth_date=date(2010, 1, 1)
        )
        call_command("process_age_transitions", verbosity=0)
        count = RelationshipNotice.objects.count()
        call_command("process_age_transitions", verbosity=0)
        self.assertEqual(RelationshipNotice.objects.count(), count)
        self.assertEqual(self.child.guardians.get(parent=self.parent).access, "view")

    def test_google_provider_and_callback_remain_registered(self):
        self.assertEqual(
            resolve("/accounts/google/login/callback/").url_name, "google_callback"
        )
        response = self.client.get(reverse("account_login"))
        self.assertContains(response, reverse("google_login"))
        # Google sign-in remains the account entry point; local password signup stays disabled.
        self.assertEqual(self.client.get("/accounts/signup/").status_code, 404)

    def test_next_sign_in_redirects_16_year_old_to_parent_review(self):
        AthleteProfile.objects.filter(pk=self.child.pk).update(
            account=self.junior, birth_date=date(2010, 10, 26)
        )
        self.client.force_login(self.junior)
        response = self.client.get(reverse("account-profile"))
        self.assertRedirects(response, reverse("athlete-detail", args=[self.child.pk]))
        detail = self.client.get(response.url)
        self.assertContains(detail, "Review each parent")
        response = self.client.post(
            reverse("parent-review", args=[self.child.pk]),
            {"version": self.version(self.child)},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse("account-profile")).status_code, 200)
        self.client.force_login(self.parent)
        self.assertContains(
            self.client.get(reverse("account-profile")), "has turned 16"
        )

    def test_parent_can_invite_coach_for_child_but_junior_cannot_manage_grants(self):
        link = self.link_coach(self.child, self.parent)
        AthleteProfile.objects.filter(pk=self.child.pk).update(account=self.junior)
        self.child.refresh_from_db()
        self.assertTrue(can(self.coach, self.child, "view"))
        service.set_grant(
            self.parent,
            self.child.pk,
            "coach",
            link.pk,
            "edit",
            self.version(self.child),
        )
        self.assertTrue(can(self.coach, self.child, "edit_plan"))
        self.assertFalse(can(self.coach, self.child, "log_scores"))
        with self.assertRaises(PermissionDenied):
            service.set_grant(
                self.junior,
                self.child.pk,
                "coach",
                link.pk,
                "none",
                self.version(self.child),
            )
        self.client.force_login(self.junior)
        self.assertEqual(
            self.client.post(
                reverse("invitation-create", args=[self.child.pk]),
                {
                    "kind": "coach",
                    "email": self.stranger.email,
                    "version": self.version(self.child),
                },
            ).status_code,
            404,
        )

    def test_revoking_parent_also_revokes_their_pending_child_invites(self):
        recipient = self.user("parent2", "parent")
        _, parent_token = self.invite("parent", self.child, self.parent, recipient)
        service.accept(recipient, parent_token, declaration=True)
        invitation, token = self.invite("coach", self.child, self.parent, self.coach)
        parent_link = self.child.guardians.get(parent=self.parent)
        service.set_grant(
            recipient,
            self.child.pk,
            "parent",
            parent_link.pk,
            "none",
            self.version(self.child),
        )
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.revoked_at)
        with self.assertRaises(PermissionDenied):
            service.accept(self.coach, token)

    def test_stale_grant_and_invitation_forms_cannot_overwrite_permissions(self):
        link = self.link_coach()
        old = self.version(self.adult)
        service.set_grant(self.owner, self.adult.pk, "coach", link.pk, "edit", old)
        with self.assertRaises(service.Conflict):
            service.set_grant(self.owner, self.adult.pk, "coach", link.pk, "none", old)
        with self.assertRaises(service.Conflict):
            self.client.force_login(self.owner)
            service.invite(self.owner, self.adult.pk, "coach", self.stranger.email, old)
        link.refresh_from_db()
        self.assertTrue(link.plan_edit)
        self.assertIsNone(link.revoked_at)

    def test_http_unknown_birth_date_update_and_invalid_create_are_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("athlete-detail", args=[self.adult.pk]),
            {"birth_date": "2010-01-01", "version": self.version(self.adult)},
        )
        self.assertEqual(response.status_code, 400)
        self.adult.refresh_from_db()
        self.assertEqual(self.adult.birth_date, date(2000, 1, 1))
        response = self.client.post(
            reverse("athletes"),
            {
                "display_name": "Bad date",
                "birth_date": "tomorrow",
                "timezone": "No/Such",
                "discipline": "recurve",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

    def test_closed_linked_account_and_under_14_login_cannot_read_any_athlete(self):
        AthleteProfile.objects.filter(pk=self.child.pk).update(
            account=self.junior, birth_date=date(2014, 1, 1)
        )
        self.child.refresh_from_db()
        self.assertFalse(can(self.junior, self.child, "view"))
        self.assertFalse(accessible_athletes(self.junior).exists())
        AthleteProfile.objects.filter(pk=self.child.pk).update(
            birth_date=date(2011, 1, 1), closed_at=NOW
        )
        self.assertFalse(accessible_athletes(self.junior).exists())

    def test_multiple_coaches_keep_separate_grants_and_no_cross_profile_access(self):
        first = self.link_coach()
        _, token = self.invite(recipient=self.stranger)
        service.accept(self.stranger, token)
        service.set_grant(
            self.owner,
            self.adult.pk,
            "coach",
            first.pk,
            "edit",
            self.version(self.adult),
        )
        self.assertTrue(can(self.coach, self.adult, "edit_plan"))
        self.assertTrue(can(self.stranger, self.adult, "view"))
        self.assertFalse(can(self.stranger, self.adult, "edit_plan"))
        self.assertFalse(can(self.stranger, self.child, "view"))

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "APP": {
                    "client_id": "synthetic-client",
                    "secret": "synthetic-secret",
                    "key": "",
                },
                "SCOPE": ["profile", "email"],
            }
        }
    )
    def test_google_callback_logs_into_existing_stable_account(self):
        SocialAccount.objects.create(
            user=self.owner, provider="google", uid="synthetic-google-id"
        )
        response = self.client.post(reverse("google_login"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).hostname, "accounts.google.com")
        state = parse_qs(urlsplit(response.url).query)["state"][0]
        with (
            patch(
                "allauth.socialaccount.providers.google.views.GoogleOAuth2Adapter.get_access_token_data",
                return_value={
                    "access_token": "synthetic-token",
                    "token_type": "Bearer",
                },
            ),
            patch(
                "allauth.socialaccount.providers.google.views.GoogleOAuth2Adapter._fetch_user_info",
                return_value={
                    "id": "synthetic-google-id",
                    "email": self.owner.email,
                    "verified_email": True,
                    "name": "Synthetic Archer",
                },
            ),
        ):
            response = self.client.get(
                reverse("google_callback"), {"code": "synthetic-code", "state": state}
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.owner.pk)
        self.adult.refresh_from_db()
        self.assertEqual(self.adult.account_id, self.owner.pk)
        self.assertEqual(self.owner.socialaccount_set.count(), 1)

    def test_workflow_pages_and_user_graphics(self):
        athlete_routes = [
            "athlete-today",
            "athlete-plans",
            "athlete-score",
            "athlete-progress",
            "athlete-equipment",
            "athlete-export",
        ]
        workspace_routes = [
            "athlete-discovery",
            "coach-contributions",
            "manager-queue",
            "admin-ops",
        ]
        home_response = self.client.get(reverse("home"))
        self.assertEqual(home_response.status_code, 200)
        for graphic in [
            "accounts/target.svg",
            "accounts/role-archer.svg",
            "accounts/role-parent.svg",
            "accounts/role-coach.svg",
            "accounts/workflow-banner.svg",
        ]:
            self.assertContains(home_response, graphic)

        for route in workspace_routes:
            self.assertEqual(self.client.get(reverse(route)).status_code, 302)
        for route in athlete_routes:
            self.assertEqual(
                self.client.get(reverse(route, args=[self.adult.pk])).status_code, 302
            )

        self.client.force_login(self.stranger)
        for route in athlete_routes:
            self.assertEqual(
                self.client.get(reverse(route, args=[self.adult.pk])).status_code, 404
            )
        for route in workspace_routes:
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Page to be implemented")
            self.assertNotContains(response, "Private Adult")
            self.assertNotContains(response, "Private Child")

        link = self.link_coach()
        self.client.force_login(self.coach)
        for route in athlete_routes:
            response = self.client.get(reverse(route, args=[self.adult.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Page to be implemented")
            self.assertContains(response, self.adult.display_name)
            for private in ["birth_date", "2000-01-01", self.owner.email]:
                self.assertNotContains(response, private)

        service.set_grant(
            self.owner, self.adult.pk, "coach", link.pk, "none", self.version(self.adult)
        )
        for route in athlete_routes:
            self.assertEqual(
                self.client.get(reverse(route, args=[self.adult.pk])).status_code, 404
            )
