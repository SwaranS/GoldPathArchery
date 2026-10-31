from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, ValidationError
from azure.core.exceptions import AzureError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from . import services
from .forms import ClaimForm, DecisionForm, EvidenceForm, InformationResponseForm
from .storage import PrivateEvidenceStore
from .security import admin_session_redirect, review_session_redirect


@never_cache
@require_GET
def directory(request):
    return render(request, "clubs/directory.html", {"clubs": services.public_clubs(request.GET.get("q", ""))[:100]})


@never_cache
@require_GET
def profile(request, slug):
    return render(request, "clubs/profile.html", {"club": services.public_club(slug)})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def apply(request, claim_id=None):
    services.require_applicant(request.user)
    existing = services.draft_for(request.user, claim_id) if claim_id else None
    draft = request.POST.get("action") == "draft"
    form = ClaimForm(request.POST if request.method == "POST" else None, instance=existing, partial=draft)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            claim = services.submit_claim(request.user, form.cleaned_data, claim_id=claim_id, draft=draft,
                expected_version=form.cleaned_data.get("version"))
            return redirect("clubs:claim", claim_id=claim.pk)
        except services.ClaimConflict as exc:
            form.add_error(None, exc)
            status = 409
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "clubs/apply.html", {"form": form, "claims": services.claims_for(request.user)}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def claim(request, claim_id):
    claim = services.claim_for(request.user, claim_id)
    if claim.applicant_id != request.user.pk:
        challenge = review_session_redirect(request)
        if challenge is not None:
            return challenge
    form = InformationResponseForm(request.POST or None, claim=claim)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            services.respond_to_information_request(request.user, claim_id, form.cleaned_data["response"],
                expected_version=form.cleaned_data["version"])
            return redirect("clubs:claim", claim_id=claim_id)
        except services.ClaimConflict as exc:
            form.add_error(None, exc)
            status = 409
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "clubs/claim.html", {"claim": claim, "form": form}, status=status)


@never_cache
@login_required
@require_GET
def queue(request):
    challenge = review_session_redirect(request)
    if challenge is not None:
        return challenge
    return render(request, "clubs/queue.html", {"claims": services.review_queue(request.user)})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def review(request, claim_id):
    challenge = review_session_redirect(request)
    if challenge is not None:
        return challenge
    claim = services.claim_for(request.user, claim_id)
    decision_form, evidence_form = DecisionForm(claim=claim), EvidenceForm(claim=claim)
    status = 200
    if request.method == "POST":
        if request.POST.get("action") == "evidence":
            evidence_form = EvidenceForm(request.POST, request.FILES, claim=claim)
            if evidence_form.is_valid():
                try:
                    services.upload_evidence(request.user, claim_id, evidence_form.cleaned_data,
                        expected_version=evidence_form.cleaned_data["version"])
                    return redirect("clubs:review", claim_id=claim_id)
                except services.ClaimConflict as exc:
                    evidence_form.add_error(None, exc)
                    status = 409
                except ValidationError as exc:
                    evidence_form.add_error(None, exc)
                except (ImproperlyConfigured, OSError, AzureError):
                    evidence_form.add_error(None, "Private evidence storage is unavailable. No evidence was recorded; try again later.")
        else:
            decision_form = DecisionForm(request.POST, claim=claim)
            if decision_form.is_valid():
                try:
                    data = dict(decision_form.cleaned_data)
                    data["expected_version"] = data.pop("version")
                    services.decide_claim(request.user, claim_id, **data)
                    return redirect("clubs:review", claim_id=claim_id)
                except services.ClaimConflict as exc:
                    decision_form.add_error(None, exc)
                    status = 409
                except ValidationError as exc:
                    decision_form.add_error(None, exc)
    # Applicant-reviewers cannot see evidence/contact details for their own claims.
    return render(request, "clubs/review.html", {
        "claim": claim, "decision_form": decision_form, "evidence_form": evidence_form,
        "candidates": services.duplicate_candidates(request.user, claim),
        "evidence": services.evidence_list(request.user, claim),
    }, status=status)


@never_cache
@login_required
@require_GET
def evidence_download(request, evidence_id):
    challenge = review_session_redirect(request)
    if challenge is not None:
        return challenge
    evidence = services.evidence_for_download(request.user, evidence_id)
    if not evidence.storage_key:
        raise Http404
    try:
        content = PrivateEvidenceStore().get(evidence.storage_key)
    except FileNotFoundError:
        raise Http404 from None
    except (ImproperlyConfigured, OSError, AzureError):
        return HttpResponse("Private evidence storage is temporarily unavailable.", status=503)
    services.audit(request.user, evidence.claim, "evidence.downloaded", evidence.pk)
    response = HttpResponse(content, content_type="image/jpeg")
    response["Content-Disposition"] = 'attachment; filename="verification-evidence.jpg"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@never_cache
@login_required
@require_GET
def manage(request, club_id):
    club = services.managed_club(request.user, club_id)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    return render(request, "clubs/manage.html", {"club": club})
