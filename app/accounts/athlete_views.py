from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import relationships as service
from .forms import AthleteCreateForm, AthleteEditForm
from .permissions import OPERATIONS, accessible_athletes, can, eligible_actor, training_fields


def relationship_errors(view):
    @never_cache
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except PermissionDenied:
            # Uniform failure: no athlete, recipient, invitation or relationship disclosure.
            raise Http404("Unavailable.")
        except ObjectDoesNotExist:
            raise Http404("Unavailable.")
        except service.Conflict as error:
            return HttpResponse(str(error), status=409)
        except ValidationError as error:
            return JsonResponse({"errors": error.messages}, status=400)
        except (ValueError, TypeError):
            return HttpResponse("Invalid request.", status=400)
        except IntegrityError:
            return HttpResponse(
                "This account or relationship already exists. Reload and review.",
                status=409,
            )

    return wrapped


@login_required
@require_http_methods(["GET", "POST"])
@relationship_errors
def athletes(request):
    form = AthleteCreateForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        child, declaration = data.pop("child"), data.pop("declaration")
        try:
            athlete = service.create_profile(
                request.user, data, child=child, declaration=declaration
            )
        except PermissionDenied:
            # Creation has no private target to conceal. Keep the bound form so
            # users can correct their role selection without losing their input.
            form.add_error(
                None,
                "Unable to create this profile. Save the Parent/Guardian role in My account "
                "for a child profile, or Archer for your own profile. Accounts with a "
                "junior (under 16) or closed athlete profile cannot create profiles.",
            )
        else:
            return redirect("athlete-detail", athlete_id=athlete.pk)
    # No directory of all athletes: only explicitly accessible objects.
    profiles = list(accessible_athletes(request.user))
    for athlete in profiles:
        service.transition(athlete.pk)
    roles = set(request.user.role_assignments.values_list("role", flat=True))
    eligible = eligible_actor(request.user, write=True)
    can_create_child = eligible and "parent" in roles
    can_create_own = (
        eligible and "archer" in roles
        and not hasattr(request.user, "athlete_profile")
    )
    return render(
        request,
        "accounts/athletes.html",
        {
            "athletes": profiles,
            "form": form,
            "can_create_child": can_create_child,
            "can_create_own": can_create_own,
            "notices": request.user.relationship_notices.filter(
                athlete__closed_at__isnull=True
            ),
        },
    )


def visible_athlete(request, athlete_id):
    athlete = get_object_or_404(accessible_athletes(request.user), pk=athlete_id)
    athlete = service.transition(athlete.pk)
    if not can(request.user, athlete, "view"):
        raise Http404("Unavailable.")
    return athlete


@login_required
@require_http_methods(["GET", "POST"])
@relationship_errors
def athlete_detail(request, athlete_id):
    athlete = visible_athlete(request, athlete_id)
    if request.method == "POST":
        # Reject unknown fields rather than silently ignoring age/account tampering.
        if set(request.POST) - {
            "csrfmiddlewaretoken",
            "version",
            "display_name",
            "discipline",
            "goals",
            "availability",
            "hidden",
        }:
            raise ValidationError("Unsupported profile fields.")
        service.require(request.user, athlete, "edit_profile")
        form = AthleteEditForm(request.POST, instance=athlete)
        if form.is_valid():
            data = dict(form.cleaned_data)
            version = data.pop("version")
            service.update_profile(request.user, athlete_id, data, version)
            return redirect("athlete-detail", athlete_id=athlete_id)
    else:
        form = AthleteEditForm(instance=athlete, initial={"version": athlete.version})
    permissions = {
        operation: can(request.user, athlete, operation) for operation in OPERATIONS
    }
    # Coach context never contains a whole athlete object, birth date, timezone or account identity.
    context = {
        "athlete": training_fields(athlete),
        "permissions": permissions,
        "active_tab": "connections",
    }
    if permissions["edit_profile"]:
        context["form"] = form
    managing = permissions["manage_grants"]
    claim_allowed = service.may_invite(request.user, athlete, "claim")
    context.update({"claim_allowed": claim_allowed, "version": athlete.version})
    if managing or claim_allowed:
        context["invitations"] = athlete.invitations.filter(
            accepted_at__isnull=True, revoked_at__isnull=True
        )
    if managing:
        context["guardians"] = athlete.guardians.select_related("parent")
        context["coaches"] = athlete.coaches.select_related("coach")
    else:
        context["guardians"] = athlete.guardians.filter(parent=request.user)
        context["coaches"] = athlete.coaches.filter(coach=request.user)
    context["review_required"] = (
        athlete.account_id == request.user.pk
        and athlete.parent_review_required
        and athlete.age() >= 16
    )
    return render(request, "accounts/athlete_detail.html", context)


