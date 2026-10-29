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


class AthleteDisciplineForm(forms.ModelForm):
    discipline = forms.MultipleChoiceField(
        choices=AthleteProfile._meta.get_field("discipline").choices,
        widget=forms.CheckboxSelectMultiple,
        label="Disciplines",
        help_text="Select all disciplines you shoot.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and self.instance.pk:
            self.initial["discipline"] = self.instance.selected_disciplines

    def clean(self):
        data = super().clean()
        selected = data.get("discipline")
        if selected:
            selected = list(dict.fromkeys(selected))
            # Keep a single default for existing scoring and plan generation.
            current = self.instance.discipline
            data["discipline"] = current if current in selected else selected[0]
            data["disciplines"] = selected
            self.instance.disciplines = selected
        return data


class AthleteCreateForm(AthleteDisciplineForm):
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


class AthleteEditForm(AthleteDisciplineForm):
    version = forms.IntegerField(widget=forms.HiddenInput)

    class Meta:
        model = AthleteProfile
        fields = ["display_name", "discipline", "goals", "availability", "hidden"]
