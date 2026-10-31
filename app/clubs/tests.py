from datetime import date, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest import mock
from allauth.mfa.models import Authenticator
from allauth.account.internal.flows.login import record_authentication

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError, ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import AthleteProfile, UserRole
from . import services
from .models import Club, ClubClaim, KnownClubListing, ClubMembership, ClubRoleAssignment, ClubAuditEvent
from .storage import PrivateEvidenceStore, normalize_upload


def login_with_mfa(client, user):
    client.force_login(user)
    auth, _ = Authenticator.objects.get_or_create(user=user, type="totp", defaults={"data": {}})
    request = RequestFactory().get("/clubs/verification/")
    request.session = client.session
    request.user = user
    record_authentication(request, user, method="mfa", id=auth.pk, type="totp")
    request.session.save()


@override_settings(CLUBS_ENABLED=True)
class FoundationTests(TestCase):
    def login_reviewer(self, client):
        login_with_mfa(client, self.reviewer)

    def setUp(self):
        User = get_user_model()
        self.applicant = User.objects.create_user(username="applicant")
        self.other = User.objects.create_user(username="other")
        self.reviewer = User.objects.create_user(username="reviewer", is_staff=True)
        self.reviewer.user_permissions.add(Permission.objects.get(codename="review_club_claim"))
        self.data = dict(name="Gold Path Archers", country="Ireland", region="Dublin", town="Dublin",
            website="https://example.test", description="A club", visibility="public", timezone="Europe/Dublin",
            role_assertion="Club secretary", listing=None)

    def claim(self, **changes):
        return services.submit_claim(self.applicant, {**self.data, **changes})

    def evidence(self, claim, **changes):
        claim.refresh_from_db()
        return services.record_evidence(self.reviewer, claim.pk, dict(
            source_url="https://federation.example.test/clubs", contact_reference="Official secretary contacted",
            outcome="Authority confirmed", confirmed=True, checked_at=timezone.now() - timedelta(hours=1),
            expires_at=timezone.now() + timedelta(days=30), **changes), expected_version=claim.version)

    def approve(self, claim, **kwargs):
        claim.refresh_from_db()
        kwargs.setdefault("expected_version", claim.version)
        if claim.listing_id:
            kwargs.setdefault("target_confirmed", True)
            kwargs.setdefault("target_snapshot", services.listing_snapshot(claim))
        return services.decide_claim(self.reviewer, claim.pk, decision="approved", reason="Independent check completed", **kwargs)

    def test_submission_has_no_privileges(self):
        claim = self.claim()
        self.assertEqual(claim.state, "submitted")
        self.assertEqual(Club.objects.count(), 0)
        self.assertEqual(ClubRoleAssignment.objects.count(), 0)
        self.assertTrue(ClubAuditEvent.objects.filter(action="claim.submitted").exists())

    def test_requires_independent_current_positive_evidence(self):
        claim = self.claim()
        with self.assertRaises(ValidationError):
            self.approve(claim)
        evidence = self.evidence(claim)
        evidence.expires_at = timezone.now() - timedelta(seconds=1)
        evidence.save()
        with self.assertRaises(ValidationError):
            self.approve(claim)
        self.assertFalse(Club.objects.exists())

    def test_approval_atomic_and_replay_rejected(self):
        claim = self.claim()
        self.evidence(claim)
        approved = self.approve(claim)
        self.assertTrue(services.can_manage(self.applicant, approved.club))
        self.assertFalse(services.can_manage(self.other, approved.club))
        self.assertEqual(ClubMembership.objects.count(), 1)
        self.assertEqual(ClubRoleAssignment.objects.count(), 1)
        self.assertTrue(ClubAuditEvent.objects.filter(action="claim.approved", club=approved.club).exists())
        with self.assertRaises(ValidationError):
            self.approve(claim)
        self.assertEqual(Club.objects.count(), 1)

    def test_role_failure_rolls_back_every_approval_write(self):
        claim = self.claim()
        self.evidence(claim)
        with mock.patch("clubs.services.ClubRoleAssignment.objects.create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.approve(claim)
        claim.refresh_from_db()
        self.assertEqual(claim.state, "submitted")
        self.assertIsNone(claim.club_id)
        self.assertFalse(Club.objects.exists())
        self.assertFalse(ClubMembership.objects.exists())

    def test_staff_and_global_coach_have_no_verification_permission(self):
        self.other.is_staff = True
        self.other.save()
        UserRole.objects.create(user=self.other, role="coach")
        with self.assertRaises(PermissionDenied):
            services.decide_claim(self.other, self.claim().pk, decision="approved", reason="test")

    def test_self_approval_and_self_evidence_denied_even_superuser(self):
        claim = self.claim()
        self.applicant.is_staff = self.applicant.is_superuser = True
        self.applicant.save()
        with self.assertRaises(PermissionDenied):
            services.decide_claim(self.applicant, claim.pk, decision="approved", reason="test")
        with self.assertRaises(PermissionDenied):
            services.record_evidence(self.applicant, claim.pk, {})

    def test_public_visibility_and_private_enumeration(self):
        private = self.claim(visibility="private")
        self.evidence(private)
        club = self.approve(private).club
        self.assertEqual(self.client.get(reverse("clubs:profile", args=[club.slug])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("clubs:directory")), club.name)
        self.assertNotIn(club, services.public_clubs())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("clubs:manage", args=[club.pk])).status_code, 404)
        login_with_mfa(self.client, self.applicant)
        self.assertEqual(self.client.get(reverse("clubs:manage", args=[club.pk])).status_code, 200)
        club.status = "suspended"
        club.save()
        self.assertFalse(services.can_manage(self.applicant, club))

    def test_public_profile_and_suspension(self):
        claim = self.claim()
        self.evidence(claim)
        club = self.approve(claim).club
        self.assertContains(self.client.get(reverse("clubs:profile", args=[club.slug])), club.name)
        club.status = "archived"
        club.save()
        self.assertEqual(self.client.get(reverse("clubs:profile", args=[club.slug])).status_code, 404)

    def test_claim_isolation_and_queue_permission(self):
        claim = self.claim()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("clubs:claim", args=[claim.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("clubs:queue")).status_code, 403)
        self.client.force_login(self.applicant)
        self.assertContains(self.client.get(reverse("clubs:claim", args=[claim.pk])), claim.name)
        self.login_reviewer(self.client)
        self.assertContains(self.client.get(reverse("clubs:queue")), claim.name)
        self.assertEqual(self.client.get(reverse("clubs:review", args=[claim.pk])).status_code, 200)

    def test_duplicate_normalization_and_domain(self):
        listing = KnownClubListing.objects.create(name="GOLD-PATH ARCHERS", country="Ireland",
            source_url="https://official.example.test", reviewed_on=date.today())
        claim = self.claim()
        self.assertIn(listing, services.duplicate_candidates(self.reviewer, claim))
        self.evidence(claim)
        with self.assertRaises(ValidationError):
            self.approve(claim)
        self.assertFalse(Club.objects.exists())
        self.approve(claim, duplicates_reviewed=True)

    def test_known_listing_links_on_approval_and_second_claim_cannot_transfer(self):
        listing = KnownClubListing.objects.create(name=self.data["name"], country="Ireland",
            source_url="https://official.example.test", reviewed_on=date.today())
        first = self.claim(listing=listing)
        self.evidence(first)
        approved = self.approve(first)
        listing.refresh_from_db()
        self.assertEqual(listing.club_id, approved.club_id)
        second = self.claim(listing=listing)
        self.evidence(second)
        with self.assertRaises(ValidationError):
            self.approve(second, duplicates_reviewed=True)

    def test_information_request_and_rejection_require_reasons(self):
        claim = self.claim()
        for decision in ["information_requested", "under_review", "rejected"]:
            claim.refresh_from_db()
            services.decide_claim(self.reviewer, claim.pk, decision=decision, reason="More information needed", expected_version=claim.version)
        with self.assertRaises(ValidationError):
            services.decide_claim(self.reviewer, claim.pk, decision="approved", reason="test")
        self.assertFalse(Club.objects.exists())

    def test_applicant_response_retains_review_history(self):
        claim = self.claim()
        services.decide_claim(self.reviewer, claim.pk, decision="information_requested", reason="Provide your position", expected_version=claim.version)
        claim.refresh_from_db()
        services.respond_to_information_request(self.applicant, claim.pk, "I am the elected secretary", expected_version=claim.version)
        claim.refresh_from_db()
        self.assertEqual(claim.state, "submitted")
        self.assertEqual(claim.decisions.count(), 2)
        self.assertEqual(claim.decisions.first().reason, "Provide your position")
        with self.assertRaises(ValidationError):
            services.respond_to_information_request(self.applicant, claim.pk, "Replay")

    def test_evidence_private_expiring_download_and_audit(self):
        claim = self.claim()
        evidence = self.evidence(claim)
        with TemporaryDirectory() as root, override_settings(CLUB_EVIDENCE_BACKEND="local", CLUB_EVIDENCE_ROOT=root):
            store = PrivateEvidenceStore()
            evidence.storage_key = store.put(b"synthetic-image")
            evidence.save()
            url = reverse("clubs:evidence", args=[evidence.pk])
            for user in [self.applicant, self.other]:
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, 403)
            self.login_reviewer(self.client)
            response = self.client.get(url)
            self.assertEqual(response.content, b"synthetic-image")
            self.assertIn("no-store", response["Cache-Control"])
            self.assertIn("attachment", response["Content-Disposition"])
            self.assertTrue(ClubAuditEvent.objects.filter(action="evidence.downloaded", target_id=evidence.pk).exists())
            evidence.expires_at = timezone.now() - timedelta(seconds=1)
            evidence.save()
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_young_and_closed_applicants_denied(self):
        athlete = AthleteProfile.objects.create(account=self.applicant, display_name="Junior",
            birth_date=date(timezone.now().year - 15, 1, 1), discipline="recurve")
        with self.assertRaises(PermissionDenied):
            self.claim()
        athlete.birth_date = date(2000, 1, 1)
        athlete.closed_at = timezone.now()
        athlete.save()
        with self.assertRaises(PermissionDenied):
            self.claim()

    def test_feature_flag_denies_services_and_routes(self):
        with override_settings(CLUBS_ENABLED=False):
            self.assertEqual(self.client.get(reverse("clubs:directory")).status_code, 404)

    def test_csrf_protected_and_get_is_read_only(self):
        claim = self.claim()
        client = Client(enforce_csrf_checks=True)
        self.login_reviewer(client)
        url = reverse("clubs:review", args=[claim.pk])
        self.assertEqual(client.post(url, {"decision": "approved", "reason": "test"}).status_code, 403)
        self.assertEqual(client.get(url).status_code, 200)
        self.assertFalse(Club.objects.exists())

    def test_complete_http_submission_and_verification(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.applicant)
        url = reverse("clubs:apply")
        self.assertEqual(client.get(url).status_code, 200)
        response = client.post(url, {**self.data, "listing": "", "csrfmiddlewaretoken": client.cookies["csrftoken"].value})
        self.assertEqual(response.status_code, 302)
        claim = ClubClaim.objects.get()
        self.evidence(claim)
        self.login_reviewer(client)
        url = reverse("clubs:review", args=[claim.pk])
        client.get(url)
        claim.refresh_from_db()
        response = client.post(url, {"decision": "approved", "reason": "Verified through independent contact", "version": claim.version,
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value})
        self.assertEqual(response.status_code, 302)
        claim.refresh_from_db()
        self.assertEqual(claim.state, "approved")


