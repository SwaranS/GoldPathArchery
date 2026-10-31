from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_GET

from accounts.athlete_views import relationship_errors
from accounts.models import AthleteProfile
from accounts.permissions import accessible_athletes, can
from accounts import relationships
from .forms import GenerationForm
from .models import GeneratedPlan


@login_required
@require_http_methods(["GET", "POST"])
@relationship_errors
def new(request):
    athletes = accessible_athletes(request.user)
    from clubs.grants import shared_athletes
    ids = {a.pk for a in athletes if can(request.user, a, "edit_plan")}
    ids.update(shared_athletes(request.user, "training_edit").values_list("pk", flat=True))
    editable = AthleteProfile.objects.filter(pk__in=ids)
    initial = {"athlete": request.GET.get("athlete")}
    form = GenerationForm(request.POST if request.method == "POST" else None, athletes=editable, initial=initial)
    if form.is_valid():
        with transaction.atomic():
            athlete = AthleteProfile.objects.select_for_update().get(pk=form.cleaned_data["athlete"].pk)
            relationships.apply_age_transition(athlete)
            relationships.require(request.user, athlete, "edit_plan")
            job = GeneratedPlan.objects.create(athlete=athlete, requested_by=request.user, inputs=form.payload)
        return redirect("training-detail", pk=job.pk)
    return render(request, "training/new.html", {"form": form, "recent": GeneratedPlan.objects.filter(athlete__in=athletes).order_by("-created_at")[:20]})


@login_required
@require_GET
@relationship_errors
def detail(request, pk):
    job = get_object_or_404(GeneratedPlan, pk=pk)
    if not can(request.user, job.athlete, "view"):
        from clubs.grant_views import data
        return data(request, job.athlete_id, "training")
    relationships.require(request.user, job.athlete, "view")
    return render(request, "training/detail.html", {"job": job})