@login_required
@require_http_methods(["POST"])
@relationship_errors
def invitation_create(request, athlete_id):
    invitation, token = service.invite(
        request.user,
        athlete_id,
        request.POST.get("kind"),
        request.POST.get("email", ""),
        request.POST.get("version"),
    )
    # Deliberate private handoff: do not put tokens in logs/email console, listings or audit metadata.
    response = render(
        request,
        "accounts/invitation_created.html",
        {
            "invitation_url": request.build_absolute_uri(
                reverse("invitation-accept", args=[token])
            ),
            "athlete_id": invitation.athlete_id,
        },
    )
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@login_required
@require_http_methods(["GET", "POST"])
@relationship_errors
def invitation_accept(request, token):
    if request.method == "POST":
        athlete = service.accept(
            request.user, token, declaration=request.POST.get("declaration") == "on"
        )
        return redirect("athlete-detail", athlete_id=athlete.pk)
    # Opening a link reveals no hidden target and makes no grant, even for matching recipients.
    response = render(request, "accounts/invitation_accept.html")
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@login_required
@require_http_methods(["POST"])
@relationship_errors
def invitation_revoke(request, athlete_id, invitation_id):
    service.revoke_invitation(
        request.user, athlete_id, invitation_id, request.POST.get("version")
    )
    return redirect("athlete-detail", athlete_id=athlete_id)


@login_required
@require_http_methods(["POST"])
@relationship_errors
def grant_update(request, athlete_id, kind, link_id):
    service.set_grant(
        request.user,
        athlete_id,
        kind,
        link_id,
        request.POST.get("access"),
        request.POST.get("version"),
    )
    return redirect("athletes")


@login_required
@require_http_methods(["POST"])
@relationship_errors
def parent_review(request, athlete_id):
    service.confirm_parent_review(request.user, athlete_id, request.POST.get("version"))
    return redirect("athlete-detail", athlete_id=athlete_id)


ATHLETE_SECTIONS = {
    "today": {
        "key": "today",
        "eyebrow": "FLOW D · PRACTICE & RESCHEDULING",
        "title": "Today & Week",
        "summary": (
            "View today's shooting and non-shooting sessions, Rest Day entries, "
            "and weekly schedule targets."
        ),
        "highlights": [
            "Log completed, partially completed or skipped sessions with actual arrow counts, effort (1–10) and notes.",
            "Move individual unstarted sessions within the active plan period with Rest Day and conflict warnings.",
            "Record strength, mobility and mental practice without requiring arrow counts.",
        ],
    },
    "plans": {
        "key": "plans",
        "eyebrow": "FLOWS B, C & H · MANAGED AI PLANS",
        "title": "Plans & Weekly Adaptation",
        "summary": (
            "Manage the athlete's active training plan (default 12 weeks, configurable 1 day to 1 year), "
            "weekly AI recommendations and shared plan copies."
        ),
        "highlights": [
            "One active plan per athlete with scheduled future activation and replacement confirmation.",
            "Review Manager-released weekly AI recommendations: accept, edit or reject each proposal individually.",
            "Share independent inactive plan copies via private invitation without exposing logs or scores.",
        ],
    },
    "score": {
        "key": "score",
        "eyebrow": "FLOW E · KEYPAD & TARGET PLOTTING",
        "title": "Round Scoring",
        "summary": (
            "Record arrow-by-arrow scores via numeric keypad or interactive target-face plotting "
            "for recurve, compound and barebow."
        ),
        "highlights": [
            "Launch presets: Indoor 30, Indoor 60, Double 60, Outdoor 720, Double 720 and partial training rounds.",
            "Optional physical arrow identifiers selected strictly from the athlete's saved active arrow sets.",
            "Save and resume unfinished rounds; audited score corrections remain restricted to Athlete 16+ or editing Parent.",
        ],
    },
    "progress": {
        "key": "progress",
        "eyebrow": "FLOW F · HISTORY & ANALYTICS",
        "title": "History & Progress",
        "summary": (
            "Review planned versus actual arrow volume, session completion and per-physical-arrow "
            "score averages across local date ranges."
        ),
        "highlights": [
            "Per-arrow mean score and sample count grouped by compatible bow revision, distance and target face.",
            "Separate equal arrow labels across different sets and preserve archived equipment in historical analysis.",
            "Explicitly labelled mixed-conditions view when combining different setups or distances.",
        ],
    },
    "equipment": {
        "key": "equipment",
        "eyebrow": "FLOW F · BOWS, ARROWS & SIGHT MARKS",
        "title": "Equipment & Sight Marks",
        "summary": (
            "Configure recurve, compound and barebow setups, named arrow sets, individual shaft identifiers "
            "and distance sight marks."
        ),
        "highlights": [
            "Save multiple bows, named arrow sets and unique physical arrow IDs per set.",
            "Record sight marks by bow, distance and optional arrow set for range reference.",
            "Archive retired equipment to hide it from new rounds while preserving historical shot revisions.",
        ],
    },
    "export": {
        "key": "export",
        "eyebrow": "FLOW I · DATA PORTABILITY & CLOSURE",
        "title": "Export & Profile Closure",
        "summary": (
            "Download training plans, session logs and scores as CSV or PDF summaries, or request "
            "reauthenticated profile closure."
        ),
        "highlights": [
            "Private 24-hour expiring downloads for CSV arrow-level detail and readable PDF summaries.",
            "Immediate access, invitation and relationship revocation upon confirmed closure, with anonymisation within 30 days.",
            "Controlled by Athlete 16+ or managing Parent for profiles below 16.",
        ],
    },
}

