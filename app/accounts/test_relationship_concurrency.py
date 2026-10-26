"""These tests run on PostgreSQL and deliberately skip SQLite's no-op row locks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from . import relationships as service
from .models import AthleteProfile, CoachRelationship, GuardianLink, UserRole


@skipUnlessDBFeature("has_select_for_update")
class RelationshipConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="owner", email="owner@example.test"
        )
        self.recipient = get_user_model().objects.create_user(
            username="recipient", email="recipient@example.test"
        )
        EmailAddress.objects.create(
            user=self.recipient, email=self.recipient.email, verified=True
        )
        UserRole.objects.create(user=self.recipient, role="coach")
        self.athlete = AthleteProfile.objects.create(
            account=self.owner,
            display_name="Synthetic adult",
            birth_date=date(2000, 1, 1),
            discipline="barebow",
        )
        service.transition(self.athlete.pk)
        self.athlete.refresh_from_db()

    def race(self, functions):
        barrier = Barrier(len(functions))

        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                function()
                return "ok"
            except PermissionDenied:
                return "denied"
            except service.Conflict:
                return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(run, functions))

    def test_one_use_token_accepts_only_once_under_race(self):
        _, token = service.invite(
            self.owner,
            self.athlete.pk,
            "coach",
            self.recipient.email,
            self.athlete.version,
        )
        results = self.race([lambda: service.accept(self.recipient, token)] * 2)
        self.assertCountEqual(results, ["ok", "denied"])
        self.assertEqual(
            CoachRelationship.objects.filter(athlete=self.athlete).count(), 1
        )

    def test_concurrent_grant_forms_cannot_silently_overwrite(self):
        link = CoachRelationship.objects.create(
            athlete=self.athlete, coach=self.recipient
        )
        version = self.athlete.version
        results = self.race(
            [
                lambda: service.set_grant(
                    self.owner, self.athlete.pk, "coach", link.pk, "edit", version
                ),
                lambda: service.set_grant(
                    self.owner, self.athlete.pk, "coach", link.pk, "none", version
                ),
            ]
        )
        self.assertCountEqual(results, ["ok", "conflict"])
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.version, version + 1)

    def test_two_profiles_cannot_claim_same_login_concurrently(self):
        tokens = []
        for index in range(2):
            athlete = AthleteProfile.objects.create(
                display_name=f"Synthetic claim {index}",
                birth_date=date(2000, 1, 1),
                discipline="recurve",
            )
            GuardianLink.objects.create(
                athlete=athlete, parent=self.owner, access="view", managing=True
            )
            service.transition(athlete.pk)
            athlete.refresh_from_db()
            _, token = service.invite(
                self.owner, athlete.pk, "claim", self.recipient.email, athlete.version
            )
            tokens.append(token)
        results = self.race(
            [
                lambda token=token: service.accept(self.recipient, token)
                for token in tokens
            ]
        )
        self.assertCountEqual(results, ["ok", "denied"])
        self.assertEqual(
            AthleteProfile.objects.filter(account=self.recipient).count(), 1
        )
