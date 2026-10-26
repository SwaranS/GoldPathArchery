from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .forms import RolesForm
from .models import UserRole
from .permissions import accessible_athletes
from .relationships import transition


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def profile(request):
    if request.method == "GET":
        # Google still redirects here. Process age changes and take the 16+ athlete
        # straight to their parent-access chooser on their next sign-in.
        for athlete in accessible_athletes(request.user):
            current = transition(athlete.pk)
            if (
                current.account_id == request.user.pk
                and current.age() >= 16
                and current.parent_review_required
            ):
                return redirect("athlete-detail", athlete_id=current.pk)
    # Role declarations do not grant permissions or athlete relationships.
    allowed = {role for role, _label in RolesForm.base_fields["roles"].choices}
    existing = set(request.user.role_assignments.values_list("role", flat=True))
    form = RolesForm(
        request.POST if request.method == "POST" else None,
        initial={"roles": list(existing & allowed)},
    )
    if request.method == "POST" and form.is_valid():
        chosen = set(form.cleaned_data["roles"])
        with transaction.atomic():
            UserRole.objects.filter(
                user=request.user, role__in=allowed - chosen
            ).delete()
            for role in chosen:
                UserRole.objects.get_or_create(user=request.user, role=role)
        return redirect("account-profile")
    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "notices": request.user.relationship_notices.filter(
                athlete__closed_at__isnull=True
            ),
        },
    )
