"""M2 permissions, lifecycle and HTTP coverage; all identities are synthetic."""
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, close_old_connections
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import AthleteProfile, GuardianLink, CoachRelationship
from accounts.permissions import can
from . import memberships as service, services
from .models import (Club, ClubMembership, ClubRoleAssignment, ClubMembershipAction,
                     AthleteHomeClub, AthleteHomeClubHistory, ClubAuditEvent)
from .tests import login_with_mfa


class Fixtures:
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", email="admin@example.test")
        self.member = User.objects.create_user(username="member", email="member@example.test")
        self.other = User.objects.create_user(username="other", email="other@example.test")
        self.parent = User.objects.create_user(username="parent", email="parent@example.test")
        for user in (self.admin, self.member, self.other, self.parent):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.club = Club.objects.create(name="Public test", slug="public-test", country="Ireland",
            visibility="public", status="active", verified_at=timezone.now())
        self.private = Club.objects.create(name="Hidden test", slug="hidden-test", country="Ireland",
            visibility="private", status="active", verified_at=timezone.now())
        for club in (self.club, self.private):
            membership = ClubMembership.objects.create(club=club, user=self.admin)
            ClubRoleAssignment.objects.create(membership=membership, role="admin", accepted_at=timezone.now())
        self.athlete = AthleteProfile.objects.create(account=self.member, display_name="Adult member",
            birth_date=date(1990, 1, 1), discipline="recurve")
        self.child = AthleteProfile.objects.create(display_name="Junior synthetic", birth_date=date(2018, 1, 1), discipline="barebow")
        self.guardian = GuardianLink.objects.create(parent=self.parent, athlete=self.child, managing=True, access="edit")

    def join(self, actor=None, club=None, athlete=None):
        action = service.request_join(actor or self.member, (club or self.club).pk, athlete.pk if athlete else None)
        return service.decide_join(self.admin, action.club_id, action.pk, True, action.version).membership


