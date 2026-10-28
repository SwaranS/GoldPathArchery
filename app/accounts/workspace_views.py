from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from . import relationships
from .athlete_views import athletes
from .navigation import WORKSPACES
from .permissions import accessible_athletes


@login_required
@never_cache
@require_GET
def landing(request):
    for athlete in accessible_athletes(request.user):
        current = relationships.transition(athlete.pk)
        if current.account_id == request.user.pk and current.age() >= 16 and current.parent_review_required:
            return redirect("athlete-detail", athlete_id=current.pk)
    roles = set(request.user.role_assignments.values_list("role", flat=True)) & WORKSPACES.keys()
    remembered = request.session.get("workspace")
    if remembered in roles:
        return redirect("workspace", workspace=remembered)
    if len(roles) == 1:
        return redirect("workspace", workspace=next(iter(roles)))
    if not roles:
        return redirect("account-profile")
    return render(request, "accounts/workspaces.html")


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def workspace(request, workspace):
    if workspace not in WORKSPACES or not request.user.role_assignments.filter(role=workspace).exists():
        raise Http404("Unavailable.")
    request.session["workspace"] = workspace
    if workspace == "archer":
        own = accessible_athletes(request.user).filter(account=request.user).first()
        if own:
            url = reverse("athlete-detail", args=[own.pk])
            return redirect(url + ("#connections" if request.GET.get("connections") else ""))
    return athletes(request, scope=workspace)
