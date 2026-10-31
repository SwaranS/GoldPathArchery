from django import forms
from django.db.models import Q
from django.utils import timezone
from accounts.models import AthleteProfile
from training.forms import GenerationForm
from app.schemas.training_plan import PlanArchetype, RoundFormat
from . import programmes
from .models import ClubRoleAssignment, ClubMembership, ClubTrainingGroupMember


class TrainingGroupForm(forms.Form):
    version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
    name = forms.CharField(max_length=160)
    description = forms.CharField(max_length=4000, required=False, widget=forms.Textarea)
    discipline = forms.ChoiceField(choices=[(d, d.title()) for d in ("recurve", "compound", "barebow")])
    coach_role = forms.ModelChoiceField(queryset=ClubRoleAssignment.objects.none(), label="Assigned club coach")
    active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, club, current_role=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["coach_role"].queryset = ClubRoleAssignment.objects.filter(membership__club=club, role="coach").filter(
            Q(membership__active=True, revoked_at__isnull=True, accepted_at__lte=timezone.now()) | Q(pk=current_role)).select_related("membership__user")
        if actor and not programmes.services.can_manage(actor, club):
            self.fields["coach_role"].queryset = self.fields["coach_role"].queryset.filter(membership__user=actor)
        self.fields["coach_role"].label_from_instance = lambda r: r.membership.user.username if r.membership.user else "Unavailable coach"


class ProgrammeTemplateForm(forms.Form):
    version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
    title = forms.CharField(max_length=160)
    instructions = forms.CharField(max_length=4000, required=False, widget=forms.Textarea,
        help_text="Group instructions are visible to accepted group members. Do not include individual private notes.")
    start_date = forms.DateField(widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    duration_days = forms.IntegerField(min_value=1, max_value=365, initial=84)
    archetype = forms.ChoiceField(choices=[(a.value, a.value.replace("_", " ").title()) for a in PlanArchetype])
    round_format = forms.ChoiceField(choices=[(r.value, r.value.replace("_", " ").title()) for r in RoundFormat])


class WeeklySessionForm(forms.Form):
    weekday = forms.TypedChoiceField(coerce=int, choices=list(enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    duration_mins = forms.IntegerField(min_value=1, max_value=480, label="Duration in minutes")
    description = forms.CharField(max_length=2000, widget=forms.Textarea, label="Group session description")


WeeklySessions = forms.formset_factory(WeeklySessionForm, extra=0, min_num=1, max_num=14,
    validate_min=True, validate_max=True, can_delete=True)


class GroupInvitationForm(forms.Form):
    membership = forms.ModelChoiceField(queryset=ClubMembership.objects.none(), label="Club member to invite")

    def __init__(self, *args, group, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["membership"].queryset = ClubMembership.objects.filter(club=group.club, active=True).select_related("athlete", "user")
        self.fields["membership"].label_from_instance = lambda m: m.athlete.display_name if m.athlete else m.user.username if m.user else "Unavailable identity"


class ProgrammeOfferForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    member = forms.ModelChoiceField(queryset=ClubTrainingGroupMember.objects.none(), label="Accepted group member")

    def __init__(self, *args, programme, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = programme.group.members.filter(state="active", membership__active=True).select_related("membership__athlete", "membership__user")
        self.fields["member"].label_from_instance = lambda m: m.membership.athlete.display_name if m.membership.athlete else m.membership.user.username if m.membership.user else "Unavailable identity"


class ProgrammeResponseForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    decision = forms.ChoiceField(choices=[("accept", "Accept and request an individual draft"), ("decline", "Decline"), ("customize", "Request a new personal draft version"), ("withdraw", "Withdraw from assignment")])
    private_note = forms.CharField(max_length=1000, required=False, widget=forms.Textarea, help_text="Private to you and authorized guardians; never shown to the group coach.")


class GroupResponseForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    decision = forms.ChoiceField(choices=[("accept", "Accept"), ("decline", "Decline"), ("leave", "Leave group")])


class ProgrammeActionForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    action = forms.ChoiceField(choices=[("publish", "Publish latest revision"), ("archive", "Archive programme")])


class ProgressForm(forms.Form):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    completed_sessions = forms.IntegerField(min_value=0, label="Self-reported sessions completed")
    private_note = forms.CharField(max_length=2000, required=False, widget=forms.Textarea,
        help_text="Private to you and authorized guardians. Progress grants share the session count only.")


def individual_form(assignment, data=None):
    snapshot = assignment.revision.snapshot
    initial = {"athlete": assignment.athlete_id, "archetype": snapshot["archetype"], "round_format": snapshot["round_format"],
        "start_date": snapshot["start_date"], "target_date": snapshot["target_date"],
        "days": sorted({s["weekday"] for s in snapshot["sessions"]}), "minutes": min(360, max(15, max(s["duration_mins"] for s in snapshot["sessions"])))}
    form = GenerationForm(data, athletes=AthleteProfile.objects.filter(pk=assignment.athlete_id), initial=dict(initial), prefix="individual")
    form.initial.update(initial)  # GenerationForm sets personal defaults in its constructor.
    form.fields["athlete"].widget = forms.HiddenInput()
    return form
