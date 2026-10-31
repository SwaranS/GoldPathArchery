from django import forms
from accounts.models import AthleteProfile
from . import memberships
from .models import Club, ClubRoleAssignment


class SubjectForm(forms.Form):
    athlete = forms.ModelChoiceField(queryset=AthleteProfile.objects.none(), required=False,
        empty_label="My own account", label="Who is joining?")

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["athlete"].queryset = AthleteProfile.objects.filter(pk__in=[a.pk for a in memberships.subjects(actor)])


class InvitationAcceptanceForm(SubjectForm):
    token = forms.CharField(max_length=128, widget=forms.PasswordInput(render_value=False), label="Invitation code")
    decision = forms.ChoiceField(choices=[("accept", "Accept"), ("decline", "Decline")])


class InviteForm(forms.Form):
    email = forms.EmailField(max_length=254, label="Recipient's verified account email")


class ManagerActionForm(forms.Form):
    action = forms.ChoiceField(choices=[(v, v) for v in (
        "approve", "reject", "revoke_invitation", "offer_role", "revoke_role", "remove", "suspend", "settings")])
    target = forms.UUIDField(required=False)
    version = forms.IntegerField(min_value=1)
    role = forms.ChoiceField(required=False, choices=[("", "Choose role"), *ClubRoleAssignment._meta.get_field("role").choices])
    accepts_requests = forms.BooleanField(required=False)


class VersionForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class RoleResponseForm(VersionForm):
    decision = forms.ChoiceField(choices=[("accept", "Accept"), ("decline", "Decline")])


class HomeForm(forms.Form):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    club = forms.ModelChoiceField(queryset=Club.objects.none(), required=False, empty_label="No home club")

    def __init__(self, *args, athlete, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["club"].queryset = memberships.home_options(athlete)
