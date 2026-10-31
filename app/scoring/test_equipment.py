from copy import deepcopy
from datetime import date
from decimal import Decimal
import uuid

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AthleteProfile, CoachRelationship, GuardianLink, User
from . import equipment_services as e, services as s
from .forms import EquipmentForm, SightMarkForm
from .models import Equipment, EquipmentRevision, PhysicalArrow, SightMark, TargetFace, ScoringRuleSet


class EquipmentTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner")
        self.parent = User.objects.create_user(username="parent")
        self.coach = User.objects.create_user(username="coach")
        self.stranger = User.objects.create_user(username="stranger")
        self.athlete = AthleteProfile.objects.create(account=self.owner, display_name="Selected archer",
            birth_date=date(1990, 1, 1), discipline="recurve")
        self.other = AthleteProfile.objects.create(account=self.stranger, display_name="Other athlete",
            birth_date=date(1990, 1, 1), discipline="recurve")
        self.bow = self.equipment("bow", name="Range bow", division="recurve", draw_weight="32", draw_weight_unit="lb")
        self.arrows = self.equipment("arrow_set", name="Outdoor shafts", spine="500", length="28", length_unit="in")
        self.url = reverse("scoring-equipment", args=[self.athlete.pk])
        self.client.force_login(self.owner)

    def equipment(self, kind, **data):
        return e.save_equipment(self.owner, self.athlete.pk, dict(kind=kind, **data))

    def revise(self, item, **changes):
        old = e.current_revision(item)
        data = {field: getattr(old, field) for field in e.SPEC_FIELDS}
        return e.save_equipment(self.owner, self.athlete.pk, {"kind": item.kind, **data, **changes},
            item_id=item.pk, expected_revision=old.pk)

    def arrow(self, identifier="A7", item=None):
        return e.save_arrow(self.owner, self.athlete.pk, dict(arrow_set=(item or self.arrows).pk,
            identifier=identifier, notes="Blue nock"))

    def mark(self, **changes):
        return e.save_mark(self.owner, self.athlete.pk, {"bow_revision": e.current_revision(self.bow).pk,
            "arrow_revision": e.current_revision(self.arrows).pk, "distance": "18", "distance_unit": "m",
            "mark": "5.25 / reference", **changes})

    def start(self):
        target = TargetFace.objects.create(name="Test face", diameter_cm=40,
            geometry=dict(spots=[[0, 0, 1]], rings=[.1, 1]))
        rules = ScoringRuleSet.objects.create(name="Test rules", rules=dict(zones=[dict(radius=1, symbol="10", points=10)]))
        return s.start(self.owner, self.athlete, dict(mode="custom", context="training", target=target.pk,
            rules=rules.pk, distance_m=18, ends=1, arrows_per_end=3, bow=self.bow.pk, arrow_set=self.arrows.pk))

    def shot(self, session, position, arrow):
        session.refresh_from_db()
        return s.mutate(self.owner, session.pk, dict(action="shot", position=position, method="manual", symbol="10",
            arrow=arrow.pk, key=str(uuid.uuid4()), version=session.version))

    def test_structured_equipment_and_model_validation(self):
        revision = e.current_revision(self.bow)
        self.assertEqual(revision.draw_weight, Decimal("32"))
        for division in ("recurve", "compound", "barebow"):
            self.equipment("bow", name=division, division=division)
        for changes in (dict(division=""), dict(draw_weight="-1", draw_weight_unit="lb"),
                dict(draw_weight="32"), dict(draw_weight_unit="lb"), dict(draw_weight="NaN", draw_weight_unit="lb"),
                dict(draw_length="28", draw_length_unit="m"), dict(handedness="ambidextrous"), dict(spine="500")):
            data = dict(kind="bow", name="Invalid", division="recurve", **{})
            data.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                e.save_equipment(self.owner, self.athlete.pk, data)
        for field, unit in (("length", "in"), ("point_weight", "gr"), ("shaft_diameter", "mm")):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.equipment("arrow_set", name="Bad set", **{field: 0, field + "_unit": unit})
        with self.assertRaises(ValidationError):
            Equipment(athlete=self.athlete, kind="bow", name="Missing division").full_clean()
        form = EquipmentForm(dict(kind="bow", name="Missing division"))
        self.assertFalse(form.is_valid())
        self.assertIn("division", form.errors)

    def test_revisions_preserve_identity_history_and_reject_stale_edits(self):
        arrow = self.arrow()
        session = self.start()
        self.shot(session, 0, arrow)
        session.refresh_from_db()
        original = deepcopy(session.equipment)
        shot_snapshot = deepcopy(session.shots.get().arrow_snapshot)
        old = e.current_revision(self.bow)
        self.revise(self.bow, name="Updated bow", draw_weight=Decimal("34"))
        self.revise(self.arrows, name="New set name", spine="450")
        session.refresh_from_db()
        self.assertEqual(session.equipment, original)
        self.assertEqual(session.shots.get().arrow_snapshot, shot_snapshot)
        self.assertEqual(old.draw_weight, Decimal("32"))
        self.assertEqual(PhysicalArrow.objects.get(pk=arrow.pk).arrow_set_id, self.arrows.pk)
        newer = self.start()
        self.assertEqual(newer.equipment["bow"]["revision"], 2)
        self.assertEqual(newer.equipment["arrow_set"]["id"], self.arrows.pk)
        self.shot(newer, 0, arrow)
        self.assertEqual(newer.shots.get().arrow_id, arrow.pk)
        self.assertEqual(len(s.arrow_comparisons([session, newer])), 2)  # bow revisions split conditions
        with self.assertRaises(ValidationError):
            old.name = "Rewrite history"
            old.save()
        with self.assertRaises(ValidationError):
            e.save_equipment(self.owner, self.athlete.pk, dict(kind="bow", name="Stale", division="recurve"),
                item_id=self.bow.pk, expected_revision=old.pk)
        self.assertEqual(self.bow.revisions.count(), 2)
        same = e.current_revision(self.bow)
        self.revise(self.bow)
        self.assertEqual(e.current_revision(self.bow).pk, same.pk)

    def test_arrow_identifier_scope_and_archive_restore(self):
        arrow = self.arrow()
        archived = self.arrow("B8")
        with self.assertRaises(ValidationError):
            self.arrow()
        second = self.equipment("arrow_set", name="Second set")
        other_arrow = self.arrow(item=second)
        self.assertNotEqual(arrow.pk, other_arrow.pk)
        for identifier in ("", "#7", "A 7", "a-7"):
            with self.subTest(identifier=identifier), self.assertRaises(ValidationError):
                self.arrow(identifier)
        e.set_active(self.owner, self.athlete.pk, "arrow", archived.pk, False)
        e.set_active(self.owner, self.athlete.pk, "equipment", self.arrows.pk, False)
        with self.assertRaises(ValidationError):
            e.set_active(self.owner, self.athlete.pk, "arrow", archived.pk, True)
        e.set_active(self.owner, self.athlete.pk, "equipment", self.arrows.pk, True)
        archived.refresh_from_db()
        arrow.refresh_from_db()
        self.assertFalse(archived.active)
        self.assertTrue(arrow.active)
        e.set_active(self.owner, self.athlete.pk, "arrow", archived.pk, True)
        archived.refresh_from_db()
        self.assertTrue(archived.active)

    def test_archive_selection_and_preserved_reports(self):
        arrow = self.arrow()
        session = self.start()
        self.shot(session, 0, arrow)
        e.set_active(self.owner, self.athlete.pk, "equipment", self.arrows.pk, False)
        with self.assertRaises(ObjectDoesNotExist):
            self.start()
        with self.assertRaises(ObjectDoesNotExist):
            self.shot(session, 1, arrow)
        self.shot(session, 0, arrow)  # retain original identity while correcting
        self.assertEqual(s.arrow_comparisons([session])[0]["count"], 1)
        e.set_active(self.owner, self.athlete.pk, "equipment", self.arrows.pk, True)
        e.set_active(self.owner, self.athlete.pk, "arrow", arrow.pk, False)
        with self.assertRaises(ObjectDoesNotExist):
            self.shot(session, 1, arrow)
        self.revise(self.bow, division="compound")
        with self.assertRaises(ValidationError):
            self.start()

    def test_set_revisions_keep_arrow_report_continuity_and_distinct_labels(self):
        arrow = self.arrow("7")
        first = self.start()
        self.shot(first, 0, arrow)
        self.revise(self.arrows, name="Renamed set", spine="450")
        self.shot(first, 1, arrow)
        self.assertEqual(first.shots.get(position=1).arrow_snapshot["set_name"], "Outdoor shafts")
        second = self.start()
        self.shot(second, 0, arrow)
        rows = s.arrow_comparisons([first, second])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 3)
        another = self.equipment("arrow_set", name="Renamed set")
        other_arrow = self.arrow("7", item=another)
        self.arrows = another
        third = self.start()
        self.shot(third, 0, other_arrow)
        rows = s.arrow_comparisons([first, second, third])
        self.assertEqual({row["set_id"] for row in rows}, {arrow.arrow_set_id, another.pk})
        report = self.client.get(reverse("scoring-history", args=[self.athlete.pk]))
        self.assertContains(report, f"set #{another.pk}")
        self.assertContains(report, f"set #{arrow.arrow_set_id}")
        self.assertContains(report, "revision 1")
        e.set_active(self.owner, self.athlete.pk, "arrow", arrow.pk, False)
        self.assertContains(self.client.get(reverse("scoring-session", args=[first.pk])), 'data-active="false"')

    def test_sight_marks_current_and_historical_setup_and_range_order(self):
        mark = self.mark()
        self.mark(distance="10", distance_unit="yd", mark="Near")
        rows = e.workspace(self.owner, self.athlete.pk, bow=self.bow.pk)["marks"]
        self.assertEqual(rows[0].mark, "Near")
        self.assertTrue(rows[1].current_setup)
        self.revise(self.arrows, spine="450")
        self.assertFalse(e.workspace(self.owner, self.athlete.pk)["marks"][0].current_setup)
        self.assertEqual(SightMark.objects.get(pk=mark.pk).arrow_revision.number, 1)
        with self.assertRaises(ValidationError):
            self.mark(arrow_revision=mark.arrow_revision_id)
        for changes in (dict(distance="0"), dict(distance="-1"), dict(distance="Infinity"),
                        dict(distance_unit="ft"), dict(mark=" "), dict(bow_revision=None)):
            data = dict(bow_revision=e.current_revision(self.bow).pk, distance="18", distance_unit="m", mark="5")
            data.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                e.save_mark(self.owner, self.athlete.pk, data)
        self.mark(arrow_revision=None, date=date(2026, 10, 1), sight_extension="6", windage="0", notes="Calm")
        e.set_active(self.owner, self.athlete.pk, "mark", mark.pk, False)
        e.set_active(self.owner, self.athlete.pk, "mark", mark.pk, True)

    def test_cross_athlete_equipment_arrow_revision_and_mark_references(self):
        foreign = e.save_equipment(self.stranger, self.other.pk, dict(kind="bow", name="Private", division="recurve"))
        revision = e.current_revision(foreign)
        with self.assertRaises(ObjectDoesNotExist):
            self.mark(bow_revision=revision.pk)
        with self.assertRaises(ObjectDoesNotExist):
            e.save_equipment(self.owner, self.athlete.pk, dict(kind="bow", name="Steal", division="recurve"),
                item_id=foreign.pk, expected_revision=revision.pk)
        with self.assertRaises(ObjectDoesNotExist):
            e.set_active(self.stranger, self.other.pk, "equipment", self.bow.pk, False)
        mark = self.mark()
        with self.assertRaises(ObjectDoesNotExist):
            e.set_active(self.stranger, self.other.pk, "mark", mark.pk, False)
        with self.assertRaises(ObjectDoesNotExist):
            e.set_active(self.stranger, self.other.pk, "arrow", self.arrow().pk, False)
        with self.assertRaises(ValidationError):
            SightMark(athlete=self.athlete, bow_revision=revision, distance=18, distance_unit="m", mark="5").full_clean()
        self.assertFalse(SightMarkForm(dict(bow_revision=revision.pk, distance=18, distance_unit="m", mark="5"), athlete=self.athlete).is_valid())
        with self.assertRaises(ObjectDoesNotExist):
            e.save_arrow(self.stranger, self.other.pk, dict(arrow_set=self.arrows.pk, identifier="A7"))
        self.assertEqual(self.client.get(self.url, {"bow": foreign.pk}).status_code, 404)

    def test_owner_parent_coach_read_only_revocation_and_closed_profiles(self):
        link = GuardianLink.objects.create(athlete=self.athlete, parent=self.parent, access="edit", adult_grant=True)
        coach_link = CoachRelationship.objects.create(athlete=self.athlete, coach=self.coach, plan_edit=True)
        self.client.force_login(self.parent)
        self.assertContains(self.client.get(reverse("athlete-equipment-section", args=[self.athlete.pk, "configurations"])), "Save equipment")
        e.save_arrow(self.parent, self.athlete.pk, dict(arrow_set=self.arrows.pk, identifier="Parent7"))
        link.access = "view"
        link.save()
        for user in (self.parent, self.coach):
            self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertContains(response, "Equipment is read-only")
            self.assertNotContains(response, "Save equipment")
            self.assertNotContains(response, "Save arrow")
            self.assertNotContains(response, "Save sight mark")
            self.assertNotContains(response, "Revise Range bow")
            for action in ("equipment", "arrow", "mark", "revise", "archive", "restore"):
                self.assertEqual(self.client.post(self.url, dict(action=action, item=self.bow.pk)).status_code, 404)
            with self.assertRaises(PermissionDenied):
                e.save_arrow(user, self.athlete.pk, dict(arrow_set=self.arrows.pk, identifier="Forbidden"))
        link.revoked_at = coach_link.revoked_at = timezone.now()
        link.save()
        coach_link.save()
        for user in (self.parent, self.coach, self.stranger):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.owner)
        self.athlete.closed_at = timezone.now()
        self.athlete.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        with self.assertRaises(PermissionDenied):
            e.set_active(self.owner, self.athlete.pk, "equipment", self.bow.pk, False)

    def test_managing_parent_and_junior_read_only(self):
        junior = AthleteProfile.objects.create(display_name="Junior", birth_date=date(2012, 1, 1), discipline="barebow")
        link = GuardianLink.objects.create(athlete=junior, parent=self.parent, managing=True)
        e.save_equipment(self.parent, junior.pk, dict(kind="bow", name="Junior bow", division="barebow"))
        junior.account = User.objects.create_user(username="junior")
        junior.save()
        with self.assertRaises(PermissionDenied):
            e.save_equipment(junior.account, junior.pk, dict(kind="arrow_set", name="Forbidden"))
        self.client.force_login(junior.account)
        self.assertContains(self.client.get(reverse("athlete-equipment", args=[junior.pk])), "Equipment is read-only")
        link.managing = False
        link.save()
        with self.assertRaises(PermissionDenied):
            e.save_equipment(self.parent, junior.pk, dict(kind="arrow_set", name="Forbidden"))

    def test_shared_navigation_forms_errors_and_archive_controls(self):
        alias = reverse("athlete-equipment", args=[self.athlete.pk])
        response = self.client.get(reverse("athlete-detail", args=[self.athlete.pk]))
        self.assertContains(response, f'href="{alias}">Equipment</a>')
        for url in (self.url, alias):
            page = self.client.get(url)
            self.assertContains(page, "SELECTED ATHLETE")
            self.assertContains(page, "Selected archer")
            self.assertContains(page, "My Equipment")
            self.assertNotContains(page, "Coming soon")
        invalid = self.client.post(alias, dict(action="equipment", kind="bow", name="Keep my input"))
        self.assertContains(invalid, "Keep my input")
        self.assertContains(invalid, "Select a bow division")
        saved = self.client.post(alias, dict(action="equipment", kind="arrow_set", name="Indoor set"))
        self.assertRedirects(saved, self.url)
        item = Equipment.objects.get(name="Indoor set")
        arrow = self.client.post(alias, dict(action="arrow", arrow_set=item.pk, identifier="C9", notes="Indoor"))
        self.assertRedirects(arrow, self.url)
        physical = item.arrows.get()
        for action in ("archive", "restore"):
            self.assertRedirects(self.client.post(alias, dict(action=action, entity="arrow", item=physical.pk)), self.url)
        revision = e.current_revision(self.bow)
        result = self.client.post(alias, dict(action="revise", item=self.bow.pk, expected_revision=revision.pk,
            kind="bow", name="Revised through form", division="recurve"))
        self.assertRedirects(result, self.url)
        self.assertEqual(self.bow.revisions.count(), 2)
        self.assertEqual(self.client.post(alias, dict(action="revise", kind="bow", name="No target", division="recurve")).status_code, 404)
        mark = self.client.post(alias, dict(action="mark", bow_revision=e.current_revision(self.bow).pk,
            distance="18", distance_unit="m", mark="5.3"))
        self.assertRedirects(mark, self.url)
        self.assertContains(self.client.get(reverse("athlete-equipment-section", args=[self.athlete.pk, "sight-marks"])), "5.3")
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(alias, dict(action="archive", item=item.pk)).status_code, 403)


