"""All club reads and transitions are scoped here, including platform actions."""
from difflib import SequenceMatcher
from urllib.parse import urlsplit
import re
import unicodedata
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify

from accounts.permissions import eligible_actor
from .models import (
    Club, ClubClaim, KnownClubListing, ClubVerificationEvidence,
    ClubMembership, ClubRoleAssignment, ClubAuditEvent, ClubClaimDecision, EvidenceUpload,
)


def enabled():
    if not getattr(settings, "CLUBS_ENABLED", False):
        from django.http import Http404
        raise Http404


def require_applicant(actor):
    enabled()
    if not eligible_actor(actor, write=True):
        raise PermissionDenied


def is_reviewer(actor):
    return bool(eligible_actor(actor, write=True) and actor.is_staff
                and actor.has_perm("clubs.review_club_claim"))


def require_reviewer(actor):
    enabled()
    if not is_reviewer(actor):
        raise PermissionDenied


def public_clubs(query=""):
    enabled()
    return Club.objects.filter(status=Club.Status.ACTIVE, verified_at__isnull=False,
                               visibility=Club.Visibility.PUBLIC).filter(
        Q(name__icontains=query[:160]) | Q(town__icontains=query[:160])).order_by("name")


def public_club(slug):
    return get_object_or_404(public_clubs(), slug=slug)


def available_listings():
    return KnownClubListing.objects.filter(Q(club__isnull=True) | Q(
        club__visibility="public", club__status="active", club__verified_at__isnull=False)).order_by("name")


def claims_for(actor):
    require_applicant(actor)
    return ClubClaim.objects.filter(applicant=actor).order_by("-created_at")


def draft_for(actor, claim_id):
    require_applicant(actor)
    return get_object_or_404(ClubClaim, pk=claim_id, applicant=actor, state="draft")


def claim_for(actor, claim_id):
    require_applicant(actor)
    qs = ClubClaim.objects.filter(Q(applicant=actor) | ~Q(state="draft")) if is_reviewer(actor) else claims_for(actor)
    return get_object_or_404(qs, pk=claim_id)


def review_queue(actor):
    require_reviewer(actor)
    return ClubClaim.objects.exclude(state__in=["draft", "approved", "rejected"]).order_by("created_at")


