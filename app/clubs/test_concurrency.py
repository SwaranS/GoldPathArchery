"""PostgreSQL-only lock tests. SQLite cannot establish these guarantees."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from . import services
from .models import Club, ClubClaim, ClubRoleAssignment, KnownClubListing


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
@override_settings(CLUBS_ENABLED=True)
class ApprovalConcurrencyTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.applicant = User.objects.create_user(username="applicant")
        self.reviewer = User.objects.create_user(username="reviewer", is_staff=True)
        self.reviewer.user_permissions.add(Permission.objects.get(codename="review_club_claim"))
        self.listing = KnownClubListing.objects.create(name="Race Club", country="Ireland",
            source_url="https://official.example.test", reviewed_on=timezone.now().date())

    def claim(self):
        claim = services.submit_claim(self.applicant, dict(name="Race Club", country="Ireland", region="",
            town="", website="", description="", visibility="private", timezone="Europe/Dublin",
            role_assertion="Secretary", listing=self.listing))
        services.record_evidence(self.reviewer, claim.pk, dict(source_url="https://official.example.test",
            contact_reference="Independent official contact", outcome="Confirmed", confirmed=True,
            checked_at=timezone.now() - timedelta(hours=1), expires_at=timezone.now() + timedelta(days=1)))
        return claim

    def race(self, claim_ids):
        barrier = Barrier(2)
        def approve(claim_id):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.reviewer.pk)
                barrier.wait(timeout=10)
                services.decide_claim(actor, claim_id, decision="approved", reason="Independently confirmed")
                return "approved"
            except ValidationError:
                return "denied"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(approve, claim_ids))
        self.assertCountEqual(outcomes, ["approved", "denied"])
        self.assertEqual(Club.objects.count(), 1)
        self.assertEqual(ClubRoleAssignment.objects.count(), 1)

    def test_same_claim_concurrent_approval(self):
        claim = self.claim()
        self.race([claim.pk, claim.pk])

    def test_competing_claims_for_same_listing(self):
        self.race([self.claim().pk, self.claim().pk])
        self.assertEqual(ClubClaim.objects.filter(state="approved").count(), 1)
