from django import forms

from .models import AthleteProfile, UserRole


class RolesForm(forms.Form):
    roles = forms.MultipleChoiceField(
        choices=[
            (UserRole.Role.ARCHER, "Archer"),
            (UserRole.Role.PARENT, "Parent/Guardian"),
            (UserRole.Role.COACH, "Coach"),
        ],
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )


class AthleteCreateForm(forms.ModelForm):
    child = forms.BooleanField(
        required=False, label="Create a child profile (under 16)"
    )
    declaration = forms.BooleanField(
        required=False, label="I declare that I am this child's parent or guardian"
    )

    class Meta:
        model = AthleteProfile
        fields = [
            "display_name",
            "birth_date",
            "timezone",
            "discipline",
            "goals",
            "availability",
            "hidden",
        ]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"})}


class AthleteEditForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput)

    class Meta:
        model = AthleteProfile
        fields = ["display_name", "discipline", "goals", "availability", "hidden"]
