from datetime import timedelta, date
from unittest import mock
from django.core.exceptions import ValidationError
from django.http import Http404
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import CoachRelationship
from accounts.permissions import can
from .test_memberships import Fixtures
from .models import ClubRoleAssignment, ClubDataGrant, ClubAuditEvent
from . import grants, memberships, services


@override_settings(CLUBS_ENABLED=True, CLUB_MEMBERSHIPS_ENABLED=True, CLUB_DATA_SHARING_ENABLED=True)
class GrantTests(Fixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.membership = self.join(athlete=self.athlete)
        self.coach_membership = self.join(self.other)
        self.role = ClubRoleAssignment.objects.create(membership=self.coach_membership, role="coach", accepted_at=timezone.now())

    def grant(self, **changes):
        data = dict(club_id=self.club.pk, grantee_id=self.other.pk, scopes=["scoring"], purpose="Synthetic coaching",
            starts_at=timezone.now()-timedelta(minutes=1), expires_at=timezone.now()+timedelta(days=7))
        data.update(changes)
        return grants.issue(self.member, self.athlete.pk, **data)

    def test_no_implicit_access_and_category_separation(self):
        self.assertFalse(grants.allows(self.other, self.athlete, "scoring"))
        self.grant()
        self.assertTrue(grants.allows(self.other, self.athlete, "scoring"))
        for scope in ("profile", "training", "equipment", "sight_marks", "training_edit"):
            self.assertFalse(grants.allows(self.other, self.athlete, scope))
        for op in ("view", "edit_profile", "edit_plan", "log_scores", "export", "manage_grants"):
            self.assertFalse(can(self.other, self.athlete, op))
        self.assertFalse(grants.allows(self.admin, self.athlete, "scoring"))

    def test_scope_union_and_expiry_revocation(self):
        first = self.grant()
        second = self.grant(scopes=["profile"])
        self.assertTrue(grants.allows(self.other, self.athlete, "profile"))
        grants.revoke(self.member, self.athlete.pk, first.pk, first.version)
        self.assertFalse(grants.allows(self.other, self.athlete, "scoring"))
        self.assertTrue(grants.allows(self.other, self.athlete, "profile"))
        second.expires_at = timezone.now()-timedelta(seconds=1)
        second.save()
        self.assertFalse(grants.allows(self.other, self.athlete, "profile"))

    def test_future_start_and_disabled_feature_deny(self):
        self.grant(starts_at=timezone.now()+timedelta(days=1))
        self.assertFalse(grants.allows(self.other, self.athlete, "scoring"))
        with self.settings(CLUB_DATA_SHARING_ENABLED=False):
            self.assertFalse(grants.allows(self.other, self.athlete, "scoring"))
            with self.assertRaises(Http404):
                grants.owner(self.member, self.athlete.pk)

    def test_only_owner_can_issue_or_revoke(self):
        grant = self.grant()
        for actor in (self.admin, self.other, self.parent):
            with self.assertRaises(Http404):
                grants.revoke(actor, self.athlete.pk, grant.pk, grant.version)
        with self.assertRaises(services.ClaimConflict):
            grants.revoke(self.member, self.athlete.pk, grant.pk, 99)

    def test_role_grant_never_crosses_club_or_role(self):
        self.grant(grantee_id=None, role="admin")
        self.assertTrue(grants.allows(self.admin, self.athlete, "scoring"))
        self.assertFalse(grants.allows(self.other, self.athlete, "scoring"))
        ClubRoleAssignment.objects.filter(membership__user=self.admin, membership__club=self.club).update(revoked_at=timezone.now())
        self.assertFalse(grants.allows(self.admin, self.athlete, "scoring"))

    def test_exit_then_rejoin_does_not_restore_old_grants(self):
        grant = self.grant()
        memberships.end_membership(self.member, self.club.pk, self.membership.pk, "left", self.membership.version)
        grant.refresh_from_db()
        self.assertIsNotNone(grant.revoked_at)
        self.join(athlete=self.athlete)
        self.assertFalse(grants.allows(self.other, self.athlete, "scoring"))

    def test_named_coach_role_reappointment_requires_new_grant(self):
        self.grant()
        memberships.revoke_role(self.admin, self.club.pk, self.role.pk, self.coach_membership.version)
        self.assertFalse(grants.allows(self.other, self.athlete, "scoring"))
        ClubRoleAssignment.objects.create(membership=self.coach_membership, role="coach", accepted_at=timezone.now())
        self.assertFalse(grants.allows(self.other, self.athlete, "scoring"))

    def test_guardian_authority_rechecked_at_sixteen(self):
        self.join(self.parent, athlete=self.child)
        grant = grants.issue(self.parent, self.child.pk, club_id=self.club.pk, grantee_id=self.other.pk,
            scopes=["scoring"], purpose="Junior coaching", starts_at=timezone.now()-timedelta(minutes=1), expires_at=timezone.now()+timedelta(days=1))
        self.assertTrue(grants.allows(self.other, self.child, "scoring"))
        self.child.birth_date = date(2000, 1, 1)
        self.child.save()
        self.guardian.adult_grant = True
        self.guardian.save()
        self.assertFalse(grants.allows(self.other, self.child, "scoring"))
        self.assertIsNone(self.child.account_id)

    def test_closure_and_suspension_deny_without_affecting_personal_relationship(self):
        self.grant()
        CoachRelationship.objects.create(athlete=self.athlete, coach=self.other, plan_edit=True)
        self.club.status = "suspended"
        self.club.save()
        self.assertFalse(grants.allows(self.other, self.athlete, "scoring"))
        self.assertTrue(can(self.other, self.athlete, "view"))
        self.athlete.closed_at = timezone.now()
        self.athlete.save()
        self.assertFalse(can(self.other, self.athlete, "view"))

    def test_invalid_recipients_scopes_and_windows(self):
        for changes in ({"role": "admin"}, {"grantee_id": None}, {"scopes": ["medical"]},
                {"scopes": ["training_edit"]}, {"purpose": " "}, {"expires_at": timezone.now()-timedelta(days=1)},
                {"club_id": self.private.pk}, {"grantee_id": self.admin.pk}):
            with self.assertRaises(ValidationError):
                self.grant(**changes)

    def test_scoring_payload_does_not_include_equipment_or_inputs(self):
        self.grant()
        self.assertEqual(grants.shared_payload(self.other, self.athlete.pk, "scoring"), {"sessions": []})
        with self.assertRaises(Http404):
            grants.shared_payload(self.other, self.athlete.pk, "equipment")

    def test_training_summary_excludes_baseline_and_free_text(self):
        from training.models import GeneratedPlan
        self.grant(scopes=["training"])
        GeneratedPlan.objects.create(athlete=self.athlete, requested_by=self.member, status="ready",
            inputs={"private": "secret"}, roadmap={"start_date": "2026-01-01", "baseline_json": {"private": "secret"}, "private_notes": "secret"})
        payload = grants.shared_payload(self.other, self.athlete.pk, "training")
        self.assertNotIn("secret", str(payload))
        schedule = grants.training_schedule({"microcycles": [{"week_number": 1, "sessions": [{
            "notes": "secret", "pain_flags_json": {"secret": True}, "duration_mins": 45,
            "blocks": [{"prescribed_arrows": 30, "linked_scorecard_id": "secret", "drill": {"title": "Blank bale"}}]}]}]})
        self.assertNotIn("secret", str(schedule))
        self.assertEqual(schedule["microcycles"][0]["sessions"][0]["blocks"][0]["prescribed_arrows"], 30)

    def test_training_permission_and_worker_recheck(self):
        from training.models import GeneratedPlan
        from training.management.commands.generate_training import process_next
        grant = self.grant(scopes=["training", "training_edit"])
        self.assertTrue(can(self.other, self.athlete, "edit_plan"))
        job = GeneratedPlan.objects.create(athlete=self.athlete, requested_by=self.other, status="queued", inputs={})
        grants.revoke(self.member, self.athlete.pk, grant.pk, grant.version)
        with mock.patch("training.management.commands.generate_training.PeriodizationEngineService") as engine:
            process_next()
            engine.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")

    def test_http_grant_create_revoke_json_and_saved_link_denial(self):
        self.client.force_login(self.member)
        url = reverse("clubs:grants", args=[self.athlete.pk])
        self.assertContains(self.client.get(url), "Data sharing")
        data = dict(action="issue", club=self.club.pk, grantee=self.other.pk, scopes=["scoring"],
            purpose="Synthetic coaching", starts_at=timezone.now().isoformat(), expires_at=(timezone.now()+timedelta(days=1)).isoformat())
        self.assertEqual(self.client.post(url, data).status_code, 302)
        grant = ClubDataGrant.objects.get()
        self.client.force_login(self.other)
        data_url = reverse("clubs:shared-data", args=[self.athlete.pk, "scoring"])
        response = self.client.get(data_url, {"format": "json"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertContains(self.client.get(reverse("clubs:shared")), self.athlete.display_name)
        self.assertEqual(self.client.get(reverse("athlete-detail", args=[self.athlete.pk])).status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(url, {"action": "revoke", "grant": grant.pk, "version": grant.version}).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(data_url).status_code, 404)
        self.assertTrue(ClubAuditEvent.objects.filter(action="grant.revoked").exists())

    def test_csrf_required_and_feature_off_routes_hidden(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.member)
        url = reverse("clubs:grants", args=[self.athlete.pk])
        self.assertEqual(client.post(url, {}).status_code, 403)
        with self.settings(CLUB_DATA_SHARING_ENABLED=False):
            self.assertEqual(client.get(url).status_code, 404)

    def test_rich_scoring_payload_excludes_snapshots_and_deleted_sessions(self):
        from scoring.models import ScoringSession, ArrowShot
        self.grant()
        session = ScoringSession.objects.create(athlete=self.athlete, context="training", mode="custom",
            snapshot={"private": "equipment-secret"}, equipment={"private": "equipment-secret"})
        ArrowShot.objects.create(session=session, position=0, symbol="X", points=10, is_x=True,
            arrow_snapshot={"private": "equipment-secret"})
        payload = grants.shared_payload(self.other, self.athlete.pk, "scoring")
        self.assertEqual(payload["sessions"][0]["arrows"][0]["symbol"], "X")
        self.assertNotIn("equipment-secret", str(payload))
        session.deleted_at = timezone.now()
        session.save()
        self.assertEqual(grants.shared_payload(self.other, self.athlete.pk, "scoring"), {"sessions": []})

    def test_equipment_consent_never_exposes_private_receipts_or_file_bytes(self):
        from scoring.models import EquipmentComponent, EquipmentPhoto
        component = EquipmentComponent.objects.create(owner=self.athlete, category="riser")
        photo = EquipmentPhoto.objects.create(owner=self.athlete, component=component, blob_key="synthetic-private-receipt", receipt=True)
        self.grant(scopes=["equipment"])
        self.client.force_login(self.other)
        payload = grants.shared_payload(self.other, self.athlete.pk, "equipment")
        self.assertNotIn(photo.blob_key, str(payload))
        response = self.client.get(reverse("equipment-media", args=[photo.pk]))
        self.assertIn(response.status_code, (403, 404))

    def test_scoped_training_draft_job_and_detail_do_not_open_profile(self):
        from training.tests import TrainingTests
        from training.models import GeneratedPlan
        grant = self.grant(scopes=["training", "training_edit"])
        self.client.force_login(self.other)
        response = self.client.post(reverse("training-new"), TrainingTests.data(self))
        self.assertEqual(response.status_code, 302)
        job = GeneratedPlan.objects.get()
        self.assertEqual(job.requested_by, self.other)
        self.assertEqual(job.status, "queued")
        self.assertEqual(self.client.get(response.url).status_code, 200)
        grants.revoke(self.member, self.athlete.pk, grant.pk, grant.version)
        self.assertEqual(self.client.get(response.url).status_code, 404)

    def test_worker_rechecks_permission_after_generation_before_persisting(self):
        from django.core.exceptions import PermissionDenied
        from training.tests import TrainingTests
        from training.models import GeneratedPlan
        from training.management.commands.generate_training import process_next
        self.grant(scopes=["training", "training_edit"])
        self.client.force_login(self.other)
        self.client.post(reverse("training-new"), TrainingTests.data(self))
        job = GeneratedPlan.objects.get()
        with mock.patch("training.management.commands.generate_training.relationships.require", side_effect=[None, PermissionDenied]), mock.patch("training.management.commands.generate_training.PeriodizationEngineService"):
            self.assertTrue(process_next())
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.roadmap, {})
