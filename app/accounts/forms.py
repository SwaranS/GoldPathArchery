from django import forms
from .models import UserRole


class RolesForm(forms.Form):
    roles = forms.MultipleChoiceField(
        choices=[(UserRole.Role.ARCHER, "Archer"), (UserRole.Role.PARENT, "Parent/guardian")],
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )
