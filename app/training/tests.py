from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AthleteProfile, CoachRelationship
from .models import GeneratedPlan
from .management.commands.generate_training import process_next


class TrainingTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="training-owner")
        self.other = get_user_model().objects.create_user(username="training-other")
        self.athlete = AthleteProfile.objects.create(account=self.owner, display_name="Test Archer", birth_date=date(2000, 1, 1), discipline="recurve", transitioned_at=timezone.now())
        self.client.force_login(self.owner)

    def data(self, **updates):
        today = timezone.localdate()
        data = dict(athlete=str(self.athlete.pk), archetype="stamina_builder", round_format="wa_720_70m", start_date=today.isoformat(), target_date=(today + timedelta(days=84)).isoformat(), competition_tier="A", current_draw_weight=30, weekly_arrows=200, days=[0, 2, 5], minutes=90, distance=70)
        data.update(updates)
        return data

    def enqueue(self):
        response = self.client.post(reverse("training-new"), self.data())
        self.assertEqual(response.status_code, 302)
        return GeneratedPlan.objects.get()

    def test_authenticated_page_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.client.get("/training/new").status_code, 302)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get("/training/new"), "Create a training plan")
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post("/training/new", self.data()).status_code, 403)

    def test_generation_is_queued_and_persisted(self):
        job = self.enqueue()
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.roadmap, {})
        self.assertTrue(process_next())
        job.refresh_from_db()
        self.assertEqual(job.status, "ready")
        self.assertEqual(job.roadmap["status"], "draft")
        self.assertEqual(len(job.roadmap["microcycles"]), 12)
        self.assertTrue(job.roadmap["microcycles"][0]["sessions"][0]["blocks"])
        self.assertContains(self.client.get(reverse("training-detail", args=[job.pk])), "Week 12")
        self.assertFalse(process_next())

    def test_other_athlete_and_revoked_access(self):
        job = self.enqueue()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("training-detail", args=[job.pk])).status_code, 404)
        self.client.post("/training/new", self.data())
        self.assertEqual(GeneratedPlan.objects.count(), 1)
        link = CoachRelationship.objects.create(athlete=self.athlete, coach=self.other, plan_edit=True)
        self.assertContains(self.client.get(reverse("training-detail", args=[job.pk])), "queued")
        job.requested_by = self.other
        job.save()
        link.revoked_at = timezone.now()
        link.save()
        self.assertTrue(process_next())
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual(self.client.get(reverse("training-detail", args=[job.pk])).status_code, 404)

    def test_validation_and_poundage_lockout(self):
        for changes in [dict(target_date=timezone.localdate().isoformat()), dict(days=[]), dict(weekly_arrows=-1), dict(target_date=(timezone.localdate() + timedelta(days=366)).isoformat()), dict(archetype="poundage_increase", target_draw_weight=35, target_date=(timezone.localdate() + timedelta(days=20)).isoformat())]:
            response = self.client.post("/training/new", self.data(**changes))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.assertFalse(GeneratedPlan.objects.exists())

    def test_failed_job_does_not_stop_worker(self):
        job = self.enqueue()
        with patch("training.management.commands.generate_training.PeriodizationEngineService.generate_plan", side_effect=RuntimeError("test")):
            self.assertTrue(process_next())
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertFalse(process_next())

    def test_athlete_plans_shows_roadmap_and_excludes_other_athletes(self):
        job = self.enqueue()
        process_next()
        foreign = AthleteProfile.objects.create(account=self.other, display_name="Other Archer", birth_date=date(2000, 1, 1), discipline="barebow", transitioned_at=timezone.now())
        hidden = GeneratedPlan.objects.create(athlete=foreign, requested_by=self.other, inputs={}, status="ready", roadmap={"start_date": "PRIVATE-DRAFT"})
        response = self.client.get(reverse("athlete-plans", args=[self.athlete.pk]))
        self.assertContains(response, reverse("training-detail", args=[job.pk]))
        self.assertContains(response, "Week 12")
        self.assertContains(response, "Ready for review")
        self.assertNotContains(response, "No plan yet")
        self.assertNotContains(response, "No training plan has been generated")
        self.assertNotContains(response, reverse("training-detail", args=[hidden.pk]))
        self.assertNotContains(response, "PRIVATE-DRAFT")

    def test_pending_job_does_not_hide_ready_roadmap_and_revocation_blocks_page(self):
        self.enqueue()
        process_next()
        self.client.post("/training/new", self.data())
        url = reverse("athlete-plans", args=[self.athlete.pk])
        response = self.client.get(url)
        self.assertContains(response, "Queued for generation")
        self.assertContains(response, "Week 12")
        link = CoachRelationship.objects.create(athlete=self.athlete, coach=self.other)
        self.client.force_login(self.other)
        self.assertContains(self.client.get(url), "Week 12")
        link.revoked_at = timezone.now()
        link.save()
        self.assertEqual(self.client.get(url).status_code, 404)
