from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from . import grants, memberships, services
from .models import Club, ClubRoleAssignment, ClubDataGrant


class GrantForm(forms.Form):
    club = forms.ModelChoiceField(queryset=Club.objects.none())
    grantee = forms.ModelChoiceField(queryset=get_user_model().objects.none(), required=False, label="Named club coach")
    role = forms.ChoiceField(required=False, choices=[("", "Or choose a club role"), *ClubRoleAssignment._meta.get_field("role").choices])
    scopes = forms.MultipleChoiceField(choices=list(grants.SCOPES.items()), widget=forms.CheckboxSelectMultiple)
    purpose = forms.CharField(max_length=300)
    starts_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    expires_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))

    def __init__(self, *args, athlete, **kwargs):
        super().__init__(*args, **kwargs)
        from . import programmes
        self.fields["scopes"].choices = [(key, label) for key, label in grants.SCOPES.items()
            if key != "programme_progress" or programmes.enabled()]
        clubs = memberships.home_options(athlete)
        self.fields["club"].queryset = clubs
        ids = ClubRoleAssignment.objects.filter(membership__club__in=clubs, membership__active=True,
            role="coach", revoked_at__isnull=True, accepted_at__lte=timezone.now()).values_list("membership__user_id", flat=True)
        self.fields["grantee"].queryset = get_user_model().objects.filter(pk__in=ids, is_active=True).order_by("username")


class RevokeForm(forms.Form):
    grant = forms.UUIDField()
    version = forms.IntegerField(min_value=1)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def manage(request, athlete_id):
    athlete = grants.owner(request.user, athlete_id)
    revoke_form = RevokeForm(request.POST if request.method == "POST" and request.POST.get("action") == "revoke" else None)
    form = GrantForm(request.POST if request.method == "POST" and request.POST.get("action") == "issue" else None,
        athlete=athlete, initial={"starts_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "expires_at": timezone.localtime(timezone.now()+timedelta(days=30)).strftime("%Y-%m-%dT%H:%M")})
    status = 200
    if request.method == "POST":
        current = revoke_form if request.POST.get("action") == "revoke" else form
        if current.is_valid():
            try:
                if current is revoke_form:
                    grants.revoke(request.user, athlete.pk, current.cleaned_data["grant"], current.cleaned_data["version"])
                else:
                    data = current.cleaned_data
                    grants.issue(request.user, athlete.pk, club_id=data["club"].pk,
                        grantee_id=data["grantee"].pk if data["grantee"] else None, role=data["role"],
                        scopes=data["scopes"], purpose=data["purpose"], starts_at=data["starts_at"], expires_at=data["expires_at"])
                return redirect("clubs:grants", athlete_id=athlete.pk)
            except ValidationError as exc:
                current.add_error(None, exc)
                status = 409 if isinstance(exc, services.ClaimConflict) else 200
    return render(request, "clubs/grants.html", {"athlete": athlete, "form": form, "revoke_form": revoke_form,
        "grants": ClubDataGrant.objects.filter(athlete=athlete).select_related("club", "grantee").order_by("-created_at")}, status=status)


@never_cache
@login_required
@require_GET
def shared(request):
    if not grants.enabled():
        raise Http404
    from . import programmes
    rows = [(scope, label, grants.shared_athletes(request.user, scope)) for scope, label in grants.SCOPES.items()
        if scope != "training_edit" and (scope != "programme_progress" or programmes.enabled())]
    return render(request, "clubs/shared.html", {"categories": rows})


@never_cache
@login_required
@require_GET
def data(request, athlete_id, scope):
    payload = grants.shared_payload(request.user, athlete_id, scope)
    services.audit(request.user, None, "grant.read." + scope, athlete_id)
    if request.GET.get("format") == "json":
        return JsonResponse(payload)
    return render(request, "clubs/shared_data.html", {"scope": grants.SCOPES[scope], "scope_key": scope,
        "payload": payload, "athlete_id": athlete_id,
        "can_generate": scope == "training" and grants.allows(request.user,
            grants.AthleteProfile.objects.get(pk=athlete_id), "training_edit")})
