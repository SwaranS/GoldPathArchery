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
    specs = forms.JSONField(required=False, widget=forms.HiddenInput)
    expected_revision = forms.IntegerField(required=False, widget=forms.HiddenInput)
    accessory_attributes = forms.CharField(required=False, widget=forms.Textarea, max_length=6000,
        label="Other accessory details (one label=value per line)")

    def __init__(self, *args, **kwargs):
        from .component_specs import NUMBERS, TEXT
        super().__init__(*args, **kwargs)
        specs = self.initial.get("specs", {})
        selected = self.initial.get("category")
        self.fields["accessory_attributes"].component_category = "other"
        self.initial["accessory_attributes"] = "\n".join(f"{k}={v}" for k, v in specs.get("attributes", {}).items())
        for category in NUMBERS:
            for key in NUMBERS[category].split() + TEXT[category].split() + ["discipline"]:
                numeric = key in NUMBERS[category].split()
                field_type = forms.IntegerField if key.endswith("count") else forms.FloatField if numeric else forms.CharField
                options = dict(required=False, label=category.replace("_", " ").title() + " / " + key.replace("_", " "))
                options.update(min_value=1 if key.endswith("count") else 0.001) if numeric else options.update(max_length=1000)
                field = field_type(**options)
                field.component_category = category
                name = f"spec__{category}__{key}"
                self.fields[name] = field
                if category == selected:
                    self.initial[name] = specs.get(key)
        self.initial["specs"] = None

    def clean(self):
        from .component_specs import validate_specs, NUMBERS, TEXT
        data = super().clean()
        category = data.get("category")
        specs = data.get("specs") or {}
        if category:
            for key in NUMBERS[category].split() + TEXT[category].split() + ["discipline"]:
                value = data.get(f"spec__{category}__{key}")
                if value is not None and value != "":
                    specs[key] = value
            if category == "other" and data.get("accessory_attributes"):
                attributes = {}
                for line in data["accessory_attributes"].splitlines():
                    if "=" not in line:
                        raise forms.ValidationError("Use label=value for each accessory detail.")
                    key, value = line.split("=", 1)
                    if key.strip() in attributes:
                        raise forms.ValidationError("Accessory labels must be unique.")
                    attributes[key.strip()] = value.strip()
                specs["attributes"] = attributes
            data["specs"] = specs
            validate_specs(category, specs)
        return data


class ConfigurationForm(forms.Form):
    name = forms.CharField(max_length=100)
    division = forms.ChoiceField(choices=DIVISIONS)
    components = forms.ModelMultipleChoiceField(queryset=Equipment.objects.none(), required=False)
    preferred_arrows = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    acknowledged = forms.BooleanField(required=False, label="I acknowledge physical fit is unverified; these rules are not a safety certification")
    reason = forms.CharField(max_length=500, required=False)
    expected_revision = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, athlete, actor=None, **kwargs):
        from .models import ComponentRevision
        super().__init__(*args, **kwargs)
        from django.db.models import Q
        from .advanced_equipment import shared_components
        shared_ids = [r["revision_id"] for r in shared_components(actor, athlete)] if actor else []
        self.fields["components"].queryset = ComponentRevision.objects.filter(Q(component__owner=athlete, component__status="active") | Q(pk__in=shared_ids)).select_related("component")
        self.fields["preferred_arrows"].queryset = Equipment.objects.filter(athlete=athlete, kind="arrow_set", active=True)


class MaintenanceForm(forms.Form):
    photos = forms.ModelMultipleChoiceField(queryset=Equipment.objects.none(), required=False)
    component = forms.ModelChoiceField(queryset=Equipment.objects.none())
    kind = forms.ChoiceField(choices=[(v, v.title()) for v in ("inspection", "service", "repair", "replacement")])
    event_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    notes = forms.CharField(max_length=2000, required=False, widget=forms.Textarea)
    condition = forms.CharField(max_length=100, required=False)
    replacement = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    correction_of = forms.IntegerField(required=False, min_value=1)
    def __init__(self, *args, athlete, **kwargs):
        from .models import EquipmentComponent
        super().__init__(*args, **kwargs)
        from .models import EquipmentPhoto
        self.fields["photos"].queryset = EquipmentPhoto.objects.filter(owner=athlete, receipt=False, active=True)
        for field in ("component", "replacement"):
            self.fields[field].queryset = EquipmentComponent.objects.filter(owner=athlete)


class PurchaseForm(forms.Form):
    component = forms.ModelChoiceField(queryset=Equipment.objects.none())
    purchase_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    retailer = forms.CharField(max_length=150, required=False)
    amount = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, required=False)
    currency = forms.ChoiceField(required=False)
    warranty_expiry = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    receipt = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    correction_of = forms.IntegerField(required=False, min_value=1)
    def __init__(self, *args, athlete, **kwargs):
        from .models import EquipmentComponent, EquipmentPhoto
        from .advanced_equipment import CURRENCIES
        super().__init__(*args, **kwargs)
        self.fields["component"].queryset = EquipmentComponent.objects.filter(owner=athlete)
        self.fields["receipt"].queryset = EquipmentPhoto.objects.filter(owner=athlete, receipt=True, active=True)
        self.fields["currency"].choices = [("", "---------")] + [(c, c) for c in sorted(CURRENCIES)]


class SessionEquipmentForm(forms.Form):
    configuration = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    bow = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    arrow_set = forms.ModelChoiceField(queryset=Equipment.objects.none(), required=False)
    version = forms.IntegerField(widget=forms.HiddenInput)
    key = forms.UUIDField(widget=forms.HiddenInput)
    def __init__(self, *args, athlete, **kwargs):
        from .models import BowConfiguration
        from .advanced_equipment import configuration_available
        super().__init__(*args, **kwargs)
        self.fields["configuration"].queryset = BowConfiguration.objects.filter(owner=athlete, active=True, pk__in=[
            c.pk for c in BowConfiguration.objects.filter(owner=athlete, active=True) if configuration_available(c.revisions.first(), athlete)])
        for key, kind in (("bow", "bow"), ("arrow_set", "arrow_set")):
            self.fields[key].queryset = Equipment.objects.filter(athlete=athlete, active=True, kind=kind)
