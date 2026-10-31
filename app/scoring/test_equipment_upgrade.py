"""Upgrade the existing equipment migration, including populated sight marks."""
from datetime import date
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

class AdvancedEquipmentUpgradeTests(TransactionTestCase):
    def test_populated_phase_one_records_are_unchanged(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        prior = [("scoring", "0002_equipment_revisions_and_sight_marks"), ("accounts", "0005_athleteprofile_disciplines")]
        executor.migrate(prior)
        try:
            apps = executor.loader.project_state(prior).apps
            athlete = apps.get_model("accounts", "AthleteProfile").objects.create(display_name="Legacy", birth_date=date(1990, 1, 1), discipline="recurve")
            equipment = apps.get_model("scoring", "Equipment").objects.create(athlete=athlete, kind="bow", name="Archived legacy", active=False, division="recurve")
            revision = apps.get_model("scoring", "EquipmentRevision").objects.create(equipment=equipment, number=1, name="Original", division="recurve", details="Do not infer measurements")
            arrow_set = apps.get_model("scoring", "Equipment").objects.create(athlete=athlete, kind="arrow_set", name="Legacy arrows")
            arrow = apps.get_model("scoring", "PhysicalArrow").objects.create(arrow_set=arrow_set, identifier="A1")
            mark = apps.get_model("scoring", "SightMark").objects.create(athlete=athlete, bow_revision=revision, distance=18, distance_unit="m", mark="4.2")
            recorded = {"bow": {"id": equipment.pk, "revision_id": revision.pk, "name": "Original"}}
            session = apps.get_model("scoring", "ScoringSession").objects.create(athlete=athlete, context="training", mode="custom", snapshot={"legacy": True}, equipment=recorded, status="completed")
            shot = apps.get_model("scoring", "ArrowShot").objects.create(session=session, position=0, symbol="X", points=10, is_x=True, arrow=arrow, arrow_snapshot={"id": arrow.pk})
            MigrationExecutor(connection).migrate(latest)
            from .models import Equipment, EquipmentRevision, PhysicalArrow, SightMark, ScoringSession, ArrowShot, EquipmentComponent, BowConfiguration
            self.assertFalse(Equipment.objects.get(pk=equipment.pk).active)
            self.assertEqual(EquipmentRevision.objects.get(pk=revision.pk).details, "Do not infer measurements")
            self.assertEqual(PhysicalArrow.objects.get(pk=arrow.pk).identifier, "A1")
            self.assertEqual(SightMark.objects.get(pk=mark.pk).bow_revision_id, revision.pk)
            self.assertIsNone(SightMark.objects.get(pk=mark.pk).configuration_revision_id)
            self.assertEqual(ScoringSession.objects.get(pk=session.pk).equipment, recorded)
            self.assertEqual(ArrowShot.objects.get(pk=shot.pk).arrow_snapshot, {"id": arrow.pk})
            self.assertEqual(EquipmentComponent.objects.count(), 0)
            self.assertEqual(BowConfiguration.objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate(latest)
