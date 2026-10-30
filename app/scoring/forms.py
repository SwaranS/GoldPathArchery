from django import forms
from .models import Equipment, EquipmentRevision, PhysicalArrow, SightMark, RoundDefinition, ScoringRuleSet, TargetFace, DIVISIONS
from .equipment_services import SPEC_FIELDS, revision_choices


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
    configuration = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    bow = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    arrow_set = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)

    def __init__(self, *args, athlete, **kwargs):
        super().__init__(*args, **kwargs)
        for field, kind in (("bow", "bow"), ("arrow_set", "arrow_set")):
            self.fields[field].queryset = Equipment.objects.filter(athlete=athlete, kind=kind, active=True)
        self.fields["division"].initial = athlete.discipline
        from .models import BowConfiguration, AthleteEquipmentDefaults
        from .advanced_equipment import configuration_available
        configs = BowConfiguration.objects.filter(owner=athlete, active=True)
        self.fields["configuration"].queryset = configs.filter(pk__in=[c.pk for c in configs if configuration_available(c.revisions.first(), athlete)])
        default = AthleteEquipmentDefaults.objects.filter(athlete=athlete).select_related("configuration").first()
        self.equipment_warning = "No usable default configuration. Choose equipment manually."
        if default and default.configuration and configuration_available(default.configuration.revisions.first(), athlete):
            rev = default.configuration.revisions.first()
            self.fields["configuration"].initial = default.configuration_id
            self.fields["division"].initial = rev.division
            self.fields["arrow_set"].initial = rev.preferred_arrows_id if rev.preferred_arrows and rev.preferred_arrows.active else None
            self.equipment_warning = ""

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
    kind = forms.ChoiceField(choices=Equipment._meta.get_field("kind").choices)
    expected_revision = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = EquipmentRevision
        fields = SPEC_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["kind", *SPEC_FIELDS, "expected_revision"])

    def clean(self):
        data = super().clean()
        if data.get("kind") == "bow" and not data.get("division"):
            self.add_error("division", "Select a bow division.")
        forbidden = ("spine", "length", "point_weight", "shaft_diameter") if data.get("kind") == "bow" else ("division", "handedness", "draw_weight", "draw_length")
        for field in forbidden:
            if data.get(field):
                self.add_error(field, "This field does not apply to this equipment type.")
        return data

    def service_data(self):
        return {key: value for key, value in self.cleaned_data.items() if key in {"kind", *SPEC_FIELDS}}


class ArrowForm(forms.ModelForm):
    class Meta:
        model = PhysicalArrow
        fields = ("arrow_set", "identifier", "notes")

    def __init__(self, *args, athlete, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["arrow_set"].queryset = Equipment.objects.filter(athlete=athlete, kind="arrow_set", active=True)


class SightMarkForm(forms.ModelForm):
    class Meta:
        model = SightMark
        fields = ("configuration_revision", "bow_revision", "arrow_revision", "distance", "distance_unit", "mark",
                  "sight_extension", "windage", "date", "notes")
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, athlete, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.athlete_id = getattr(athlete, "pk", athlete)
        from .models import ConfigurationRevision, BowConfiguration
        self.fields["configuration_revision"].queryset = ConfigurationRevision.objects.filter(
            pk__in=[c.revisions.first().pk for c in BowConfiguration.objects.filter(owner=athlete, active=True)])
        self.fields["bow_revision"].queryset = revision_choices(athlete, "bow")
        self.fields["arrow_revision"].queryset = revision_choices(athlete, "arrow_set")


class ComponentForm(forms.Form):
    from .component_specs import CATEGORIES
    category = forms.ChoiceField(choices=[(v, v.replace("_", " ").title()) for v in CATEGORIES])
    name = forms.CharField(max_length=100)
    manufacturer = forms.CharField(max_length=100, required=False)
    model = forms.CharField(max_length=100, required=False)
    serial_reference = forms.CharField(max_length=100, required=False)
    notes = forms.CharField(max_length=2000, required=False, widget=forms.Textarea)
    specs = forms.JSONField(required=False, initial=dict, help_text="Optional specification JSON. Field names include units; see the category schema below.")
    expected_revision = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def clean(self):
        from .component_specs import validate_specs
        data = super().clean()
        data["specs"] = data.get("specs") or {}
        if data.get("category"):
            validate_specs(data["category"], data["specs"])
        return data


class ConfigurationForm(forms.Form):
    name = forms.CharField(max_length=100)
    division = forms.ChoiceField(choices=DIVISIONS)
    components = forms.ModelMultipleChoiceField(queryset=Equipment.objects.none(), required=False)
    preferred_arrows = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    acknowledged = forms.BooleanField(required=False, label="I acknowledge physical fit is unverified; these rules are not a safety certification")
    reason = forms.CharField(max_length=500, required=False)
    expected_revision = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, athlete, **kwargs):
        from .models import ComponentRevision
        super().__init__(*args, **kwargs)
        self.fields["components"].queryset = ComponentRevision.objects.filter(component__owner=athlete, component__status="active").select_related("component")
        self.fields["preferred_arrows"].queryset = Equipment.objects.filter(athlete=athlete, kind="arrow_set", active=True)
