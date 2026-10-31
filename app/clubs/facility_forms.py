from decimal import Decimal, InvalidOperation
from django import forms
from .models import ClubFacility, ShootingArea, FacilityAvailabilityRule, FacilityAvailabilityException, FACILITY_AUDIENCES, FacilityAccessGroup, ClubMembership


class GroupFieldsMixin:
    def __init__(self, *args, club=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("access_group", "location_group"):
            if field in self.fields:
                self.fields[field].queryset = FacilityAccessGroup.objects.filter(club=club).order_by("name", "pk")
                self.fields[field].help_text = "Select only when the corresponding audience is a named facility access group."


class FacilityForm(GroupFieldsMixin, forms.ModelForm):
    version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = ClubFacility
        fields = ["name", "description", "timezone", "audience", "access_group", "location_audience", "location_group", "address", "latitude", "longitude", "active"]
        labels = {"description": "Description (visible to the facility audience)",
            "audience": "Who can see this facility?", "location_audience": "Who can see the exact address and coordinates?"}


class DistancesField(forms.CharField):
    def prepare_value(self, value):
        return ", ".join(str(d) for d in value) if isinstance(value, list) else value

    def to_python(self, value):
        if isinstance(value, list):
            return value
        try:
            result = [Decimal(part.strip()) for part in value.split(",")]
            if not result or len(result) > 100 or any(not d.is_finite() or not 0 < d <= 1000 for d in result):
                raise ValueError
            return [float(d) for d in sorted(set(result))]
        except (InvalidOperation, AttributeError, ValueError):
            raise forms.ValidationError("Enter comma-separated positive distances in metres, up to 1000.") from None


class AreaForm(GroupFieldsMixin, forms.ModelForm):
    version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
    disciplines = forms.MultipleChoiceField(choices=[(v, v.title()) for v in ("recurve", "compound", "barebow")], widget=forms.CheckboxSelectMultiple)
    distances_m = DistancesField(label="Distances in metres", help_text="For example: 5, 18, 30, 50, 70")
    lane_capacity = forms.IntegerField(min_value=1, max_value=1000)
    target_capacity = forms.IntegerField(min_value=1, max_value=1000)

    class Meta:
        model = ShootingArea
        fields = ["name", "kind", "disciplines", "distances_m", "lane_capacity", "target_capacity", "audience", "access_group", "active"]


class RuleForm(GroupFieldsMixin, forms.ModelForm):
    version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = FacilityAvailabilityRule
        fields = ["weekday", "starts_on", "ends_on", "start_time", "end_time", "priority", "audience", "access_group", "active"]
        widgets = {"starts_on": forms.DateInput(attrs={"type": "date"}), "ends_on": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}), "end_time": forms.TimeInput(attrs={"type": "time"})}
        help_texts = {"priority": "Higher priority replaces all lower-priority hours for that day. Add multiple rules at the same priority for separate daily slots.",
            "end_time": "Same-day hours only. Split overnight hours across two weekdays."}


class ExceptionForm(GroupFieldsMixin, forms.ModelForm):
    version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = FacilityAvailabilityException
        fields = ["starts_on", "ends_on", "kind", "replacement_slots", "reason", "priority", "audience", "access_group", "active"]
        widgets = {"starts_on": forms.DateInput(attrs={"type": "date"}), "ends_on": forms.DateInput(attrs={"type": "date"})}
        help_texts = {"replacement_slots": 'For replacement hours only: [{"start":"09:00","end":"12:00"}]. Leave empty for closures.',
            "reason": "Visible only to the exception audience. Hidden exceptions still suppress ordinary hours.",
            "priority": "Highest-priority exception takes precedence over all recurring rules."}


FORMS = {"facility": FacilityForm, "area": AreaForm, "rule": RuleForm, "exception": ExceptionForm}


class CalendarForm(forms.Form):
    starts_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Starting date")
    days = forms.IntegerField(min_value=1, max_value=31, initial=7)


class PhotoForm(GroupFieldsMixin, forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    caption = forms.CharField(max_length=200, help_text="Describe the image. Avoid precise location details unless its audience may see them.")
    audience = forms.ChoiceField(choices=FACILITY_AUDIENCES, initial="admins")
    access_group = forms.ModelChoiceField(queryset=FacilityAccessGroup.objects.none(), required=False)
    primary = forms.BooleanField(required=False)
    upload = forms.FileField(help_text="JPEG or PNG only, up to 5 MB and 12 million pixels. Metadata is removed.")


class PhotoActionForm(forms.Form):
    photo = forms.UUIDField()
    version = forms.IntegerField(min_value=1)
    action = forms.ChoiceField(choices=[("primary", "Set primary"), ("archive", "Archive")])


class GroupForm(forms.Form):
    version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
    name = forms.CharField(max_length=100)
    members = forms.ModelMultipleChoiceField(queryset=ClubMembership.objects.none(), required=False)
    active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, club, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["members"].queryset = ClubMembership.objects.filter(club=club, active=True).select_related("user", "athlete").order_by("created_at", "pk")
        self.fields["members"].label_from_instance = lambda member: member.athlete.display_name if member.athlete else member.user.username if member.user else "Inactive identity"
