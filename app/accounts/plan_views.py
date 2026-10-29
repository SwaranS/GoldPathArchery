from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from . import relationships as service
from .athlete_views import relationship_errors, visible_athlete
from .models import AthleteProfile
from .permissions import can, training_fields
from .plan_forms import DAYS, PlanSetupForm
from .plan_models import PlanSetup
from django.utils import timezone
from training.models import GeneratedPlan


@login_required
@require_GET
@relationship_errors
def my_plans(request):
    # Do not require a declared role for access to an existing own profile.
    from .permissions import accessible_athletes
    own = accessible_athletes(request.user).filter(account=request.user).first()
    if own:
        return redirect("athlete-plans", athlete_id=own.pk)
    return render(request, "accounts/plans_missing_profile.html")


@login_required
@require_http_methods(["GET", "POST"])
@relationship_errors
def plans(request, athlete_id):
    athlete = visible_athlete(request, athlete_id)
    generated_plans = GeneratedPlan.objects.filter(athlete=athlete).order_by("-created_at", "-pk")
    setup = PlanSetup.objects.filter(athlete=athlete).first()
    allowed = can(request.user, athlete, "edit_profile")
    if request.method == "POST":
        # Lock the same athlete row as relationship writes; recheck live authority.
        with transaction.atomic():
            athlete = AthleteProfile.objects.select_for_update().get(pk=athlete_id)
            service.apply_age_transition(athlete)
            service.require(request.user, athlete, "edit_profile")
            setup = PlanSetup.objects.filter(athlete=athlete).first()
            if setup and setup.submitted_at:
                messages.info(request, "This setup has already been submitted. No changes were made.")
                return redirect("athlete-plans", athlete_id=athlete.pk)
            form = PlanSetupForm(request.POST, instance=setup, submitting=request.POST.get("action") == "submit")
            status = 200
            if request.POST.get("action") not in {"save", "submit"}:
                form.is_valid()
                form.add_error(None, "Choose Save draft or Submit setup.")
            elif form.is_valid():
                if str(athlete.version) != str(form.cleaned_data["version"]):
                    form.add_error(None, "This profile or setup changed. Reload the page and review before saving. Your entries are shown below.")
                    status = 409
                else:
                    saved = form.save(commit=False)
                    saved.athlete = athlete
                    if request.POST["action"] == "submit":
                        saved.submitted_at = timezone.now()
                    saved.full_clean()
                    saved.save()
                    service.changed(athlete)
                    service.audit(athlete, request.user, "submit_plan_setup" if saved.submitted_at else "save_plan_setup")
                    messages.success(request, "Your setup has been submitted." if saved.submitted_at else "Your setup draft has been saved.")
                    return redirect("athlete-plans", athlete_id=athlete.pk)
    else:
        initial = {"version": athlete.version}
        if setup is None:
            initial.update(goals=athlete.goals, availability=athlete.availability)
        form = PlanSetupForm(instance=setup, initial=initial)
        status = 200
    return render(request, "accounts/plans.html", {
        "athlete": training_fields(athlete), "setup": setup,
        "generated_plans": generated_plans,
        "latest_generated_plan": generated_plans.filter(status="ready").first(),
        "setup_form": form if allowed and not (setup and setup.submitted_at) else None,
        "can_setup": allowed, "active_tab": "plans",
        "review_day_label": dict(DAYS).get(setup.review_day) if setup else None,
        "permissions": {"edit_profile": allowed, "edit_plan": can(request.user, athlete, "edit_plan")},
    }, status=status)
