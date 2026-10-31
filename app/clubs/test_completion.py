"""Remaining M1 acceptance: private drafts, fresh MFA, retention and adapters."""
from datetime import timedelta
from io import BytesIO, StringIO
from tempfile import TemporaryDirectory
from unittest import mock
import time

from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, hotp_value
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import services
from .mfa import EncryptedMFAAdapter
from .models import ClubClaim, ClubAuditEvent, ClubSecurityEvent, EvidenceUpload, KnownClubListing
from .storage import PrivateEvidenceStore
from .tests import FoundationTests


@override_settings(CLUBS_ENABLED=True)
class CompletionTests(TestCase):
    setUp = FoundationTests.setUp
    claim = FoundationTests.claim
    evidence = FoundationTests.evidence
    approve = FoundationTests.approve
    login_reviewer = FoundationTests.login_reviewer

    def upload(self):
        output = BytesIO()
        Image.new("RGB", (8, 8)).save(output, "PNG")
        return SimpleUploadedFile("evidence.png", output.getvalue(), content_type="image/png")

    def test_partial_draft_private_edit_submit_and_no_review(self):
        draft = services.submit_claim(self.applicant, {**self.data, "country": "", "role_assertion": ""}, draft=True)
        self.assertNotIn(draft, services.review_queue(self.reviewer))
        self.login_reviewer(self.client)
        self.assertEqual(self.client.get(reverse("clubs:claim", args=[draft.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("clubs:draft", args=[draft.pk])).status_code, 404)
        with self.assertRaises(ValidationError):
            self.approve(draft)
        self.client.force_login(self.applicant)
        url = reverse("clubs:draft", args=[draft.pk])
        self.assertContains(self.client.get(url), "Save draft")
        response = self.client.post(url, {**self.data, "listing": "", "action": "submit"})
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.state, "submitted")
        self.assertEqual(ClubClaim.objects.count(), 1)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_http_draft_requires_complete_fields_on_submission(self):
        self.client.force_login(self.applicant)
        data = {**self.data, "country": "", "role_assertion": "", "listing": "", "action": "draft"}
        response = self.client.post(reverse("clubs:apply"), data)
        self.assertEqual(response.status_code, 302)
        draft = ClubClaim.objects.get()
        self.assertEqual(draft.state, "draft")
        response = self.client.post(reverse("clubs:draft", args=[draft.pk]), {**data, "action": "submit"})
        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.state, "draft")
        self.assertContains(response, "This field is required")

    def test_social_login_alone_cannot_review_or_write_admin(self):
        self.client.force_login(self.reviewer)
        session = self.client.session
        session["account_authentication_methods"] = [{"method": "socialaccount", "at": time.time(), "provider": "google"}]
        session.save()
        claim = self.claim()
        url = reverse("clubs:review", args=[claim.pk])
        response = self.client.post(url, {"decision": "rejected", "reason": "Bypass attempt"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("mfa_index"), response.url)
        claim.refresh_from_db()
        self.assertEqual(claim.state, "submitted")
        admin_url = reverse("admin:clubs_knownclublisting_add")
        self.assertEqual(self.client.get(admin_url).status_code, 403)

    def test_stale_mfa_and_deleted_authenticator_immediately_deny(self):
        self.login_reviewer(self.client)
        session = self.client.session
        session["account_authentication_methods"][0]["at"] -= 301
        session.save()
        self.assertIn(reverse("mfa_reauthenticate"), self.client.get(reverse("clubs:queue")).url)
        self.login_reviewer(self.client)
        Authenticator.objects.filter(user=self.reviewer).delete()
        self.assertIn(reverse("mfa_index"), self.client.get(reverse("clubs:queue")).url)

    @override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode("ascii")])
    def test_real_totp_reauthentication_unlocks_review(self):
        cache.clear()
        self.reviewer.email = "reviewer@example.test"
        self.reviewer.save()
        EmailAddress.objects.create(user=self.reviewer, email=self.reviewer.email, verified=True, primary=True)
        secret = "JBSWY3DPEHPK3PXP"
        authenticator = TOTP.activate(self.reviewer, secret).instance
        self.assertNotEqual(authenticator.data["secret"], secret)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.reviewer)
        queue_url = reverse("clubs:queue")
        challenge = self.client.get(queue_url)
        self.assertEqual(challenge.status_code, 302)
        self.assertEqual(self.client.get(challenge.url).status_code, 200)
        response = self.client.post(challenge.url, {"code": "bad-code",
            "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value})
        self.assertEqual(response.status_code, 200)
        code = format_hotp_value(hotp_value(secret, int(time.time()) // 30))
        response = self.client.post(challenge.url, {"code": code,
            "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(queue_url).status_code, 200)
        records = self.client.session["account_authentication_methods"]
        self.assertEqual(records[-1]["method"], "mfa")
        self.assertEqual(records[-1]["id"], authenticator.pk)

    def test_purge_dry_run_scrubs_expired_records_and_is_idempotent(self):
        claim = self.claim()
        evidence = self.evidence(claim)
        with TemporaryDirectory() as root, override_settings(CLUB_EVIDENCE_BACKEND="local", CLUB_EVIDENCE_ROOT=root):
            store = PrivateEvidenceStore()
            evidence.storage_key = store.put(b"private synthetic evidence")
            evidence.expires_at = timezone.now() - timedelta(seconds=1)
            evidence.save()
            output = StringIO()
            call_command("cleanup_club_evidence", stdout=output)
            self.assertIn("Eligible: 1", output.getvalue())
            self.assertTrue(store.get(evidence.storage_key))
            call_command("cleanup_club_evidence", apply=True, stdout=StringIO())
            evidence.refresh_from_db()
            self.assertIsNotNone(evidence.purged_at)
            self.assertEqual(evidence.source_url + evidence.contact_reference + evidence.outcome + evidence.storage_key, "")
            self.assertFalse(evidence.confirmed)
            self.assertTrue(ClubAuditEvent.objects.filter(action="evidence.purged", target_id=evidence.pk).exists())
            self.assertEqual(services.cleanup_evidence(dry_run=False), (0, 0))
            with self.assertRaises(ValidationError):
                self.approve(claim)

    def test_orphan_cleanup_preserves_current_upload_and_live_evidence(self):
        claim = self.claim()
        evidence = self.evidence(claim)
        with TemporaryDirectory() as root, override_settings(CLUB_EVIDENCE_BACKEND="local", CLUB_EVIDENCE_ROOT=root):
            store = PrivateEvidenceStore()
            orphan = EvidenceUpload.objects.create(storage_key=store.put(b"orphan"))
            recent = EvidenceUpload.objects.create(storage_key=store.put(b"upload in progress"))
            linked = EvidenceUpload.objects.create(storage_key=store.put(b"retained evidence"))
            evidence.storage_key = linked.storage_key
            evidence.save()
            EvidenceUpload.objects.exclude(pk=recent.pk).update(created_at=timezone.now() - timedelta(days=2))
            self.assertEqual(services.cleanup_evidence(dry_run=False), (0, 1))
            self.assertEqual(store.get(linked.storage_key), b"retained evidence")
            self.assertEqual(store.get(recent.storage_key), b"upload in progress")
            self.assertTrue(EvidenceUpload.objects.filter(pk=recent.pk).exists())
            with self.assertRaises(FileNotFoundError):
                store.get(orphan.storage_key)

    def test_failed_upload_rollback_keeps_intent_when_cleanup_fails(self):
        claim = self.claim()
        data = {"upload": self.upload()}
        with mock.patch("clubs.storage.PrivateEvidenceStore") as Store, mock.patch("clubs.services.record_evidence", side_effect=RuntimeError):
            Store.return_value.delete.side_effect = OSError
            with self.assertRaises(RuntimeError):
                services.upload_evidence(self.reviewer, claim.pk, data)
        self.assertEqual(EvidenceUpload.objects.count(), 1)

    def test_http_upload_is_private_and_storage_failure_is_recoverable(self):
        claim = self.claim()
        self.login_reviewer(self.client)
        url = reverse("clubs:review", args=[claim.pk])
        data = dict(action="evidence", source_url="https://official.example.test", contact_reference="Independent official",
            outcome="Synthetic confirmation", confirmed=True, checked_at=(timezone.now()-timedelta(hours=1)).isoformat(),
            expires_at=(timezone.now()+timedelta(days=1)).isoformat())
        response = self.client.post(url, {**data, "upload": self.upload()})
        self.assertContains(response, "Private evidence storage is unavailable")
        self.assertEqual(claim.evidence.count(), 0)
        with TemporaryDirectory() as root, override_settings(CLUB_EVIDENCE_BACKEND="local", CLUB_EVIDENCE_ROOT=root):
            response = self.client.post(url, {**data, "upload": self.upload()})
            self.assertEqual(response.status_code, 302)
            evidence = claim.evidence.get()
            self.assertTrue(PrivateEvidenceStore().get(evidence.storage_key).startswith(b"\xff\xd8"))
            self.assertFalse(EvidenceUpload.objects.exists())
            self.client.force_login(self.applicant)
            self.assertEqual(self.client.get(reverse("clubs:evidence", args=[evidence.pk])).status_code, 403)

    def test_unicode_and_federation_duplicate_hints(self):
        self.assertEqual(services.normalized("Árchers---東京"), "archers 東京")
        listing = KnownClubListing.objects.create(name="Different club name", country="Ireland", federation_number="IE-123",
            source_url="https://official.example.test", reviewed_on=timezone.now().date())
        claim = self.claim(federation_number="ie 123")
        self.assertIn(listing, services.duplicate_candidates(self.reviewer, claim))
        self.assertEqual(services.domain("https://WWW.Example.test/path"), "example.test")
        self.assertEqual(services.domain("https://[invalid"), "")

    def test_private_listing_not_exposed_by_application_form(self):
        claim = self.claim(visibility="private")
        self.evidence(claim)
        club = self.approve(claim).club
        listing = KnownClubListing.objects.create(name="Secret Known Club", country="Ireland", club=club,
            source_url="https://official.example.test", reviewed_on=timezone.now().date())
        self.client.force_login(self.other)
        response = self.client.get(reverse("clubs:apply"))
        self.assertNotContains(response, listing.name)
        self.assertEqual(self.client.post(reverse("clubs:apply"), {**self.data, "listing": listing.pk}).status_code, 200)
        self.assertEqual(ClubClaim.objects.count(), 1)

    def test_security_events_bounded_redacted_and_expired(self):
        cache.clear()
        self.client.force_login(self.other)
        for _ in range(3):
            response = self.client.get(reverse("clubs:queue") + "?token=never-log-this")
            self.assertEqual(response.status_code, 403)
        event = ClubSecurityEvent.objects.get(actor=self.other, action="access.denied")
        self.assertNotIn("never-log-this", str(event.__dict__))
        self.assertTrue(event.correlation_id)
        ClubSecurityEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=31))
        self.assertEqual(services.cleanup_security_events(dry_run=True), 1)
        self.assertTrue(ClubSecurityEvent.objects.exists())
        self.assertEqual(services.cleanup_security_events(dry_run=False), 1)
        self.assertFalse(ClubSecurityEvent.objects.exists())

    def test_web_audit_uses_server_generated_correlation(self):
        self.client.force_login(self.applicant)
        response = self.client.post(reverse("clubs:apply"), {**self.data, "listing": ""}, HTTP_X_REQUEST_ID="untrusted")
        self.assertEqual(response.status_code, 302)
        event = ClubAuditEvent.objects.get(action="claim.submitted")
        self.assertEqual(str(event.correlation_id), response["X-Request-ID"])
        self.assertEqual(event.source, "web")


class AdapterTests(TestCase):
    @override_settings(CLUBS_ENABLED=True, CLUBS_PRODUCTION=True, MFA_ENCRYPTION_KEYS=[], CLUB_EVIDENCE_BACKEND="disabled")
    def test_production_enablement_requires_security_configuration(self):
        from .checks import production_readiness
        self.assertEqual({error.id for error in production_readiness(None)}, {"clubs.E001", "clubs.E002", "clubs.E003"})
        with override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()], CLUB_EVIDENCE_BACKEND="azure",
                CLUB_EVIDENCE_AZURE_CONNECTION_STRING="synthetic", CLUB_EVIDENCE_AZURE_CONTAINER="private",
                CACHES={"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "synthetic_cache"}}):
            self.assertEqual(production_readiness(None), [])

    def test_mfa_key_ring_encryption_rotation_and_missing_key(self):
        adapter = EncryptedMFAAdapter()
        old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(MFA_ENCRYPTION_KEYS=[]):
            with self.assertRaises(ImproperlyConfigured):
                adapter.encrypt("synthetic secret")
        with override_settings(MFA_ENCRYPTION_KEYS=[old_key]):
            token = adapter.encrypt("synthetic secret")
            self.assertNotIn("synthetic secret", token)
        with override_settings(MFA_ENCRYPTION_KEYS=[new_key, old_key]):
            self.assertEqual(adapter.decrypt(token), "synthetic secret")

    @override_settings(CLUB_EVIDENCE_BACKEND="azure", CLUB_EVIDENCE_AZURE_CONNECTION_STRING="synthetic", CLUB_EVIDENCE_AZURE_CONTAINER="private-evidence")
    def test_azure_adapter_rejects_public_container_and_non_https(self):
        with mock.patch("azure.storage.blob.BlobServiceClient") as Client:
            container = Client.from_connection_string.return_value.get_container_client.return_value
            container.get_container_properties.return_value.public_access = "blob"
            with self.assertRaises(ImproperlyConfigured):
                PrivateEvidenceStore()
            container.get_container_properties.return_value.public_access = None
            container.url = "http://storage.example.test/container"
            with self.assertRaises(ImproperlyConfigured):
                PrivateEvidenceStore()
            container.url = "https://storage.example.test/container"
            store = PrivateEvidenceStore()
            key = store.put(b"synthetic")
            container.upload_blob.assert_called_once_with(key, b"synthetic", overwrite=False)
            from azure.core.exceptions import ResourceNotFoundError
            container.download_blob.side_effect = ResourceNotFoundError
            with self.assertRaises(FileNotFoundError):
                store.get(key)
            container.delete_blob.side_effect = ResourceNotFoundError
            store.delete(key)  # Safe cleanup retry.

    def test_served_storage_root_rejected(self):
        with TemporaryDirectory() as root, override_settings(CLUB_EVIDENCE_BACKEND="local", CLUB_EVIDENCE_ROOT=root, MEDIA_ROOT=root):
            with self.assertRaises(ImproperlyConfigured):
                PrivateEvidenceStore()