def normalized(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def domain(value):
    try:
        return (urlsplit(value).hostname or "").encode("idna").decode("ascii").casefold().removeprefix("www.")
    except (ValueError, UnicodeError):
        return ""


def duplicate_candidates(actor, claim):
    require_reviewer(actor)
    results = []
    for item in [*Club.objects.all(), *KnownClubListing.objects.all()]:
        same_name = normalized(item.name) == normalized(claim.name)
        near_name = SequenceMatcher(None, normalized(item.name), normalized(claim.name)).ratio() >= .82
        same_location = normalized(item.country) == normalized(claim.country)
        same_domain = bool(domain(claim.website)) and domain(claim.website) == domain(item.website)
        same_federation = (isinstance(item, KnownClubListing) and bool(claim.federation_number.strip())
                           and normalized(claim.federation_number) == normalized(item.federation_number)
                           and same_location)
        if same_name or same_domain or same_federation or (near_name and same_location):
            results.append(item)
    return results


def audit(actor, claim, action, target_id=None):
    from .middleware import request_correlation
    correlation_id = request_correlation.get()
    ClubAuditEvent.objects.create(actor=actor, claim=claim, club=claim.club,
        action=action, target_id=target_id, correlation_id=correlation_id or uuid.uuid4(),
        source="web" if correlation_id else "service")


@transaction.atomic
def submit_claim(actor, data, *, claim_id=None, draft=False):
    require_applicant(actor)
    fields = {key: data[key] for key in (
        "name", "country", "region", "town", "website", "description",
        "visibility", "timezone", "role_assertion")}
    listing = data.get("listing")
    if listing:
        listing = get_object_or_404(available_listings(), pk=listing.pk)
    if claim_id:
        claim = get_object_or_404(ClubClaim.objects.select_for_update(), pk=claim_id, applicant=actor, state="draft")
        for key, value in fields.items():
            setattr(claim, key, value)
        claim.listing = listing
        claim.club = listing.club if listing else None
    else:
        claim = ClubClaim(applicant=actor, listing=listing, club=listing.club if listing else None, **fields)
    claim.federation_number = data.get("federation_number", "")
    claim.state = "draft" if draft else "submitted"
    claim.full_clean(exclude=[field for field in ("country", "role_assertion") if draft and not getattr(claim, field)])
    claim.save()
    audit(actor, claim, "claim.draft_saved" if draft else "claim.submitted")
    return claim


@transaction.atomic
def record_evidence(actor, claim_id, data, storage_key=""):
    require_reviewer(actor)
    claim = get_object_or_404(ClubClaim.objects.select_for_update(), pk=claim_id)
    if claim.applicant_id == actor.pk:
        raise PermissionDenied("An independent reviewer must record verification.")
    if claim.state in ("draft", "approved", "rejected"):
        raise ValidationError("Only submitted claims can be reviewed.")
    evidence = ClubVerificationEvidence(claim=claim, recorded_by=actor, storage_key=storage_key,
        **{key: data[key] for key in ("source_url", "contact_reference", "outcome", "confirmed", "checked_at", "expires_at")})
    evidence.full_clean()
    now = timezone.now()
    if evidence.checked_at > now or evidence.expires_at <= now or evidence.expires_at <= evidence.checked_at:
        raise ValidationError("Use a past contact check and a future evidence expiry.")
    from datetime import timedelta
    if evidence.expires_at > evidence.checked_at + timedelta(days=settings.CLUB_EVIDENCE_MAX_RETENTION_DAYS):
        raise ValidationError("Evidence expiry exceeds the configured retention limit.")
    evidence.save()
    if storage_key:
        EvidenceUpload.objects.filter(storage_key=storage_key).delete()
    audit(actor, claim, "evidence.recorded", evidence.pk)
    return evidence


def upload_evidence(actor, claim_id, data):
    """Persist intent before external I/O so crashes and deletion failures can be retried."""
    require_reviewer(actor)
    claim = claim_for(actor, claim_id)
    if claim.applicant_id == actor.pk:
        raise PermissionDenied
    from .storage import PrivateEvidenceStore, normalize_upload
    upload = data.get("upload")
    if not upload:
        return record_evidence(actor, claim_id, data)
    content = normalize_upload(upload)
    store = PrivateEvidenceStore()
    key = uuid.uuid4().hex + ".jpg"
    # Refuse a surrounding application transaction that could erase the upload intent
    # after the blob has already been written. Django TestCase's wrapper is supported.
    with transaction.atomic(durable=True):
        intent = EvidenceUpload.objects.create(storage_key=key)
    try:
        store.put(content, key)
        return record_evidence(actor, claim_id, data, key)
    except Exception:
        try:
            store.delete(key)
            intent.delete()
        except Exception:
            # Leave the durable intent for the cleanup command. Never log contact/file payloads.
            pass
        raise


def cleanup_evidence(*, dry_run=True, limit=100):
    """Operational task: purge expired private payloads, retain minimal audit references."""
    from datetime import timedelta
    from .storage import PrivateEvidenceStore
    now = timezone.now()
    expired = ClubVerificationEvidence.objects.filter(purged_at__isnull=True, expires_at__lte=now)
    orphans = EvidenceUpload.objects.filter(created_at__lte=now - timedelta(days=1))
    if dry_run:
        return expired.count(), orphans.count()
    store = None
    purged = removed = 0
    for evidence_id in list(expired.values_list("pk", flat=True)[:limit]):
        with transaction.atomic():
            evidence = ClubVerificationEvidence.objects.select_for_update().get(pk=evidence_id)
            if evidence.purged_at or evidence.expires_at > now:
                continue
            if evidence.storage_key:
                store = store or PrivateEvidenceStore()
                store.delete(evidence.storage_key)
            evidence.source_url = evidence.contact_reference = evidence.outcome = evidence.storage_key = ""
            evidence.confirmed = False
            evidence.recorded_by = None
            evidence.purged_at = now
            evidence.save()
            audit(None, evidence.claim, "evidence.purged", evidence.pk)
            purged += 1
    for intent_id in list(orphans.values_list("pk", flat=True)[:limit]):
        with transaction.atomic():
            intent = EvidenceUpload.objects.select_for_update().filter(pk=intent_id).first()
            if intent is None:
                continue
            if not ClubVerificationEvidence.objects.filter(storage_key=intent.storage_key).exists():
                store = store or PrivateEvidenceStore()
                store.delete(intent.storage_key)
                removed += 1
            intent.delete()
    return purged, removed


def cleanup_security_events(*, dry_run=True):
    from datetime import timedelta
    from .models import ClubSecurityEvent
    expired = ClubSecurityEvent.objects.filter(
        created_at__lt=timezone.now() - timedelta(days=settings.CLUB_SECURITY_RETENTION_DAYS))
    count = expired.count()
    if not dry_run:
        expired.delete()
    return count


@transaction.atomic
def decide_claim(actor, claim_id, *, decision, reason, duplicates_reviewed=False):
    require_reviewer(actor)
    claim = get_object_or_404(ClubClaim.objects.select_for_update(), pk=claim_id)
    if claim.applicant_id == actor.pk:
        raise PermissionDenied("You cannot decide your own claim.")
    if claim.state in ("draft", "approved", "rejected"):
        raise ValidationError("Only submitted claims can be reviewed.")
    if decision not in ("approved", "rejected", "under_review", "information_requested") or not reason.strip():
        raise ValidationError("Choose a valid decision and record a reason.")
    if len(reason) > 1000:
        raise ValidationError("Decision reason exceeds 1000 characters.")
    if decision == "approved":
        if not claim.applicant_id or not eligible_actor(claim.applicant, write=True):
            raise ValidationError("Applicant is no longer eligible.")
        # Serialize all first-identity creations, including competing new-club claims.
        # Existing permission row is stable and is never created by an applicant.
        from django.contrib.auth.models import Permission
        Permission.objects.select_for_update().get(content_type__app_label="clubs", codename="review_club_claim")
        if not claim.evidence.filter(confirmed=True, purged_at__isnull=True, expires_at__gt=timezone.now(), checked_at__lte=timezone.now(),
                                     recorded_by__isnull=False).exclude(recorded_by_id=claim.applicant_id).exists():
            raise ValidationError("Current independent confirmation is required.")
        listing = None
        if claim.listing_id:
            listing = KnownClubListing.objects.select_for_update().get(pk=claim.listing_id)
        if claim.club_id or (listing and listing.club_id):
            # Replacement/succession must use a future platform dispute/recovery case.
            raise ValidationError("An existing club requires platform recovery review; no control transfer here.")
        candidates = duplicate_candidates(actor, claim)
        others = [obj for obj in candidates if not (isinstance(obj, KnownClubListing) and obj.pk == claim.listing_id)]
        if others and not duplicates_reviewed:
            raise ValidationError("Review duplicate candidates before creating a separate identity.")
        club = Club(**{key: getattr(claim, key) for key in (
            "name", "country", "region", "town", "website", "description", "visibility", "timezone")},
            status="active", verified_at=timezone.now())
        club.slug = (slugify(club.name)[:150] or "club") + "-" + club.id.hex
        club.full_clean()
        club.save()
        claim.club = club
        if listing:
            listing.club = club
            listing.save(update_fields=["club"])
        membership = ClubMembership.objects.create(club=club, user=claim.applicant,
            athlete=getattr(claim.applicant, "athlete_profile", None))
        ClubRoleAssignment.objects.create(membership=membership, accepted_at=timezone.now(), verified_claim=claim)
        audit(actor, claim, "admin.bootstrapped", membership.pk)
        if others:
            audit(actor, claim, "duplicates.reviewed")
    claim.state = decision
    claim.reviewer = actor
    claim.decision_reason = reason.strip()
    claim.decided_at = timezone.now() if decision in ("approved", "rejected") else None
    claim.save()
    ClubClaimDecision.objects.create(claim=claim, actor=actor, state=decision, reason=reason.strip())
    audit(actor, claim, "claim." + decision)
    return claim


@transaction.atomic
def respond_to_information_request(actor, claim_id, response):
    require_applicant(actor)
    claim = get_object_or_404(ClubClaim.objects.select_for_update(), pk=claim_id, applicant=actor)
    if claim.state != "information_requested" or not response.strip() or len(response) > 1000:
        raise ValidationError("Respond to an open information request using at most 1000 characters.")
    claim.state = "submitted"
    claim.save(update_fields=["state"])
    ClubClaimDecision.objects.create(claim=claim, actor=actor, state="submitted", reason=response.strip())
    audit(actor, claim, "claim.resubmitted")
    return claim


def can_manage(actor, club):
    return bool(eligible_actor(actor, write=True) and club.status == "active" and club.verified_at
        and ClubRoleAssignment.objects.filter(membership__club=club, membership__user=actor,
            membership__active=True, role="admin", revoked_at__isnull=True,
            accepted_at__lte=timezone.now(), verified_claim__state="approved").exists())


def managed_club(actor, club_id):
    enabled()
    club = get_object_or_404(Club, pk=club_id)
    if not can_manage(actor, club):
        from django.http import Http404
        raise Http404
    return club


def evidence_for_download(actor, evidence_id):
    require_reviewer(actor)
    evidence = get_object_or_404(ClubVerificationEvidence, pk=evidence_id, purged_at__isnull=True, expires_at__gt=timezone.now())
    if evidence.claim.applicant_id == actor.pk:
        raise PermissionDenied
    return evidence


def evidence_list(actor, claim):
    require_reviewer(actor)
    if claim.applicant_id == actor.pk:
        return ClubVerificationEvidence.objects.none()
    return claim.evidence.filter(purged_at__isnull=True).order_by("created_at")