WORKSPACE_SECTIONS = {
    "discovery": {
        "key": "discovery",
        "eyebrow": "FLOW G · R04 SIGNED-IN DISCOVERY",
        "title": "Profile Discovery",
        "graphic": "accounts/role-archer.svg",
        "summary": (
            "Search eligible signed-in profiles showing only display name, role and bow discipline."
        ),
        "highlights": [
            "Under-16 athlete profiles and accounts with 'Stay out of Search' enabled never appear in search.",
            "Hidden users and managing parents initiate their own connections via private 7-day invitations.",
            "Birth dates, contact emails and training records are never exposed in directory listings.",
        ],
    },
    "contributions": {
        "key": "contributions",
        "eyebrow": "FLOW G · R15 COACH SNAPSHOTS",
        "title": "My Coach Contributions",
        "graphic": "accounts/role-coach.svg",
        "summary": (
            "Read-only archive of your own authored plan proposals and session instruction revisions."
        ),
        "highlights": [
            "Retains only your dated authored instructions and their status after a coaching relationship ends.",
            "Excludes whole athlete plans, subsequent athlete activity and other coaches' private notes.",
            "Subject to athlete account closure and anonymisation rules.",
        ],
    },
    "manager": {
        "key": "manager",
        "eyebrow": "FLOWS B & C · R05/R07 SYSTEM PLAN MANAGER",
        "title": "Plan Manager Review Queue",
        "graphic": "accounts/workflow-banner.svg",
        "summary": (
            "Generate, validate and review initial AI training plans and weekly adaptation proposals "
            "for assigned athletes."
        ),
        "highlights": [
            "Access restricted strictly to administrator-assigned athletes and active temporary cover grants.",
            "Review AI drafts against scheduling and volume constraints before publishing or releasing proposals.",
            "Plan Managers never edit athlete actual scores or browse private coach notes.",
        ],
    },
    "admin_ops": {
        "key": "admin_ops",
        "eyebrow": "R16 & R18 · OPERATIONS & ASSIGNMENTS",
        "title": "Administrator Operations",
        "graphic": "accounts/role-parent.svg",
        "summary": (
            "Manage System Plan Manager assignments, expiring temporary cover and operational job status."
        ),
        "highlights": [
            "Assign or reassign Plan Managers and dated temporary cover (default 7 days, max 30 days) with audit logs.",
            "Monitor durable background queues for exports, closures and scheduled activations.",
            "Routine administration provides no private-data browsing or training-note debug views.",
        ],
    },
}


@login_required
@require_http_methods(["GET"])
@relationship_errors
def athlete_section(request, athlete_id, section):
    if section not in ATHLETE_SECTIONS:
        raise Http404("Unavailable.")
    athlete = visible_athlete(request, athlete_id)
    permissions = {
        operation: can(request.user, athlete, operation) for operation in OPERATIONS
    }
    return render(
        request,
        "accounts/athlete_placeholder.html",
        {
            "athlete": training_fields(athlete),
            "permissions": permissions,
            "section": ATHLETE_SECTIONS[section],
            "active_tab": section,
        },
    )


@login_required
@require_http_methods(["GET"])
@relationship_errors
def workspace_section(request, section):
    if section not in WORKSPACE_SECTIONS:
        raise Http404("Unavailable.")
    return render(
        request,
        "accounts/workspace_placeholder.html",
        {
            "section": WORKSPACE_SECTIONS[section],
            "active_workspace": section,
        },
    )
