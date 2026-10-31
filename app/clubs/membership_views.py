from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from . import memberships as service
from . import services
from .membership_forms import (SubjectForm, InvitationAcceptanceForm, InviteForm,
    ManagerActionForm, VersionForm, RoleResponseForm, HomeForm)
from .models import ClubMembership, ClubMembershipAction, AthleteHomeClub
from .security import admin_session_redirect


def status_for(error):
    return 409 if isinstance(error, services.ClaimConflict) else 200


@never_cache
@login_required
@require_GET
def mine(request):
    service.actor_allowed(request.user)
    selected = request.GET.get("club")
    if selected:
        from uuid import UUID
        try:
            club_id = UUID(selected)
        except ValueError:
            raise Http404 from None
        club = service.managed(request.user, club_id)
        return redirect("clubs:membership-manage", club_id=club.pk)
    members = list(service.owned_memberships(request.user))
    for member in members:
        member.can_manage = service.has_role(request.user, member.club, {"admin", "membership_manager"})
        member.can_leave = member.active and service.owns(request.user, member)
    return render(request, "clubs/memberships.html", {
        "memberships": members, "actions": service.owner_actions(request.user),
        "subjects": service.subjects(request.user) if service.eligible_actor(request.user, write=True) else [],
    })


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def join(request, club_id):
    service.actor_allowed(request.user, write=True)
    club = get_object_or_404(services.public_clubs(), pk=club_id)
    form = SubjectForm(request.POST if request.method == "POST" else None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            athlete = form.cleaned_data["athlete"]
            service.request_join(request.user, club.pk, athlete.pk if athlete else None)
            return redirect("clubs:memberships")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "clubs/membership_form.html", {"title": "Request to join " + club.name, "form": form, "button": "Request to join"})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def accept_invitation(request, action_id):
    service.actor_allowed(request.user, write=True)
    # A UUID alone never reveals the club, recipient or invitation validity.
    form = InvitationAcceptanceForm(request.POST if request.method == "POST" else None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            service.accept_invite(request.user, action_id, data["token"], accept=data["decision"] == "accept",
                athlete_id=data["athlete"].pk if data["athlete"] else None)
            return redirect("clubs:memberships")
        except ValidationError as exc:
            form.add_error(None, exc)
    response = render(request, "clubs/membership_form.html", {"title": "Club invitation", "form": form, "button": "Confirm response"})
    # Suppress external referrers without turning same-origin POST Origin into
    # "null", which Django correctly rejects during CSRF verification.
    response["Referrer-Policy"] = "same-origin"
    return response


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def manage(request, club_id):
    club = service.managed(request.user, club_id)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    form = ManagerActionForm(request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            action, target, version = data["action"], data["target"], data["version"]
            if action in {"approve", "reject"}:
                service.decide_join(request.user, club.pk, target, action == "approve", version)
            elif action == "revoke_invitation":
                service.revoke_action(request.user, club.pk, target, version)
            elif action == "offer_role":
                service.offer_role(request.user, club.pk, target, data["role"], version)
            elif action == "revoke_role":
                service.revoke_role(request.user, club.pk, target, version)
            elif action in {"remove", "suspend"}:
                service.end_membership(request.user, club.pk, target, {"remove": "removed", "suspend": "suspended"}[action], version)
            elif action == "settings":
                service.set_requests(request.user, club.pk, data["accepts_requests"], version)
            return redirect("clubs:membership-manage", club_id=club.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
            status = status_for(exc)
    now = timezone.now()
    members = list(ClubMembership.objects.filter(club=club, active=True).select_related("user", "athlete").prefetch_related("roles"))
    for member in members:
        member.can_offer = member.user_id != request.user.pk and service.eligible_actor(member.user, write=True)
        member.can_end = True
        try:
            service.protect_last_admin(club, member)
        except ValidationError:
            member.can_end = False
        for role in member.roles.all():
            role.can_revoke = role.role != "admin" or member.can_end
    return render(request, "clubs/membership_manage.html", {"club": club, "form": form,
        "is_club_admin": service.has_role(request.user, club, {"admin"}),
        "members": members,
        "pending": ClubMembershipAction.objects.filter(club=club, kind="join", state="pending").select_related("athlete", "target_user"),
        "invitations": ClubMembershipAction.objects.filter(club=club, state="pending", expires_at__gt=now).exclude(kind="join"),
    }, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def invite(request, club_id):
    club = service.managed(request.user, club_id)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    form = InviteForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            action, token = service.invite(request.user, club.pk, form.cleaned_data["email"])
            response = render(request, "clubs/invitation_created.html", {"club": club, "token": token,
                "invitation_url": request.build_absolute_uri(reverse("clubs:invitation", args=[action.pk])), "expires": action.expires_at})
            response["Referrer-Policy"] = "no-referrer"
            return response
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "clubs/membership_form.html", {"title": "Invite to " + club.name, "form": form, "button": "Create invitation"})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def leave(request, member_id):
    service.actor_allowed(request.user, write=True)
    member = get_object_or_404(service.owned_memberships(request.user), pk=member_id)
    if not service.owns(request.user, member):
        raise Http404
    if service.has_role(request.user, member.club, {"admin", "membership_manager"}):
        challenge = admin_session_redirect(request)
        if challenge is not None:
            return challenge
    form = VersionForm(request.POST if request.method == "POST" else None, initial={"version": member.version})
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            service.end_membership(request.user, member.club_id, member.pk, "left", form.cleaned_data["version"])
            return redirect("clubs:memberships")
        except ValidationError as exc:
            form.add_error(None, exc)
            status = status_for(exc)
    return render(request, "clubs/membership_form.html", {"title": "Leave " + member.club.name, "form": form, "button": "Confirm leaving"}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def role_response(request, action_id):
    service.actor_allowed(request.user, write=True)
    action = get_object_or_404(ClubMembershipAction, pk=action_id, kind="role", target_user=request.user)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    form = RoleResponseForm(request.POST if request.method == "POST" else None, initial={"version": action.version})
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            service.accept_role(request.user, action.pk, form.cleaned_data["decision"] == "accept", form.cleaned_data["version"])
            return redirect("clubs:memberships")
        except ValidationError as exc:
            form.add_error(None, exc)
            status = status_for(exc)
    return render(request, "clubs/membership_form.html", {"title": "Respond to " + action.role + " appointment for " + action.club.name, "form": form, "button": "Confirm response"}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def home(request, athlete_id):
    athlete = service.subject(request.user, athlete_id)
    record = AthleteHomeClub.objects.filter(athlete=athlete).first()
    form = HomeForm(request.POST if request.method == "POST" else None, athlete=athlete,
        initial={"club": record.club_id if record else None, "version": record.version if record else 0})
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            service.select_home(request.user, athlete.pk, form.cleaned_data["club"].pk if form.cleaned_data["club"] else None, form.cleaned_data["version"])
            return redirect("clubs:memberships")
        except ValidationError as exc:
            form.add_error(None, exc)
            status = status_for(exc)
    return render(request, "clubs/membership_form.html", {"title": "Home club for " + athlete.display_name, "form": form,
        "description": "Choose explicitly from active verified memberships, or clear your selection. Past scores and event representation stay unchanged.", "button": "Save home club"}, status=status)