class StorageTests(TestCase):
    def test_disabled_storage_and_traversal(self):
        with self.assertRaises(ImproperlyConfigured):
            PrivateEvidenceStore()
        with TemporaryDirectory() as root, override_settings(CLUB_EVIDENCE_BACKEND="local", CLUB_EVIDENCE_ROOT=root):
            with self.assertRaises(ValidationError):
                PrivateEvidenceStore().get("../../secret")

    def test_upload_reencodes_and_rejects_active_or_oversized_content(self):
        output = BytesIO()
        Image.new("RGB", (10, 10)).save(output, "PNG")
        upload = SimpleUploadedFile("test.png", output.getvalue() + b"private-trailer", content_type="image/png")
        normalized = normalize_upload(upload)
        self.assertTrue(normalized.startswith(b"\xff\xd8"))
        self.assertNotIn(b"private-trailer", normalized)
        with self.assertRaises(ValidationError):
            normalize_upload(SimpleUploadedFile("x.svg", b"<svg/>", content_type="image/svg+xml"))
        with self.assertRaises(ValidationError):
            normalize_upload(SimpleUploadedFile("x.png", b"bad", content_type="image/png"))
        with override_settings(CLUB_EVIDENCE_MAX_BYTES=1):
            with self.assertRaises(ValidationError):
                normalize_upload(SimpleUploadedFile("x.png", b"too big", content_type="image/png"))
