from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import RolesForm
from .models import UserRole


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    # Role declarations do not grant permissions or athlete relationships.
    allowed = {role for role, _label in RolesForm.base_fields["roles"].choices}
    existing = set(request.user.role_assignments.values_list("role", flat=True))
    form = RolesForm(request.POST if request.method == "POST" else None, initial={"roles": list(existing & allowed)})
    if request.method == "POST" and form.is_valid():
        chosen = set(form.cleaned_data["roles"])
        with transaction.atomic():
            UserRole.objects.filter(user=request.user, role__in=allowed - chosen).delete()
            for role in chosen:
                UserRole.objects.get_or_create(user=request.user, role=role)
        return redirect("account-profile")
    return render(request, "accounts/profile.html", {"form": form})