@override_settings(CLUBS_ENABLED=True, CLUB_MEMBERSHIPS_ENABLED=True)
class MembershipTests(Fixtures, TestCase):
    def test_multiclub_join_invite_and_no_automatic_home(self):
        first = self.join(athlete=self.athlete)
        action, token = service.invite(self.admin, self.private.pk, self.member.email)
        second = service.accept_invite(self.member, action.pk, token, athlete_id=self.athlete.pk).membership
        self.assertNotEqual(first.club_id, second.club_id)
        self.assertEqual(ClubMembership.objects.filter(user=self.member, active=True).count(), 2)
        self.assertFalse(AthleteHomeClub.objects.exists())
        self.assertFalse(services.can_manage(self.member, self.club))
        self.assertFalse(can(self.admin, self.athlete, "view"))

    def test_guardian_child_has_no_login_or_parent_membership(self):
        member = self.join(self.parent, athlete=self.child)
        self.assertIsNone(member.user_id)
        self.assertEqual(member.athlete, self.child)
        self.assertFalse(ClubMembership.objects.filter(user=self.parent).exists())
        home = service.select_home(self.parent, self.child.pk, self.club.pk, 0)
        self.assertEqual(home.club, self.club)
        self.assertIsNone(self.child.account_id)

    def test_guardian_rechecked_before_join_decision_and_invite_acceptance(self):
        action = service.request_join(self.parent, self.club.pk, self.child.pk)
        self.child.birth_date = date(2000, 1, 1)
        self.child.save()
        with self.assertRaises(ValidationError):
            service.decide_join(self.admin, self.club.pk, action.pk, True, action.version)
        invite, token = service.invite(self.admin, self.private.pk, self.parent.email)
        with self.assertRaises(Http404):
            service.accept_invite(self.parent, invite.pk, token, athlete_id=self.child.pk)
        self.assertFalse(ClubMembership.objects.filter(athlete=self.child).exists())

    def test_coach_or_adult_guardian_edit_grant_cannot_manage_membership(self):
        self.guardian.athlete = self.athlete
        self.guardian.adult_grant = True
        self.guardian.save()
        CoachRelationship.objects.create(athlete=self.athlete, coach=self.other, plan_edit=True)
        for actor in (self.parent, self.other):
            with self.assertRaises(Http404):
                service.request_join(actor, self.club.pk, self.athlete.pk)

    def test_under_sixteen_account_cannot_join_or_accept_roles(self):
        self.athlete.birth_date = date(2012, 1, 1)
        self.athlete.save()
        with self.assertRaises(PermissionDenied):
            service.request_join(self.member, self.club.pk)

    def test_invite_requires_matching_verified_recipient_and_single_use(self):
        action, token = service.invite(self.admin, self.private.pk, self.member.email)
        self.assertNotEqual(token, action.token_digest)
        with self.assertRaises(Http404):
            service.accept_invite(self.other, action.pk, token)
        EmailAddress.objects.filter(user=self.member).update(verified=False)
        with self.assertRaises(Http404):
            service.accept_invite(self.member, action.pk, token)
        EmailAddress.objects.filter(user=self.member).update(verified=True)
        service.accept_invite(self.member, action.pk, token)
        with self.assertRaises(ValidationError):
            service.accept_invite(self.member, action.pk, token)

    def test_expired_revoked_and_declined_invites_cannot_join(self):
        for state in ("expired", "revoked", "declined"):
            action, token = service.invite(self.admin, self.private.pk, self.member.email)
            if state == "expired":
                action.expires_at = timezone.now() - timedelta(seconds=1)
                action.save()
            elif state == "revoked":
                service.revoke_action(self.admin, self.private.pk, action.pk, action.version)
            else:
                service.accept_invite(self.member, action.pk, token, accept=False)
            with self.assertRaises(ValidationError):
                service.accept_invite(self.member, action.pk, token)
        self.assertFalse(ClubMembership.objects.filter(user=self.member).exists())

    def test_join_closed_private_and_duplicate_rejected(self):
        with self.assertRaises(Http404):
            service.request_join(self.member, self.private.pk)
        service.set_requests(self.admin, self.club.pk, False, self.club.version)
        with self.assertRaises(ValidationError):
            service.request_join(self.member, self.club.pk)
        # Closing requests does not disable authorized invitations.
        action, token = service.invite(self.admin, self.club.pk, self.member.email)
        service.accept_invite(self.member, action.pk, token)
        self.club.refresh_from_db()
        service.set_requests(self.admin, self.club.pk, True, self.club.version)
        with self.assertRaises(ValidationError):
            service.request_join(self.member, self.club.pk)

    def test_pending_join_duplicate_reject_and_stale_decision(self):
        action = service.request_join(self.member, self.club.pk)
        with self.assertRaises(ValidationError):
            service.request_join(self.member, self.club.pk)
        with self.assertRaises(services.ClaimConflict):
            service.decide_join(self.admin, self.club.pk, action.pk, True, 100)
        service.decide_join(self.admin, self.club.pk, action.pk, False, action.version)
        self.assertFalse(ClubMembership.objects.filter(user=self.member).exists())

    def test_multiple_roles_require_acceptance_and_remain_club_scoped(self):
        member = self.join()
        for role in ("coach", "membership_manager", "admin"):
            member.refresh_from_db()
            action = service.offer_role(self.admin, self.club.pk, member.pk, role, member.version)
            self.assertFalse(member.roles.filter(role=role, revoked_at__isnull=True).exists())
            service.accept_role(self.member, action.pk, True, action.version)
        self.assertEqual(member.roles.filter(revoked_at__isnull=True).count(), 3)
        self.assertTrue(services.can_manage(self.member, self.club))
        self.assertFalse(services.can_manage(self.member, self.private))
        self.assertFalse(can(self.member, self.child, "view"))

    def test_role_offer_decline_revocation_and_issuer_loss(self):
        member = self.join()
        for behavior in ("decline", "revoke", "issuer_lost"):
            action = service.offer_role(self.admin, self.club.pk, member.pk, "coach", member.version)
            if behavior == "decline":
                service.accept_role(self.member, action.pk, False, action.version)
            elif behavior == "revoke":
                service.revoke_action(self.admin, self.club.pk, action.pk, action.version)
            else:
                ClubRoleAssignment.objects.filter(membership__club=self.club, role="admin").update(revoked_at=timezone.now())
            with self.assertRaises(ValidationError):
                service.accept_role(self.member, action.pk, True, action.version)
        self.assertFalse(member.roles.exists())

    def test_manager_can_process_members_but_cannot_assign_roles_or_remove(self):
        member = self.join()
        offer = service.offer_role(self.admin, self.club.pk, member.pk, "membership_manager", member.version)
        service.accept_role(self.member, offer.pk, True, offer.version)
        self.join(self.other)
        victim = ClubMembership.objects.get(user=self.other)
        with self.assertRaises(Http404):
            service.offer_role(self.member, self.club.pk, victim.pk, "admin", victim.version)
        with self.assertRaises(Http404):
            service.end_membership(self.member, self.club.pk, victim.pk, "removed", victim.version)
        service.invite(self.member, self.club.pk, "synthetic@example.test")
        self.assertFalse(service.has_role(self.member, self.private, {"membership_manager"}))

    def test_cross_club_action_and_role_identifiers_are_denied(self):
        member = self.join()
        with self.assertRaises(Http404):
            service.offer_role(self.admin, self.private.pk, member.pk, "admin", member.version)
        pending = service.request_join(self.other, self.club.pk)
        with self.assertRaises(Http404):
            service.decide_join(self.admin, self.private.pk, pending.pk, True, pending.version)

    def test_last_admin_protection_and_accepted_successor(self):
        admin_member = ClubMembership.objects.get(user=self.admin, club=self.club)
        role = admin_member.roles.get()
        with self.assertRaises(ValidationError):
            service.revoke_role(self.admin, self.club.pk, role.pk, admin_member.version)
        with self.assertRaises(ValidationError):
            service.end_membership(self.admin, self.club.pk, admin_member.pk, "left", admin_member.version)
        member = self.join()
        offer = service.offer_role(self.admin, self.club.pk, member.pk, "admin", member.version)
        with self.assertRaises(ValidationError):
            service.end_membership(self.admin, self.club.pk, admin_member.pk, "left", admin_member.version)
        service.accept_role(self.member, offer.pk, True, offer.version)
        service.end_membership(self.admin, self.club.pk, admin_member.pk, "left", admin_member.version)
        self.assertTrue(services.can_manage(self.member, self.club))
        self.assertFalse(services.can_manage(self.admin, self.club))

    def test_closed_successor_does_not_allow_last_admin_removal(self):
        member = self.join()
        offer = service.offer_role(self.admin, self.club.pk, member.pk, "admin", member.version)
        service.accept_role(self.member, offer.pk, True, offer.version)
        self.athlete.closed_at = timezone.now()
        self.athlete.save()
        original = ClubMembership.objects.get(user=self.admin, club=self.club)
        with self.assertRaises(ValidationError):
            service.end_membership(self.admin, self.club.pk, original.pk, "left", original.version)

    def test_explicit_home_switch_clear_and_stale_version(self):
        self.join(athlete=self.athlete)
        invite, token = service.invite(self.admin, self.private.pk, self.member.email)
        service.accept_invite(self.member, invite.pk, token, athlete_id=self.athlete.pk)
        home = service.select_home(self.member, self.athlete.pk, self.club.pk, 0)
        with self.assertRaises(services.ClaimConflict):
            service.select_home(self.member, self.athlete.pk, self.private.pk, 0)
        home = service.select_home(self.member, self.athlete.pk, self.private.pk, home.version)
        home = service.select_home(self.member, self.athlete.pk, None, home.version)
        self.assertIsNone(home.club_id)
        self.assertEqual(AthleteHomeClubHistory.objects.filter(athlete=self.athlete).count(), 3)

    def test_ending_membership_clears_home_preserves_history_other_clubs_and_athlete(self):
        first = self.join(athlete=self.athlete)
        invite, token = service.invite(self.admin, self.private.pk, self.member.email)
        second = service.accept_invite(self.member, invite.pk, token, athlete_id=self.athlete.pk).membership
        service.select_home(self.member, self.athlete.pk, self.club.pk, 0)
        service.end_membership(self.member, self.club.pk, first.pk, "left", first.version)
        self.assertIsNone(AthleteHomeClub.objects.get(athlete=self.athlete).club_id)
        self.assertEqual(AthleteHomeClubHistory.objects.filter(athlete=self.athlete).count(), 2)
        second.refresh_from_db()
        self.assertTrue(second.active)
        self.assertTrue(AthleteProfile.objects.filter(pk=self.athlete.pk).exists())

    def test_removed_members_require_explicit_new_invite_roles_not_restored(self):
        member = self.join()
        old_invite, old_token = service.invite(self.admin, self.club.pk, self.member.email)
        role = service.offer_role(self.admin, self.club.pk, member.pk, "coach", member.version)
        service.accept_role(self.member, role.pk, True, role.version)
        member.refresh_from_db()
        service.end_membership(self.admin, self.club.pk, member.pk, "removed", member.version)
        with self.assertRaises(ValidationError):
            service.accept_invite(self.member, old_invite.pk, old_token)
        with self.assertRaises(ValidationError):
            service.request_join(self.member, self.club.pk)
        invite, token = service.invite(self.admin, self.club.pk, self.member.email)
        restored = service.accept_invite(self.member, invite.pk, token).membership
        self.assertEqual(restored.pk, member.pk)
        self.assertFalse(restored.roles.filter(revoked_at__isnull=True).exists())

    def test_suspension_blocks_invite_role_and_home_and_keeps_personal_access(self):
        self.join(athlete=self.athlete)
        invite, token = service.invite(self.admin, self.club.pk, self.other.email)
        self.club.status = "suspended"
        self.club.save()
        with self.assertRaises(ValidationError):
            service.accept_invite(self.other, invite.pk, token)
        with self.assertRaises(Http404):
            service.select_home(self.member, self.athlete.pk, self.club.pk, 0)
        with self.assertRaises(Http404):
            service.invite(self.admin, self.club.pk, self.other.email)
        self.assertTrue(can(self.member, self.athlete, "view"))

    def test_audit_has_transition_codes_and_no_invite_token(self):
        invite, token = service.invite(self.admin, self.club.pk, self.member.email)
        service.accept_invite(self.member, invite.pk, token)
        events = list(ClubAuditEvent.objects.values_list("action", flat=True))
        self.assertIn("membership.invited", events)
        self.assertIn("membership.invite.accepted", events)
        self.assertNotIn(token, str(events))


