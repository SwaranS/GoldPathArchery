"""Regression cases found during the draft PR review."""
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import services
from .storage import PrivateEvidenceStore
from .models import Club, ClubAuditEvent, KnownClubListing
from . import tests as foundation


@override_settings(CLUBS_ENABLED=True)
class ReviewFixTests(TestCase):
    setUp = foundation.FoundationTests.setUp
    claim = foundation.FoundationTests.claim
    evidence = foundation.FoundationTests.evidence
    approve = foundation.FoundationTests.approve
    login_reviewer = foundation.FoundationTests.login_reviewer

    def test_selected_listing_is_explicit_even_when_not_a_duplicate_hint(self):
        listing = KnownClubListing.objects.create(name="Unrelated directory identity", country="France",
            source_url="https://official.example.test/unique-source", reviewed_on=timezone.now().date())
        claim = self.claim(listing=listing)
        self.login_reviewer(self.client)
        response = self.client.get(reverse("clubs:review", args=[claim.pk]))
        self.assertContains(response, listing.name)
        self.assertContains(response, listing.source_url)
        self.assertContains(response, "target_confirmed")

    def test_stale_draft_cannot_overwrite_a_newer_save(self):
        claim = services.submit_claim(self.applicant, self.data, draft=True)
        self.client.force_login(self.applicant)
        url = reverse("clubs:draft", args=[claim.pk])
        data = {**self.data, "listing": "", "action": "draft", "version": 1}
        self.assertEqual(self.client.post(url, {**data, "name": "Newer saved name"}).status_code, 302)
        response = self.client.post(url, {**data, "name": "Obsolete tab name"})
        self.assertEqual(response.status_code, 409)
        claim.refresh_from_db()
        self.assertEqual(claim.name, "Newer saved name")

    def test_later_negative_verification_blocks_old_positive(self):
        claim = self.claim()
        self.evidence(claim)
        claim.refresh_from_db()
        services.record_evidence(self.reviewer, claim.pk, dict(source_url="https://official.example.test",
            contact_reference="More recent independent contact", outcome="Applicant authority denied",
            confirmed=False, checked_at=timezone.now()-timedelta(minutes=30), expires_at=timezone.now()+timedelta(days=1)), expected_version=claim.version)
        with self.assertRaises(ValidationError):
            self.approve(claim)
        self.assertFalse(Club.objects.exists())

    def test_expired_contact_payload_is_not_rendered_before_cleanup(self):
        claim = self.claim()
        evidence = self.evidence(claim)
        evidence.contact_reference = "Expired private contact payload"
        evidence.expires_at = timezone.now()-timedelta(seconds=1)
        evidence.save()
        self.login_reviewer(self.client)
        response = self.client.get(reverse("clubs:review", args=[claim.pk]))
        self.assertNotContains(response, evidence.contact_reference)

    def listing_claim(self):
        listing = KnownClubListing.objects.create(name=self.data["name"], country=self.data["country"],
            source_url="https://official.example.test", reviewed_on=timezone.now().date())
        claim = self.claim(listing=listing)
        self.evidence(claim)
        claim.refresh_from_db()
        return claim, listing

    def test_known_listing_approval_requires_explicit_bound_confirmation(self):
        claim, listing = self.listing_claim()
        args = dict(decision="approved", reason="Independently verified", expected_version=claim.version)
        with self.assertRaises(ValidationError):
            services.decide_claim(self.reviewer, claim.pk, **args)
        with self.assertRaises(services.ClaimConflict):
            services.decide_claim(self.reviewer, claim.pk, **args, target_confirmed=True, target_snapshot="tampered")
        self.assertFalse(Club.objects.exists())
        self.approve(claim)
        listing.refresh_from_db()
        self.assertIsNotNone(listing.club_id)

    def test_known_listing_changed_after_review_returns_conflict(self):
        claim, listing = self.listing_claim()
        self.login_reviewer(self.client)
        url = reverse("clubs:review", args=[claim.pk])
        page = self.client.get(url)
        snapshot = page.context["decision_form"].initial["target_snapshot"]
        KnownClubListing.objects.filter(pk=listing.pk).update(name="A changed target identity")
        response = self.client.post(url, dict(decision="approved", reason="Reviewed old target", version=claim.version,
            target_confirmed=True, target_snapshot=snapshot))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Club.objects.exists())
        listing.refresh_from_db()
        self.assertIsNone(listing.club_id)

    def test_confirmation_cannot_be_replayed_for_another_claim(self):
        first, listing = self.listing_claim()
        second = self.claim(listing=listing)
        self.evidence(second)
        second.refresh_from_db()
        with self.assertRaises(services.ClaimConflict):
            services.decide_claim(self.reviewer, second.pk, decision="approved", reason="Independent check",
                expected_version=second.version, target_confirmed=True, target_snapshot=services.listing_snapshot(first))
        self.assertFalse(Club.objects.exists())

    def test_stale_decision_cannot_approve_after_new_applicant_response(self):
        claim = self.claim()
        self.evidence(claim)
        claim.refresh_from_db()
        old_version = claim.version
        services.decide_claim(self.reviewer, claim.pk, decision="information_requested", reason="Clarify authority",
            expected_version=old_version)
        claim.refresh_from_db()
        services.respond_to_information_request(self.applicant, claim.pk, "Updated authority information",
            expected_version=claim.version)
        self.login_reviewer(self.client)
        response = self.client.post(reverse("clubs:review", args=[claim.pk]),
            dict(decision="approved", reason="Stale approval", version=old_version))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Club.objects.exists())
        claim.refresh_from_db()
        self.assertEqual(claim.state, "submitted")
        self.assertEqual(claim.decisions.count(), 2)

    def test_stale_information_response_does_not_answer_a_newer_question(self):
        claim = self.claim()
        services.decide_claim(self.reviewer, claim.pk, decision="information_requested", reason="First question",
            expected_version=claim.version)
        claim.refresh_from_db()
        old_version = claim.version
        services.decide_claim(self.reviewer, claim.pk, decision="information_requested", reason="New question",
            expected_version=old_version)
        self.client.force_login(self.applicant)
        response = self.client.post(reverse("clubs:claim", args=[claim.pk]), dict(response="Old answer", version=old_version))
        self.assertEqual(response.status_code, 409)
        claim.refresh_from_db()
        self.assertEqual(claim.state, "information_requested")
        self.assertEqual(claim.decisions.count(), 2)

    def test_missing_or_stale_service_version_cannot_mutate(self):
        claim = self.claim()
        for expected in (None, 0, True, claim.version + 1):
            with self.assertRaises(services.ClaimConflict):
                services.decide_claim(self.reviewer, claim.pk, decision="rejected", reason="Invalid version",
                    expected_version=expected)
        self.assertFalse(claim.decisions.exists())

    def test_listing_admin_audit_keeps_web_request_correlation(self):
        self.login_reviewer(self.client)
        response = self.client.post(reverse("admin:clubs_knownclublisting_add"), dict(
            name="Curated directory club", country="Ireland", region="", website="", federation_number="",
            source_url="https://official.example.test/clubs", reviewed_on=timezone.now().date().isoformat(), _save="Save"))
        self.assertEqual(response.status_code, 302)
        event = ClubAuditEvent.objects.get(action="listing.created")
        self.assertEqual(str(event.correlation_id), response["X-Request-ID"])
        self.assertEqual(event.source, "web")

    @override_settings(CLUB_EVIDENCE_BACKEND="azure", CLUB_EVIDENCE_AZURE_CONNECTION_STRING="synthetic", CLUB_EVIDENCE_AZURE_CONTAINER="private")
    def test_http_azure_endpoint_is_rejected_before_authenticated_network_io(self):
        with mock.patch("azure.storage.blob.BlobServiceClient") as Factory:
            container = Factory.from_connection_string.return_value.get_container_client.return_value
            container.url = "http://storage.example.test/private"
            container.get_container_properties.return_value.public_access = None
            with self.assertRaises(ImproperlyConfigured):
                PrivateEvidenceStore()
            container.get_container_properties.assert_not_called()
