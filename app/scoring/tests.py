import json
import uuid
from datetime import date

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import AthleteProfile, CoachRelationship, GuardianLink, User, UserRole
from . import services as s
from .models import Equipment, PhysicalArrow, RoundDefinition, RoundStage, ScoringRuleSet, TargetFace


class ScoringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="archer")
        cls.other = User.objects.create_user(username="other")
        cls.athlete = AthleteProfile.objects.create(account=cls.user, display_name="Archer", birth_date=date(1990, 1, 1), discipline="recurve")
        cls.target = TargetFace.objects.create(name="40 cm", diameter_cm=40, geometry=dict(spots=[[0, 0, 1]], rings=[.05, .1, .2, 1]))
        cls.rules = ScoringRuleSet.objects.create(name="X scoring", rules=dict(zones=[dict(radius=.05, symbol="X", points=10, x=True), dict(radius=.1, symbol="10", points=10), dict(radius=.2, symbol="9", points=9), dict(radius=1, symbol="1", points=1)]))
        cls.round = RoundDefinition.objects.create(name="Short round", division="recurve")
        RoundStage.objects.create(round=cls.round, order=1, distance_m=18, target=cls.target, rules=cls.rules, ends=1, arrows_per_end=3)

    def start(self, **overrides):
        return s.start(self.user, self.athlete, dict(mode="round", context="training", round=self.round.pk, **overrides))

    def change(self, session, action="shot", actor=None, **kwargs):
        session.refresh_from_db()
        return s.mutate(actor or self.user, session.pk, dict(key=str(uuid.uuid4()), version=session.version, action=action, **kwargs))

    def shot(self, session, position, symbol="X", **kwargs):
        return self.change(session, position=position, symbol=symbol, method="manual", **kwargs)

    def complete(self, session):
        for position in range(sum(t["ends"] * t["arrows_per_end"] for t in session.snapshot["stages"])):
            self.shot(session, position)
        self.change(session, "review")
        return self.change(session, "complete")

    def test_mixed_entry_retry_and_correction(self):
        session = self.start()
        payload = dict(key=str(uuid.uuid4()), version=1, action="shot", position=0, method="manual", symbol="X")
        s.mutate(self.user, session.pk, payload)
        s.mutate(self.user, session.pk, payload)
        self.assertEqual(session.shots.count(), 1)
        self.assertEqual(session.audit.filter(operation="shot").count(), 1)
        with self.assertRaises(s.Conflict):
            s.mutate(self.user, session.pk, {**payload, "symbol": "M"})
        self.change(session, position=1, method="tap", x=.1, y=0, spot=0)
        self.shot(session, 2, "M")
        self.assertIsNone(session.shots.get(position=0).x)
        self.assertEqual(session.shots.get(position=1).points, 10)
        self.assertEqual(s.statistics(session)["total"], 20)
        self.assertEqual(s.statistics(session)["xs"], 1)
        self.change(session, "review")
        self.change(session, "complete")
        self.change(session, "reopen")
        self.shot(session, 0, "9", reason="Corrected observed value")
        audit = session.audit.filter(operation="shot").last()
        self.assertEqual(audit.before["symbol"], "X")
        self.assertEqual(audit.after["symbol"], "9")
        self.assertEqual(s.statistics(session)["total"], 19)

    def test_snapshots_and_validation(self):
        session = self.start()
        self.target.diameter_cm = 60
        self.target.geometry = dict(spots=[[0, 0, 1]], rings=[1])
        self.target.save()
        self.rules.rules = dict(zones=[dict(radius=1, symbol="Z", points=99)])
        self.rules.save()
        session.refresh_from_db()
        self.assertEqual(session.snapshot["stages"][0]["diameter_cm"], 40)
        self.shot(session, 0)
        for values in (dict(method="manual", symbol="8"), dict(method="tap", x=float("nan"), y=0, spot=0),
                       dict(method="tap", x=2, y=0, spot=0), dict(method="tap", x=0, y=0, spot=5),
                       dict(method="tap", x=0, y=0, spot=0, symbol="M")):
            with self.assertRaises(ValidationError):
                self.change(session, position=1, **values)
        self.change(session, position=1, method="tap", x=0, y=0, spot=0, symbol="M", reason="Observed miss")
        self.change(session, "review")
        with self.assertRaises(ValidationError):
            self.change(session, "complete")

    def test_permissions_and_revoked_access(self):
        session = self.start()
        CoachRelationship.objects.create(athlete=self.athlete, coach=self.other, plan_edit=True)
        UserRole.objects.create(user=self.other, role="coach")
        with self.assertRaises(PermissionDenied):
            self.change(session, "pause", actor=self.other)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("scoring-session", args=[session.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("scoring-save", args=[session.pk]), data=json.dumps(dict(key=str(uuid.uuid4()), version=1, action="pause")), content_type="application/json").status_code, 404)
        self.assertEqual(self.client.get(reverse("scoring-start", args=[self.athlete.pk])).status_code, 404)
        CoachRelationship.objects.filter(coach=self.other).delete()
        self.assertEqual(self.client.get(reverse("scoring-session", args=[session.pk])).status_code, 404)
        for model in ("targetface", "scoringruleset", "rounddefinition"):
            self.assertEqual(self.client.get(f"/admin/scoring/{model}/add/").status_code, 302)

    def test_guardian_and_age_rules(self):
        child = AthleteProfile.objects.create(display_name="Junior", birth_date=date(2015, 1, 1), discipline="recurve")
        guardian = GuardianLink.objects.create(athlete=child, parent=self.other, managing=True, access="edit")
        session = s.start(self.other, child, dict(mode="round", context="training", round=self.round.pk))
        self.change(session, "pause", actor=self.other)
        guardian.access = "view"
        guardian.save()
        with self.assertRaises(PermissionDenied):
            self.change(session, "resume", actor=self.other)

    def test_pb_classification_recalculation_and_locks(self):
        training = self.complete(self.start())
        competition = s.start(self.user, self.athlete, dict(mode="round", context="competition", round=self.round.pk))
        competition = self.complete(competition)
        sessions = lambda: self.athlete.scoring_sessions.all()
        self.assertEqual(len(s.personal_bests(sessions())), 2)
        self.change(training, "reopen")
        self.assertEqual(len(s.personal_bests(sessions())), 1)
        self.change(training, "review")
        training = self.change(training, "complete")
        self.change(training, "delete", confirmed=True)
        self.assertEqual(len(s.personal_bests(sessions())), 1)
        self.change(training, "restore", confirmed=True)
        self.assertEqual(len(s.personal_bests(sessions())), 2)
        self.change(training, "invalidate")
        self.assertEqual(len(s.personal_bests(sessions())), 1)
        self.other.is_staff = True
        self.other.save()
        self.other.user_permissions.add(Permission.objects.get(codename="change_scoringsession"))
        self.change(competition, "verify", actor=self.other)
        with self.assertRaises(ValidationError):
            self.change(competition, "reopen")
        self.assertTrue(competition.audit.filter(operation="verify").exists())
        self.client.force_login(self.user)
        response = self.client.get(reverse("scoring-session", args=[competition.pk]))
        self.assertContains(response, 'data-action="delete"')
        self.assertNotContains(response, 'id="entry"')
        self.change(competition, "delete", confirmed=True)
        self.change(competition, "restore", confirmed=True)
        competition.refresh_from_db()
        self.assertIsNotNone(competition.verified_at)

    def test_comparison_boundaries_and_verification_required(self):
        first = self.complete(self.start())
        self.target.diameter_cm = 60
        self.target.save()
        second = self.complete(self.start())
        self.assertNotEqual(s.comparison_key(first), s.comparison_key(second))
        self.assertEqual(len(s.personal_bests([first, second])), 2)
        self.round.verification_required = True
        self.round.save()
        competition = s.start(self.user, self.athlete, dict(mode="round", context="competition", round=self.round.pk))
        competition = self.complete(competition)
        self.assertEqual(s.personal_bests([competition]), [])
        first.snapshot["division"] = "compound"
        self.assertNotEqual(s.comparison_key(first), s.comparison_key(second))

    def test_custom_and_equipment_averages(self):
        arrow_set = Equipment.objects.create(athlete=self.athlete, kind="arrow_set", name="Set A")
        arrow = PhysicalArrow.objects.create(arrow_set=arrow_set, identifier="7")
        session = s.start(self.user, self.athlete, dict(mode="custom", context="training", target=self.target.pk,
            rules=self.rules.pk, distance_m=18, ends=1, arrows_per_end=3, arrow_set=arrow_set.pk))
        self.shot(session, 0, "X", arrow=arrow.pk)
        self.shot(session, 1, "M", arrow=arrow.pk)
        self.shot(session, 2, "9")
        row = s.arrow_comparisons([session])[0]
        self.assertEqual((row["count"], row["average"]), (2, 5))
        arrow_set.active = False
        arrow_set.save()
        with self.assertRaises(PhysicalArrow.DoesNotExist):
            self.shot(session, 2, "X", arrow=arrow.pk)
        self.assertEqual(s.arrow_comparisons([session])[0]["average"], 5)
        self.shot(session, 0, "9", arrow=arrow.pk)
        self.assertEqual(s.arrow_comparisons([session])[0]["average"], 4.5)
        other_set = Equipment.objects.create(athlete=self.athlete, kind="arrow_set", name="Set B")
        other_arrow = PhysicalArrow.objects.create(arrow_set=other_set, identifier="7")
        with self.assertRaises(PhysicalArrow.DoesNotExist):
            self.shot(session, 2, arrow=other_arrow.pk)

    def test_pause_resume_stale_version_and_mobile_pages(self):
        session = self.start()
        self.shot(session, 0)
        self.change(session, "pause")
        with self.assertRaises(ValidationError):
            self.shot(session, 1)
        self.change(session, "resume")
        self.assertEqual(s.statistics(session)["next_position"], 1)
        with self.assertRaises(s.Conflict):
            s.mutate(self.user, session.pk, dict(key=str(uuid.uuid4()), version=1, action="pause"))
        self.client.force_login(self.user)
        for url in (reverse("scoring-session", args=[session.pk]), reverse("scoring-history", args=[self.athlete.pk]),
                    reverse("scoring-start", args=[self.athlete.pk]), reverse("scoring-equipment", args=[self.athlete.pk])):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get(reverse("scoring-session", args=[session.pk])), 'scoring-data')

    def test_seed_and_sixty_arrow_multistage_round(self):
        call_command("seed_scoring", verbosity=0)
        count = TargetFace.objects.count()
        call_command("seed_scoring", verbosity=0)
        self.assertEqual(TargetFace.objects.count(), count)
        junior = TargetFace.objects.get(name="Practice 60 cm junior full")
        self.assertEqual(junior.diameter_cm, 60)
        definition = RoundDefinition.objects.get(name="Practice Indoor 60 · recurve")
        self.assertEqual(definition.maximum, 600)
        session = s.start(self.user, self.athlete, dict(mode="round", context="training", round=definition.pk))
        for pos in range(30):
            self.shot(session, pos, "10")
        self.change(session, "pause")
        self.change(session, "resume")
        self.assertEqual(s.statistics(session)["next_position"], 30)
        for pos in range(30, 60):
            self.shot(session, pos, "10")
        self.change(session, "review")
        self.change(session, "complete")
        self.assertEqual(s.statistics(session)["total"], 600)
        RoundStage.objects.create(round=self.round, order=2, distance_m=30, target=junior, rules=self.rules, ends=1, arrows_per_end=2)
        multi = self.complete(self.start())
        self.assertEqual(s.statistics(multi)["total"], 50)

    def test_compound_inner_ten_and_triple_spots(self):
        call_command("seed_scoring", verbosity=0)
        compound = ScoringRuleSet.objects.get(name="Practice indoor compound inner ten")
        target = TargetFace.objects.get(name="Practice 40 cm vertical triple")
        stage = s.stage_snapshot(target, compound, 18, 1, 3)
        cx, cy, radius = stage["geometry"]["spots"][1]
        self.assertEqual(s.suggest(stage, cx + .05 * radius, cy, 1), "10")
        self.assertEqual(s.suggest(stage, cx + .08 * radius, cy, 1), "9")
        self.assertNotIn("X", s.score_options(stage))

    def test_staff_role_does_not_grant_configuration_permissions(self):
        self.other.is_staff = True
        self.other.save()
        UserRole.objects.create(user=self.other, role="coach")
        self.client.force_login(self.other)
        for model in ("targetface", "scoringruleset", "rounddefinition"):
            self.assertEqual(self.client.get(f"/admin/scoring/{model}/add/").status_code, 403)
            obj = {"targetface": self.target, "scoringruleset": self.rules, "rounddefinition": self.round}[model]
            self.assertEqual(self.client.post(f"/admin/scoring/{model}/{obj.pk}/change/", {"name":"Changed"}).status_code, 403)
            self.assertEqual(self.client.post(f"/admin/scoring/{model}/", {"action":"deactivate", "_selected_action":obj.pk}).status_code, 403)
        self.other.user_permissions.add(*Permission.objects.filter(content_type__app_label="scoring", codename__in=["add_targetface", "change_targetface", "view_targetface"]))
        self.assertEqual(self.client.get("/admin/scoring/targetface/add/").status_code, 200)
        response = self.client.post("/admin/scoring/targetface/add/", dict(name="Admin junior", diameter_cm=60,
            layout="full", geometry=json.dumps(dict(spots=[[0,0,1]], rings=[.1,1])), active="on", _save="Save"))
        self.assertEqual(response.status_code, 302)
        junior = TargetFace.objects.get(name="Admin junior")
        self.client.post("/admin/scoring/targetface/", {"action":"deactivate", "_selected_action":junior.pk})
        junior.refresh_from_db()
        self.assertFalse(junior.active)
        self.client.post("/admin/scoring/targetface/", {"action":"duplicate", "_selected_action":junior.pk})
        self.assertTrue(TargetFace.objects.filter(name="Admin junior (copy)", active=False).exists())
        # Missing numeric fields should be normal form errors, never an admin exception.
        self.assertEqual(self.client.post("/admin/scoring/targetface/add/", {"name":"Incomplete"}).status_code, 200)

    def test_save_api_csrf_invalid_score_and_retry(self):
        session = self.start()
        self.client.force_login(self.user)
        url = reverse("scoring-save", args=[session.pk])
        payload = dict(key=str(uuid.uuid4()), version=1, action="shot", position=0, method="manual", symbol="X")
        for _ in range(2):
            result = self.client.post(url, json.dumps(payload), content_type="application/json")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["total"], 10)
        self.assertEqual(session.shots.count(), 1)
        result = self.client.post(url, json.dumps({**payload, "key":str(uuid.uuid4()), "version":2, "symbol":"99"}), content_type="application/json")
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(url, json.dumps(payload), content_type="application/json").status_code, 403)

    def test_equipment_selection_and_training_context(self):
        foreign = Equipment.objects.create(athlete=AthleteProfile.objects.create(account=self.other,
            display_name="Other", birth_date=date(1990,1,1), discipline="recurve"), kind="bow", division="recurve", name="Private bow")
        with self.assertRaises(Equipment.DoesNotExist):
            self.start(bow=foreign.pk)
        with self.assertRaises(ValidationError):
            s.start(self.user, self.athlete, dict(mode="custom", context="competition"))
        with self.assertRaises(ValidationError):
            s.stage_snapshot(self.target, self.rules, 18, 0, 3)
        with self.assertRaises(ValidationError):
            self.change(self.start(), "delete")
