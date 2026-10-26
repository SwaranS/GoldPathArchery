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
from .permissions import OPERATIONS, accessible_athletes, can, training_fields


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
        athlete = service.create_profile(
            request.user, data, child=child, declaration=declaration
        )
        return redirect("athlete-detail", athlete_id=athlete.pk)
    # No directory of all athletes: only explicitly accessible objects.
    profiles = list(accessible_athletes(request.user))
    for athlete in profiles:
        service.transition(athlete.pk)
    return render(
        request,
        "accounts/athletes.html",
        {
            "athletes": profiles,
            "form": form,
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
    context = {"athlete": training_fields(athlete), "permissions": permissions}
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
