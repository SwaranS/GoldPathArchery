from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from accounts.permissions import can
from . import programmes as service, services, grants
from .models import Club, ClubTrainingGroup, ClubProgramme, ClubTrainingGroupMember, ClubProgrammeProgress
from .programme_forms import (TrainingGroupForm, ProgrammeTemplateForm, GroupInvitationForm, ProgrammeOfferForm,
    ProgrammeResponseForm, GroupResponseForm, ProgrammeActionForm, ProgressForm, individual_form, WeeklySessions)
from .security import admin_session_redirect


def error_status(exc):
    return 409 if isinstance(exc, service.ProgrammeConflict) else 200


def stale_form(form, expected):
    if not form.is_bound:
        return False
    try:
        submitted = int(form.data.get(form.add_prefix("version")))
    except (ValueError, TypeError):
        return False  # Normal field validation supplies the missing/invalid error.
    if submitted == expected:
        return False
    form.is_valid()
    form.add_error(None, "This record changed. Reload the current page before submitting again.")
    return True


@never_cache
@login_required
@require_GET
def index(request):
    groups = service.groups_for(request.user)
    authoring_clubs = [club for club in Club.objects.filter(clubmembership__user=request.user, clubmembership__active=True).distinct().order_by("name")
        if service.memberships.has_role(request.user, club, {"admin", "coach"})]
    return render(request, "clubs/programmes.html", {"groups": groups,
        "authoring_clubs": authoring_clubs,
        "memberships": [m for m in service.own_group_members(request.user) if service.owns_member(request.user, m.membership)],
        "assignments": service.own_assignments(request.user)})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def group_settings(request, club_id, group_id=None):
    service.require_enabled()
    club = get_object_or_404(Club, pk=club_id)
    group = get_object_or_404(ClubTrainingGroup, pk=group_id, club=club) if group_id else None
    if not (services.can_manage(request.user, club) or (service.is_coach(request.user, group) if group else service.memberships.has_role(request.user, club, {"coach"}))):
        raise Http404
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    initial = {key: getattr(group, key) for key in ("name", "description", "discipline", "coach_role", "active", "version")} if group else {}
    form = TrainingGroupForm(request.POST if request.method == "POST" else None, club=club, initial=initial,
        current_role=group.coach_role_id if group else None, actor=request.user)
    status = 200
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        version = data.pop("version")
        try:
            group = service.save_group(request.user, club.pk, data, group_id=group_id, version=version)
            return redirect("clubs:training-group", group_id=group.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
            status = error_status(exc)
    return render(request, "clubs/programme_form.html", {"title": "Training group settings · " + club.name, "form": form, "button": "Save training group"}, status=status)


@never_cache
@login_required
@require_GET
def group(request, group_id):
    group = service.group_for_reader(request.user, group_id)
    coach = service.is_coach(request.user, group)
    admin = services.can_manage(request.user, group.club)
    if coach or admin:
        challenge = admin_session_redirect(request)
        if challenge is not None:
            return challenge
    programmes = group.programmes.all().order_by("name", "pk") if coach or admin else group.programmes.filter(active=True, published_revision__gt=0).order_by("name", "pk")
    return render(request, "clubs/training_group.html", {"group": group, "is_coach": coach, "is_group_admin": admin,
        "programmes": programmes, "members": group.members.select_related("membership__athlete", "membership__user").all() if coach or admin else None})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def invite(request, group_id):
    group = service.control_group(request.user, group_id)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    form = GroupInvitationForm(request.POST if request.method == "POST" else None, group=group)
    if request.method == "POST" and form.is_valid():
        try:
            service.invite_group(request.user, group.pk, form.cleaned_data["membership"].pk)
            return redirect("clubs:training-group", group_id=group.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "clubs/programme_form.html", {"title": "Invite to " + group.name, "form": form, "button": "Invite club member"})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def member_response(request, member_id):
    service.require_enabled()
    member = get_object_or_404(ClubTrainingGroupMember.objects.select_related("group", "membership"), pk=member_id)
    if not service.owns_member(request.user, member.membership, write=True):
        raise Http404
    choices = [("accept", "Accept"), ("decline", "Decline")] if member.state == "invited" else [("leave", "Leave group")]
    if member.state not in {"invited", "active"} or (member.state == "invited" and member.expires_at <= service.timezone.now()):
        choices = []
    form = GroupResponseForm(request.POST if request.method == "POST" else None, initial={"version": member.version})
    form.fields["decision"].choices = choices
    status = 409 if stale_form(form, member.version) else 200
    if request.method == "POST" and status != 409 and form.is_valid():
        try:
            data = form.cleaned_data
            if data["decision"] == "leave":
                service.leave_group(request.user, member.pk, data["version"])
            else:
                service.respond_group(request.user, member.pk, data["decision"] == "accept", data["version"])
            return redirect("clubs:programmes")
        except ValidationError as exc:
            form.add_error(None, exc)
            status = error_status(exc)
    return render(request, "clubs/programme_form.html", {"title": "Group invitation · " + member.group.name, "form": form, "button": "Confirm group response"}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def remove_member(request, member_id):
    service.require_enabled()
    member = get_object_or_404(ClubTrainingGroupMember, pk=member_id)
    service.control_group(request.user, member.group_id)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    form = GroupResponseForm(request.POST if request.method == "POST" else None, initial={"version": member.version})
    form.fields["decision"].choices = [("leave", "Remove from group")]
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            service.leave_group(request.user, member.pk, form.cleaned_data["version"], remove=True)
            return redirect("clubs:training-group", group_id=member.group_id)
        except ValidationError as exc:
            form.add_error(None, exc)
            status = error_status(exc)
    return render(request, "clubs/programme_form.html", {"title": "Remove group membership", "form": form, "button": "Confirm removal"}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def template(request, group_id, programme_id=None):
    group = service.control_group(request.user, group_id, coach_only=True)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    programme = get_object_or_404(ClubProgramme, pk=programme_id, group=group, owner_role=group.coach_role) if programme_id else None
    latest = programme.revisions.order_by("-number").first() if programme else None
    initial = {**latest.snapshot, "version": programme.version} if latest else {"start_date": service.timezone.localdate()}
    form = ProgrammeTemplateForm(request.POST if request.method == "POST" else None, initial=initial)
    session_forms = WeeklySessions(request.POST if request.method == "POST" else None, prefix="sessions",
        initial=latest.snapshot["sessions"] if latest else None)
    status = 200
    if request.method == "POST" and form.is_valid() and session_forms.is_valid():
        data = dict(form.cleaned_data)
        version = data.pop("version")
        data["sessions"] = [{**{key: row[key] for key in ("weekday", "duration_mins", "description")},
            "start_time": row["start_time"].isoformat(timespec="minutes")} for row in session_forms.cleaned_data if row and not row.get("DELETE")]
        try:
            programme = service.save_template(request.user, group.pk, data, programme_id=programme_id, version=version)
            return redirect("clubs:programme", programme_id=programme.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
            status = error_status(exc)
    return render(request, "clubs/programme_form.html", {"title": "Programme template · " + group.name, "form": form,
        "session_forms": session_forms, "button": "Save template revision"}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def programme(request, programme_id):
    service.require_enabled()
    programme = get_object_or_404(ClubProgramme.objects.select_related("group__club"), pk=programme_id)
    group = service.group_for_reader(request.user, programme.group_id)
    coach, admin = service.is_coach(request.user, group), services.can_manage(request.user, group.club)
    if coach or admin:
        challenge = admin_session_redirect(request)
        if challenge is not None:
            return challenge
    elif not programme.active or not programme.published_revision:
        raise Http404
    can_edit = coach and programme.owner_role_id == group.coach_role_id
    form = ProgrammeActionForm(request.POST if request.method == "POST" else None, initial={"version": programme.version})
    if not can_edit:
        form.fields["action"].choices = [("archive", "Archive programme")]
    status = 200
    if request.method == "POST":
        if not (can_edit or admin):
            raise Http404
        if form.is_valid():
            try:
                if form.cleaned_data["action"] == "publish":
                    service.publish(request.user, programme.pk, form.cleaned_data["version"])
                else:
                    service.archive(request.user, programme.pk, form.cleaned_data["version"])
                return redirect("clubs:programme", programme_id=programme.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
                status = error_status(exc)
    revision = programme.revisions.order_by("-number").first() if coach or admin else programme.revisions.filter(number=programme.published_revision).first()
    return render(request, "clubs/programme.html", {"programme": programme, "revision": revision,
        "form": form if coach or admin else None, "can_edit": can_edit, "is_group_admin": admin,
        "assignments": service.ClubProgrammeAssignment.objects.filter(revision__programme=programme).select_related("athlete", "revision") if coach or admin else None}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def offer(request, programme_id):
    service.require_enabled()
    programme = get_object_or_404(ClubProgramme.objects.select_related("group__club"), pk=programme_id)
    service.control_group(request.user, programme.group_id, coach_only=True)
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    form = ProgrammeOfferForm(request.POST if request.method == "POST" else None, programme=programme, initial={"version": programme.version})
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            service.offer(request.user, programme.pk, form.cleaned_data["member"].pk, form.cleaned_data["version"])
            return redirect("clubs:programme", programme_id=programme.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
            status = error_status(exc)
    return render(request, "clubs/programme_form.html", {"title": "Offer " + programme.name, "form": form, "button": "Offer programme for consent"}, status=status)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def assignment(request, assignment_id):
    assignment = service.assignment_for_owner(request.user, assignment_id)
    writable = can(request.user, assignment.athlete, "manage_grants")
    action = request.POST.get("action")
    response = ProgrammeResponseForm(request.POST if request.method == "POST" and action == "response" else None,
        initial={"version": assignment.version})
    active_source = service.source_active(assignment)
    decisions = [("accept", "Accept and request an individual draft"), ("decline", "Decline")] if assignment.state == "offered" else [("customize", "Request a new personal draft version"), ("withdraw", "Withdraw from assignment")] if assignment.state == "accepted" else []
    if not active_source:
        decisions = [(key, label) for key, label in decisions if key not in {"accept", "customize"}]
    if assignment.state == "offered" and assignment.expires_at <= service.timezone.now():
        decisions = []
    response.fields["decision"].choices = decisions
    needs_inputs = request.method == "POST" and action == "response" and request.POST.get("decision") in {"accept", "customize"}
    planning = individual_form(assignment, request.POST if needs_inputs else None)
    progress = ClubProgrammeProgress.objects.filter(assignment=assignment).first()
    progress_form = ProgressForm(request.POST if request.method == "POST" and action == "progress" else None,
        initial={"version": progress.version if progress else 0, "completed_sessions": progress.completed_sessions if progress else 0, "private_note": progress.private_note if progress else ""}, prefix="progress")
    status = 409 if action == "response" and stale_form(response, assignment.version) else 200
    if request.method == "POST":
        if not writable:
            raise Http404
        current = progress_form if action == "progress" else response
        if status != 409 and current.is_valid() and (not needs_inputs or planning.is_valid()):
            try:
                if action == "progress":
                    data = progress_form.cleaned_data
                    service.save_progress(request.user, assignment.pk, data["completed_sessions"], data["private_note"], data["version"])
                elif action == "response":
                    data = response.cleaned_data
                    service.respond_assignment(request.user, assignment.pk, data["decision"], data["version"],
                        payload=planning.payload if needs_inputs else None, private_note=data["private_note"])
                else:
                    raise ValidationError("Choose a permitted response.")
                return redirect("clubs:programme-assignment", assignment_id=assignment.pk)
            except ValidationError as exc:
                current.add_error(None, exc)
                status = error_status(exc)
    return render(request, "clubs/programme_assignment.html", {"assignment": assignment, "snapshot": assignment.revision.snapshot,
        "response_form": response if writable and decisions else None, "planning_form": planning,
        "show_planning": active_source and assignment.state in {"offered", "accepted"},
        "progress_form": progress_form if writable and assignment.state in {"accepted", "withdrawn"} else None,
        "progress": progress, "plans": assignment.plans.select_related("plan").order_by("-number")}, status=status)


@never_cache
@login_required
@require_GET
def coach_progress(request, assignment_id):
    service.require_enabled()
    assignment = get_object_or_404(service.ClubProgrammeAssignment.objects.select_related("revision__programme__group__club", "group_member__membership", "athlete"), pk=assignment_id)
    group = service.control_group(request.user, assignment.revision.programme.group_id, coach_only=True)
    if not service.source_active(assignment) or assignment.state != "accepted" or not grants.allows(request.user, assignment.athlete, "programme_progress", club_id=group.club_id):
        raise Http404
    challenge = admin_session_redirect(request)
    if challenge is not None:
        return challenge
    payload = service.shared_progress(request.user, assignment.athlete_id)
    payload["progress"] = [row for row in payload["progress"] if row["assignment"] == str(assignment.pk)]
    services.audit(request.user, None, "programme.progress.read", assignment.pk, club=group.club)
    if request.GET.get("format") == "json":
        return JsonResponse(payload)
    return render(request, "clubs/shared_data.html", {"scope": "Programme progress", "scope_key": "programme_progress", "payload": payload})
