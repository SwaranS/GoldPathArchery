from django import forms
from .models import ClubClaim, ClubVerificationEvidence
from . import services


class ClaimForm(forms.ModelForm):
    class Meta:
        model = ClubClaim
        fields = ["listing", "name", "country", "region", "town", "website", "federation_number", "description", "visibility", "timezone", "role_assertion"]

    def __init__(self, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        super().__init__(*args, **kwargs)
        self.fields["listing"].queryset = services.available_listings()
        self.fields["role_assertion"].help_text = "Describe your authority to represent this club. Submission grants no club access."
        if partial:
            for name in ("country", "role_assertion"):
                self.fields[name].required = False


class EvidenceForm(forms.ModelForm):
    upload = forms.FileField(required=False, help_text="Optional private JPEG/PNG, at most 5 MB. Original metadata is removed.")

    class Meta:
        model = ClubVerificationEvidence
        fields = ["source_url", "contact_reference", "outcome", "confirmed", "checked_at", "expires_at"]
        widgets = {name: forms.DateTimeInput(attrs={"type": "datetime-local"}) for name in ("checked_at", "expires_at")}


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=[(value, label) for value, label in ClubClaim.State.choices if value not in ("draft", "submitted")])
    reason = forms.CharField(max_length=1000, widget=forms.Textarea,
        help_text="Shown to applicant. Do not include private evidence or contact details.")
    duplicates_reviewed = forms.BooleanField(required=False, label="I reviewed duplicate candidates and verified that a separate identity is appropriate")


class InformationResponseForm(forms.Form):
    response = forms.CharField(max_length=1000, widget=forms.Textarea)
