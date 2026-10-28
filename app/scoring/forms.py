from django import forms
from .models import Equipment, PhysicalArrow, RoundDefinition, ScoringRuleSet, TargetFace, DIVISIONS


class StartForm(forms.Form):
    mode = forms.ChoiceField(choices=[("round", "Configured round"), ("custom", "Custom training")])
    context = forms.ChoiceField(choices=[("training", "Training"), ("competition", "Competition")])
    round = forms.ModelChoiceField(queryset=RoundDefinition.objects.filter(active=True), required=False)
    division = forms.ChoiceField(choices=DIVISIONS)
    category = forms.CharField(max_length=100, required=False)
    target = forms.ModelChoiceField(queryset=TargetFace.objects.filter(active=True), required=False)
    rules = forms.ModelChoiceField(queryset=ScoringRuleSet.objects.filter(active=True), required=False)
    distance_m = forms.FloatField(min_value=0.01, required=False)
    ends = forms.IntegerField(min_value=1, max_value=100, initial=10, required=False)
    arrows_per_end = forms.IntegerField(min_value=1, max_value=36, initial=3, required=False)
    bow = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    arrow_set = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)

    def __init__(self, *args, athlete, **kwargs):
        super().__init__(*args, **kwargs)
        for field, kind in (("bow", "bow"), ("arrow_set", "arrow_set")):
            self.fields[field].queryset = Equipment.objects.filter(athlete=athlete, kind=kind, active=True)
        self.fields["division"].initial = athlete.discipline

    def clean(self):
        data = super().clean()
        required = ["round"] if data.get("mode") == "round" else ["target", "rules", "distance_m", "ends", "arrows_per_end"]
        for key in required:
            if not data.get(key):
                self.add_error(key, "Required for this mode.")
        return data

    def service_data(self):
        return {key: value.pk if hasattr(value, "pk") else value for key, value in self.cleaned_data.items()}


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = ("kind", "name", "division", "details")

    def clean(self):
        data = super().clean()
        if data.get("kind") == "bow" and not data.get("division"):
            self.add_error("division", "Select a bow division.")
        return data


class ArrowForm(forms.ModelForm):
    class Meta:
        model = PhysicalArrow
        fields = ("arrow_set", "identifier")

    def __init__(self, *args, athlete, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["arrow_set"].queryset = Equipment.objects.filter(athlete=athlete, kind="arrow_set", active=True)
