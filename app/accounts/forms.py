from django import forms
from .models import UserRole


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
