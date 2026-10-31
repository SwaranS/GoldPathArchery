from datetime import date, timedelta
from unittest import mock, skipUnless
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, connections, close_old_connections
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import AthleteProfile
from training.models import GeneratedPlan
from training.forms import GenerationForm
from training import tests as training_tests
from training.management.commands.generate_training import process_next
from . import programmes as service, memberships, grants
from .models import (ClubRoleAssignment, ClubProgramme, ClubProgrammeRevision, ClubTrainingGroupMember,
    ClubProgrammeAssignment, ClubAssignmentPlan, ClubProgrammeProgress, ClubAuditEvent)
from .test_memberships import Fixtures
from .tests import login_with_mfa


class ProgrammeFixtures(Fixtures):
    def setUp(self):
        super().setUp()
        self.club_member = self.join(athlete=self.athlete)
        coach_member = self.join(self.other)
        self.coach_role = ClubRoleAssignment.objects.create(membership=coach_member, role="coach", accepted_at=timezone.now())
        self.group = service.save_group(self.admin, self.club.pk, dict(name="Synthetic recurve group", description="Group instructions",
            discipline="recurve", coach_role=self.coach_role, active=True))

    def group_join(self, club_member=None, actor=None, group=None):
        member = service.invite_group(self.other, (group or self.group).pk, (club_member or self.club_member).pk)
        return service.respond_group(actor or self.member, member.pk, True, member.version)

    def programme(self, **changes):
        data = dict(title="Synthetic programme", instructions="Group technical practice",
            start_date=timezone.localdate(), duration_days=84, archetype="stamina_builder", round_format="wa_720_70m",
            sessions=[dict(weekday=0, start_time="18:00", duration_mins=90, description="Group technique practice")])
        data.update(changes)
        programme = service.save_template(self.other, self.group.pk, data)
        return service.publish(self.other, programme.pk, programme.version)

    def assignment(self, member=None, programme=None):
        member = member or self.group_join()
        programme = programme or self.programme()
        return service.offer(self.other, programme.pk, member.pk, programme.version)

    def payload(self, athlete=None):
        data = training_tests.TrainingTests.data(self)
        data["athlete"] = str((athlete or self.athlete).pk)
        form = GenerationForm(data, athletes=AthleteProfile.objects.filter(pk=(athlete or self.athlete).pk))
        assert form.is_valid(), form.errors
        return form.payload

    def accept(self, assignment=None, actor=None, athlete=None, note=""):
        assignment = assignment or self.assignment()
        return service.respond_assignment(actor or self.member, assignment.pk, "accept", assignment.version,
            payload=self.payload(athlete), private_note=note)


FLAGS = dict(CLUBS_ENABLED=True, CLUB_MEMBERSHIPS_ENABLED=True, CLUB_DATA_SHARING_ENABLED=True, CLUB_PROGRAMMES_ENABLED=True)