class EquipmentMigrationTests(TransactionTestCase):
    def test_legacy_records_arrow_identity_and_snapshots_preserved(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate([("scoring", "0001_initial")])
        try:
            apps = executor.loader.project_state([("scoring", "0001_initial"), ("accounts", "0005_athleteprofile_disciplines")]).apps
            athlete = apps.get_model("accounts", "AthleteProfile").objects.create(
                display_name="Legacy athlete", birth_date=date(1990, 1, 1), discipline="recurve")
            EquipmentOld = apps.get_model("scoring", "Equipment")
            bow = EquipmentOld.objects.create(athlete=athlete, kind="bow", name="Legacy bow", division="",
                details="Possibly 32lb? Do not parse this", active=False)
            arrow_set = EquipmentOld.objects.create(athlete=athlete, kind="arrow_set", name="Legacy set", details="500 maybe")
            arrow = apps.get_model("scoring", "PhysicalArrow").objects.create(arrow_set=arrow_set, identifier="#7 old", active=False)
            original = dict(bow=dict(id=bow.pk, name="Earlier bow", division="recurve", details="Earlier setup"))
            session = apps.get_model("scoring", "ScoringSession").objects.create(athlete=athlete, context="training",
                mode="custom", snapshot=dict(legacy=True), equipment=original)
            shot = apps.get_model("scoring", "ArrowShot").objects.create(session=session, position=0, symbol="M", points=0,
                arrow=arrow, arrow_snapshot=dict(id=arrow.pk, identifier="#7 old", set_id=arrow_set.pk, set_name="Legacy set"))
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            revision = EquipmentRevision.objects.get(equipment_id=bow.pk)
            self.assertEqual(revision.details, "Possibly 32lb? Do not parse this")
            self.assertEqual(revision.division, "")
            self.assertIsNone(revision.draw_weight)
            self.assertEqual(revision.brand, "")
            self.assertEqual(EquipmentRevision.objects.get(equipment_id=arrow_set.pk).spine, "")
            self.assertFalse(Equipment.objects.get(pk=bow.pk).active)
            self.assertFalse(PhysicalArrow.objects.get(pk=arrow.pk).active)
            from .models import ScoringSession, ArrowShot
            self.assertEqual(ScoringSession.objects.get(pk=session.pk).equipment, original)
            self.assertEqual(ArrowShot.objects.get(pk=shot.pk).arrow_id, arrow.pk)
            self.assertEqual(ArrowShot.objects.get(pk=shot.pk).arrow_snapshot["identifier"], "#7 old")
        finally:
            MigrationExecutor(connection).migrate(latest)