@override_settings(CLUBS_ENABLED=True, CLUB_MEMBERSHIPS_ENABLED=True)
class MembershipHTTPTests(Fixtures, TestCase):
    def test_join_and_my_clubs_and_feature_gate(self):
        self.client.force_login(self.member)
        url = reverse("clubs:join", args=[self.club.pk])
        self.assertContains(self.client.get(url), "Request to join")
        self.assertEqual(self.client.post(url, {"athlete": self.athlete.pk}).status_code, 302)
        self.assertContains(self.client.get(reverse("clubs:memberships")), self.club.name)
        with self.settings(CLUB_MEMBERSHIPS_ENABLED=False):
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.get(reverse("clubs:memberships")).status_code, 404)

    def test_manager_requires_mfa_and_outsider_cannot_get_roster(self):
        url = reverse("clubs:membership-manage", args=[self.club.pk])
        self.client.force_login(self.admin)
        self.assertIn(reverse("mfa_index"), self.client.get(url).url)
        login_with_mfa(self.client, self.admin)
        self.assertContains(self.client.get(url), "Invite a member")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_manager_approve_post_and_stale_post(self):
        action = service.request_join(self.member, self.club.pk)
        login_with_mfa(self.client, self.admin)
        url = reverse("clubs:membership-manage", args=[self.club.pk])
        data = {"action": "approve", "target": action.pk, "version": action.version}
        self.assertEqual(self.client.post(url, {**data, "version": 99}).status_code, 409)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(ClubMembership.objects.filter(user=self.member, active=True).exists())

    def test_invite_form_no_email_sent_token_only_in_post_body(self):
        login_with_mfa(self.client, self.admin)
        url = reverse("clubs:invite", args=[self.private.pk])
        self.assertContains(self.client.get(url), "Recipient")
        response = self.client.post(url, {"email": self.member.email})
        self.assertContains(response, "No email has been sent")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        action = ClubMembershipAction.objects.get(kind="invite")
        accept_url = reverse("clubs:invitation", args=[action.pk])
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(accept_url), self.private.name)
        self.assertNotContains(self.client.get(accept_url), self.member.email)
        self.assertEqual(self.client.post(accept_url, {"token": "wrong", "decision": "accept"}).status_code, 404)

    def test_invitation_post_accept_and_decline(self):
        for accept in (True, False):
            actor = self.member if accept else self.other
            action, token = service.invite(self.admin, self.private.pk, actor.email)
            self.client.force_login(actor)
            response = self.client.post(reverse("clubs:invitation", args=[action.pk]), {"token": token,
                "decision": "accept" if accept else "decline"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(ClubMembership.objects.filter(user=actor, club=self.private).exists(), accept)

    def test_home_and_leave_forms(self):
        member = self.join(athlete=self.athlete)
        self.client.force_login(self.member)
        url = reverse("clubs:home-club", args=[self.athlete.pk])
        self.assertContains(self.client.get(url), self.club.name)
        self.assertEqual(self.client.post(url, {"club": self.club.pk, "version": 0}).status_code, 302)
        leave = reverse("clubs:leave", args=[member.pk])
        self.assertContains(self.client.get(leave), "Confirm leaving")
        self.assertEqual(self.client.post(leave, {"version": member.version}).status_code, 302)

    def test_role_accept_requires_mfa_and_recipient(self):
        member = self.join()
        action = service.offer_role(self.admin, self.club.pk, member.pk, "admin", member.version)
        url = reverse("clubs:role-response", args=[action.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 302)
        login_with_mfa(self.client, self.member)
        self.assertContains(self.client.get(url), "appointment")
        self.assertEqual(self.client.post(url, {"version": action.version, "decision": "accept"}).status_code, 302)
        self.assertTrue(services.can_manage(self.member, self.club))

    def test_csrf_missing_denies_join(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.member)
        self.assertEqual(client.post(reverse("clubs:join", args=[self.club.pk]), {}).status_code, 403)

    def test_invitation_acceptance_preserves_same_origin_csrf(self):
        action, token = service.invite(self.admin, self.private.pk, self.member.email)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.member)
        url = reverse("clubs:invitation", args=[action.pk])
        response = client.get(url)
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        response = client.post(url, {"token": token, "decision": "accept",
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value}, HTTP_ORIGIN="http://testserver")
        self.assertEqual(response.status_code, 302)

    def test_club_context_requires_current_manager_role(self):
        self.client.force_login(self.member)
        url = reverse("clubs:memberships")
        self.assertEqual(self.client.get(url, {"club": self.club.pk}).status_code, 404)
        self.assertEqual(self.client.get(url, {"club": "invalid"}).status_code, 404)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(url, {"club": self.club.pk}),
            reverse("clubs:membership-manage", args=[self.club.pk]), fetch_redirect_response=False)


@skipUnless(connection.vendor == "postgresql", "Requires disposable PostgreSQL row locks")
@override_settings(CLUBS_ENABLED=True, CLUB_MEMBERSHIPS_ENABLED=True)
class MembershipConcurrencyTests(Fixtures, TransactionTestCase):
    def test_two_administrators_cannot_both_leave(self):
        member = self.join()
        offer = service.offer_role(self.admin, self.club.pk, member.pk, "admin", member.version)
        service.accept_role(self.member, offer.pk, True, offer.version)
        original = ClubMembership.objects.get(club=self.club, user=self.admin)
        member.refresh_from_db()

        def leave(pair):
            close_old_connections()
            user_id, member_id, version = pair
            try:
                actor = get_user_model().objects.get(pk=user_id)
                service.end_membership(actor, self.club.pk, member_id, "left", version)
                return "left"
            except ValidationError:
                return "protected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(leave, [(self.admin.pk, original.pk, original.version), (self.member.pk, member.pk, member.version)]))
        self.assertCountEqual(results, ["left", "protected"])
        self.assertEqual(ClubRoleAssignment.objects.filter(membership__club=self.club,
            membership__active=True, role="admin", revoked_at__isnull=True).count(), 1)