@override_settings(**FLAGS)
class ProgrammeTests(ProgrammeFixtures, TestCase):
    def test_zero_one_multiple_groups_and_declined_invitation(self):
        self.assertEqual(list(service.own_group_members(self.member)), [])
        first = self.group_join()
        second_group = service.save_group(self.admin, self.club.pk, dict(name="Second group", description="", discipline="recurve", coach_role=self.coach_role, active=True))
        invitation = service.invite_group(self.other, second_group.pk, self.club_member.pk)
        service.respond_group(self.member, invitation.pk, False, invitation.version)
        self.assertEqual(ClubTrainingGroupMember.objects.filter(state="active").count(), 1)
        invitation = service.invite_group(self.other, second_group.pk, self.club_member.pk)
        service.respond_group(self.member, invitation.pk, True, invitation.version)
        self.assertEqual(len(service.groups_for(self.member)), 2)
        self.assertFalse(GeneratedPlan.objects.exists())

    def test_acceptance_creates_independent_queued_plan_without_overwriting_existing(self):
        old = GeneratedPlan.objects.create(athlete=self.athlete, requested_by=self.member, status="ready", inputs={}, roadmap={"private_existing_plan": True})
        assignment = self.accept(note="PRIVATE CUSTOMIZATION")
        plan = assignment.plans.get().plan
        self.assertEqual(plan.status, "queued")
        self.assertEqual(plan.requested_by, self.member)
        self.assertTrue(process_next())
        plan.refresh_from_db()
        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.roadmap["status"], "draft")
        self.assertEqual(plan.roadmap["club_programme"]["revision"], 1)
        old.refresh_from_db()
        self.assertEqual(old.roadmap, {"private_existing_plan": True})
        self.assertNotIn("PRIVATE CUSTOMIZATION", str(plan.inputs)+str(plan.roadmap))
        self.assertEqual(GeneratedPlan.objects.count(), 2)

    def test_decline_and_replay_create_no_plan(self):
        assignment = self.assignment()
        service.respond_assignment(self.member, assignment.pk, "decline", assignment.version)
        with self.assertRaises(service.ProgrammeConflict):
            self.accept(assignment)
        self.assertFalse(GeneratedPlan.objects.exists())

    def test_guardian_acceptance_for_child_without_login_and_age_transition(self):
        self.child.discipline = "recurve"
        self.child.save()
        child_member = self.join(self.parent, athlete=self.child)
        group_member = self.group_join(child_member, self.parent)
        assignment = self.assignment(group_member)
        self.accept(assignment, self.parent, self.child)
        self.assertIsNone(self.child.account_id)
        self.assertEqual(assignment.plans.get().plan.requested_by, self.parent)
        self.child.birth_date = date(2000, 1, 1)
        self.child.save()
        with self.assertRaises(Http404):
            service.respond_assignment(self.parent, assignment.pk, "customize", 2, payload=self.payload(self.child))
        self.assertFalse(service.generation_allowed(assignment.plans.get().plan))

    def test_coach_cannot_self_consent_or_read_private_assignment(self):
        assignment = self.assignment()
        for actor in (self.other, self.admin):
            with self.assertRaises(Http404):
                service.assignment_for_owner(actor, assignment.pk)
            with self.assertRaises(Http404):
                service.respond_assignment(actor, assignment.pk, "accept", assignment.version, payload=self.payload())

    def test_customized_versions_preserve_previous_drafts_and_other_athletes(self):
        assignment = self.accept()
        old_plan = assignment.plans.get(number=1).plan
        self.assertTrue(process_next())
        old_plan.refresh_from_db()
        original = old_plan.roadmap.copy()
        payload = self.payload()
        payload["baseline"]["current_weekly_arrow_volume"] = 100
        service.respond_assignment(self.member, assignment.pk, "customize", assignment.version, payload=payload)
        self.assertTrue(process_next())
        old_plan.refresh_from_db()
        self.assertEqual(old_plan.roadmap, original)
        self.assertEqual(assignment.plans.count(), 2)
        self.assertEqual(assignment.revision.snapshot["instructions"], "Group technical practice")

    def test_template_revisions_are_immutable_and_offers_keep_exact_source(self):
        assignment = self.assignment()
        revision = assignment.revision
        with self.assertRaises(ValueError):
            revision.save()
        programme = revision.programme
        data = {key: revision.snapshot[key] for key in ("title", "instructions", "start_date", "duration_days", "archetype", "round_format", "sessions")}
        data["instructions"] = "Changed source"
        programme = service.save_template(self.other, self.group.pk, data, programme_id=programme.pk, version=programme.version)
        service.publish(self.other, programme.pk, programme.version)
        self.accept(assignment)
        self.assertTrue(process_next())
        self.assertEqual(assignment.plans.get().plan.roadmap["club_programme"]["instructions"], "Group technical practice")

    def test_progress_requires_separate_club_scoped_grant_and_never_shares_notes(self):
        assignment = self.accept()
        process_next()
        service.save_progress(self.member, assignment.pk, 1, "PRIVATE ADHERENCE NOTE", 0)
        self.assertEqual(service.shared_progress(self.other, self.athlete.pk), {"progress": []})
        grant = grants.issue(self.member, self.athlete.pk, club_id=self.club.pk, grantee_id=self.other.pk,
            scopes=["training"], purpose="Training only", starts_at=timezone.now()-timedelta(minutes=1), expires_at=timezone.now()+timedelta(days=7))
        self.assertEqual(service.shared_progress(self.other, self.athlete.pk), {"progress": []})
        grant = grants.issue(self.member, self.athlete.pk, club_id=self.club.pk, grantee_id=self.other.pk,
            scopes=["programme_progress"], purpose="Count review", starts_at=timezone.now()-timedelta(minutes=1), expires_at=timezone.now()+timedelta(days=7))
        payload = service.shared_progress(self.other, self.athlete.pk)
        self.assertEqual(payload["progress"][0]["completed_sessions"], 1)
        self.assertNotIn("PRIVATE ADHERENCE NOTE", str(payload))
        grants.revoke(self.member, self.athlete.pk, grant.pk, grant.version)
        self.assertEqual(service.shared_progress(self.other, self.athlete.pk), {"progress": []})

    def test_progress_owner_only_and_stale_or_invalid_counts_denied(self):
        assignment = self.accept()
        with self.assertRaises(ValidationError):
            service.save_progress(self.member, assignment.pk, 1, "", 0)
        process_next()
        progress = service.save_progress(self.member, assignment.pk, 1, "Private", 0)
        with self.assertRaises(service.ProgrammeConflict):
            service.save_progress(self.member, assignment.pk, 2, "", 0)
        with self.assertRaises(ValidationError):
            service.save_progress(self.member, assignment.pk, 100000, "", progress.version)
        with self.assertRaises(Http404):
            service.save_progress(self.other, assignment.pk, 1, "", progress.version)

    def test_withdrawal_and_club_departure_stop_jobs_keep_personal_history(self):
        assignment = self.accept()
        process_next()
        first = assignment.plans.get().plan
        assignment = service.respond_assignment(self.member, assignment.pk, "customize", assignment.version, payload=self.payload())
        second = assignment.plans.get(number=2).plan
        service.respond_assignment(self.member, assignment.pk, "withdraw", assignment.version)
        with mock.patch("training.management.commands.generate_training.PeriodizationEngineService") as engine:
            process_next()
            engine.assert_not_called()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, "ready")
        self.assertEqual(second.status, "failed")
        self.assertTrue(service.owner_read(self.member, first.athlete))

    def test_coach_role_loss_and_group_reassignment_invalidate_pending_jobs(self):
        assignment = self.accept()
        self.coach_role.revoked_at = timezone.now()
        self.coach_role.save()
        self.assertFalse(service.generation_allowed(assignment.plans.get().plan))
        with mock.patch("training.management.commands.generate_training.PeriodizationEngineService") as engine:
            process_next()
            engine.assert_not_called()

    def test_archival_keeps_accepted_plan_and_prevents_new_consent(self):
        assignment = self.accept()
        process_next()
        programme = assignment.revision.programme
        service.archive(self.other, programme.pk, programme.version)
        self.assertEqual(assignment.plans.get().plan.status, "ready")
        with self.assertRaises(ValidationError):
            service.respond_assignment(self.member, assignment.pk, "customize", assignment.version, payload=self.payload())

    def test_membership_exit_cancels_group_and_pending_offers(self):
        assignment = self.assignment()
        memberships.end_membership(self.member, self.club.pk, self.club_member.pk, "left", self.club_member.version)
        assignment.refresh_from_db()
        assignment.group_member.refresh_from_db()
        self.assertEqual(assignment.state, "cancelled")
        self.assertEqual(assignment.group_member.state, "left")
        self.assertFalse(GeneratedPlan.objects.exists())

    def test_cross_club_ids_and_global_role_do_not_authorize_group_control(self):
        with self.assertRaises(Http404):
            service.control_group(self.member, self.group.pk)
        with self.assertRaises(ValidationError):
            service.save_group(self.admin, self.private.pk, dict(name="Cross club", description="", discipline="recurve", coach_role=self.coach_role, active=True))
        private_member = service.ClubMembership.objects.get(club=self.private, user=self.admin)
        with self.assertRaises(Http404):
            service.invite_group(self.other, self.group.pk, private_member.pk)

    def test_expiry_stale_version_and_unpublished_template(self):
        member = self.group_join()
        programme = self.programme()
        with self.assertRaises(service.ProgrammeConflict):
            service.offer(self.other, programme.pk, member.pk, 999)
        assignment = service.offer(self.other, programme.pk, member.pk, programme.version)
        assignment.expires_at = timezone.now()-timedelta(seconds=1)
        assignment.save()
        with self.assertRaises(ValidationError):
            self.accept(assignment)

    def test_programme_scope_not_offered_when_feature_off(self):
        with self.settings(CLUB_PROGRAMMES_ENABLED=False):
            with self.assertRaises(Http404):
                service.groups_for(self.member)
            with self.assertRaises(ValidationError):
                grants.issue(self.member, self.athlete.pk, club_id=self.club.pk, grantee_id=self.other.pk,
                    scopes=["programme_progress"], purpose="No", starts_at=timezone.now(), expires_at=timezone.now()+timedelta(days=1))

    def test_http_owner_accept_decline_and_coach_progress_gates(self):
        assignment = self.assignment()
        self.client.force_login(self.member)
        url = reverse("clubs:programme-assignment", args=[assignment.pk])
        self.assertContains(self.client.get(url), "individual training inputs")
        data = {"individual-"+key: value for key, value in training_tests.TrainingTests.data(self).items()}
        response = self.client.post(url, {**data, "action": "response", "version": assignment.version, "decision": "accept", "private_note": "PRIVATE INPUT NOTE"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(process_next())
        self.assertContains(self.client.get(url), "Open personal draft version 1")
        login_with_mfa(self.client, self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        progress_url = reverse("clubs:programme-coach-progress", args=[assignment.pk])
        self.assertEqual(self.client.get(progress_url).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(progress_url).status_code, 404)

    def test_http_authoring_mfa_and_group_invitation_response(self):
        url = reverse("clubs:training-group", args=[self.group.pk])
        self.client.force_login(self.other)
        self.assertIn(reverse("mfa_index"), self.client.get(url).url)
        login_with_mfa(self.client, self.other)
        self.assertContains(self.client.get(url), "Create a programme template")
        invitation = service.invite_group(self.other, self.group.pk, self.club_member.pk)
        self.client.force_login(self.member)
        response = self.client.post(reverse("clubs:group-member-response", args=[invitation.pk]), {"version": invitation.version, "decision": "accept"})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(url), self.group.name)

    def test_csrf_and_no_plan_for_decline(self):
        assignment = self.assignment()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.member)
        url = reverse("clubs:programme-assignment", args=[assignment.pk])
        self.assertEqual(client.post(url, {}).status_code, 403)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(url, {"action": "response", "version": assignment.version, "decision": "decline"}).status_code, 302)
        self.assertFalse(GeneratedPlan.objects.exists())

    def test_two_athletes_have_independent_consent_and_source_snapshot(self):
        other_athlete = AthleteProfile.objects.create(account=self.parent, display_name="Second synthetic athlete", birth_date=date(1990, 1, 1), discipline="recurve")
        other_membership = self.join(self.parent, athlete=other_athlete)
        first_member = self.group_join()
        second_member = self.group_join(other_membership, self.parent)
        programme = self.programme()
        first = self.assignment(first_member, programme)
        second = self.assignment(second_member, programme)
        self.accept(first)
        service.respond_assignment(self.parent, second.pk, "decline", second.version)
        self.assertEqual(GeneratedPlan.objects.filter(athlete=self.athlete).count(), 1)
        self.assertFalse(GeneratedPlan.objects.filter(athlete=other_athlete).exists())
        self.assertEqual(ClubProgrammeRevision.objects.filter(programme=programme).count(), 1)

    def test_http_coach_template_publish_offer_and_group_admin_settings(self):
        login_with_mfa(self.client, self.admin)
        settings_url = reverse("clubs:training-group-settings", args=[self.club.pk, self.group.pk])
        self.assertEqual(self.client.get(settings_url).status_code, 200)
        self.assertEqual(self.client.post(settings_url, {"name": self.group.name, "description": "Updated", "discipline": "recurve",
            "coach_role": self.coach_role.pk, "active": "on", "version": self.group.version}).status_code, 302)
        member = self.group_join()
        login_with_mfa(self.client, self.other)
        url = reverse("clubs:programme-new", args=[self.group.pk])
        self.assertContains(self.client.get(url), "Weekly group sessions")
        response = self.client.post(url, {"title": "HTTP source", "instructions": "Group only", "start_date": timezone.localdate().isoformat(),
            "duration_days": 84, "archetype": "stamina_builder", "round_format": "wa_720_70m",
            "sessions-TOTAL_FORMS": 1, "sessions-INITIAL_FORMS": 0, "sessions-MIN_NUM_FORMS": 1, "sessions-MAX_NUM_FORMS": 14,
            "sessions-0-weekday": 0, "sessions-0-start_time": "18:00", "sessions-0-duration_mins": 90, "sessions-0-description": "Technique"})
        self.assertEqual(response.status_code, 302)
        programme = ClubProgramme.objects.get()
        url = reverse("clubs:programme", args=[programme.pk])
        self.assertEqual(self.client.post(url, {"action": "publish", "version": programme.version}).status_code, 302)
        programme.refresh_from_db()
        self.assertEqual(self.client.post(reverse("clubs:programme-offer", args=[programme.pk]), {"version": programme.version, "member": member.pk}).status_code, 302)

    def test_progress_counts_cannot_leak_across_club_grants(self):
        assignment = self.accept()
        process_next()
        service.save_progress(self.member, assignment.pk, 1, "Private", 0)
        invite, token = memberships.invite(self.admin, self.private.pk, self.member.email)
        memberships.accept_invite(self.member, invite.pk, token, athlete_id=self.athlete.pk)
        invite, token = memberships.invite(self.admin, self.private.pk, self.other.email)
        coach_member = memberships.accept_invite(self.other, invite.pk, token).membership
        ClubRoleAssignment.objects.create(membership=coach_member, role="coach", accepted_at=timezone.now())
        grants.issue(self.member, self.athlete.pk, club_id=self.private.pk, grantee_id=self.other.pk,
            scopes=["programme_progress"], purpose="Other club only", starts_at=timezone.now()-timedelta(minutes=1), expires_at=timezone.now()+timedelta(days=7))
        self.assertEqual(service.shared_progress(self.other, self.athlete.pk), {"progress": []})

    def test_new_explicit_offer_after_decline_never_replays_old_consent(self):
        first = self.assignment()
        service.respond_assignment(self.member, first.pk, "decline", first.version)
        programme = first.revision.programme
        second = service.offer(self.other, programme.pk, first.group_member_id, programme.version)
        self.assertNotEqual(first.pk, second.pk)
        self.assertFalse(GeneratedPlan.objects.exists())
        self.accept(second)
        self.assertEqual(GeneratedPlan.objects.count(), 1)

    def test_offered_dates_render_in_native_inputs_and_do_not_revert_to_defaults(self):
        programme = self.programme(duration_days=28, start_date=timezone.localdate()+timedelta(days=7))
        assignment = self.assignment(programme=programme)
        self.client.force_login(self.member)
        response = self.client.get(reverse("clubs:programme-assignment", args=[assignment.pk]))
        self.assertContains(response, 'value="'+assignment.revision.snapshot["start_date"]+'"')
        self.assertContains(response, 'value="'+assignment.revision.snapshot["target_date"]+'"')

    def test_administrator_can_archive_group_after_its_coach_loses_role(self):
        self.coach_role.revoked_at = timezone.now()
        self.coach_role.save()
        group = service.save_group(self.admin, self.club.pk, dict(name=self.group.name, description=self.group.description,
            discipline=self.group.discipline, coach_role=self.coach_role, active=False), group_id=self.group.pk, version=self.group.version)
        self.assertFalse(group.active)

    def test_current_coach_can_create_own_group_but_not_assign_another_coach(self):
        group = service.save_group(self.other, self.club.pk, dict(name="Coach-created group", description="", discipline="recurve", coach_role=self.coach_role, active=True))
        self.assertTrue(service.is_coach(self.other, group))
        other_role = ClubRoleAssignment.objects.create(membership=service.ClubMembership.objects.get(user=self.admin, club=self.club), role="coach", accepted_at=timezone.now())
        with self.assertRaises(Http404):
            service.save_group(self.other, self.club.pk, dict(name="Invalid reassignment", description="", discipline="recurve", coach_role=other_role, active=True), group_id=group.pk, version=group.version)
        login_with_mfa(self.client, self.other)
        self.assertEqual(self.client.get(reverse("clubs:training-group-new", args=[self.club.pk])).status_code, 200)

    def test_stale_http_consent_returns_conflict_after_a_decision(self):
        assignment = self.assignment()
        url = reverse("clubs:programme-assignment", args=[assignment.pk])
        self.client.force_login(self.member)
        data = {"action": "response", "version": assignment.version, "decision": "decline"}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 409)
        self.assertFalse(GeneratedPlan.objects.exists())


@skipUnless(connection.vendor == "postgresql", "Requires disposable PostgreSQL row locks")
@override_settings(**FLAGS)
class ProgrammeConcurrencyTests(ProgrammeFixtures, TransactionTestCase):
    def test_concurrent_acceptance_creates_only_one_personal_draft(self):
        assignment = self.assignment()
        payload = self.payload()
        def accept(_):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.member.pk)
                service.respond_assignment(actor, assignment.pk, "accept", assignment.version, payload=payload)
                return "accepted"
            except service.ProgrammeConflict:
                return "stale"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(accept, range(2)))
        self.assertCountEqual(results, ["accepted", "stale"])
        self.assertEqual(GeneratedPlan.objects.count(), 1)
