from datetime import timedelta

from django import forms
from django.utils import timezone
from pydantic import ValidationError

from app.schemas.training_plan import GeneratePlanRequest, PlanArchetype, RoundFormat


def choices(enum):
    return [(item.value, item.value.replace("_", " ").title()) for item in enum]


class GenerationForm(forms.Form):
    athlete = forms.ModelChoiceField(queryset=None)
    archetype = forms.ChoiceField(choices=choices(PlanArchetype))
    round_format = forms.ChoiceField(choices=choices(RoundFormat))
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    target_date = forms.DateField(label="Target event or plan end date", widget=forms.DateInput(attrs={"type": "date"}))
    competition_tier = forms.ChoiceField(choices=[("A", "A — major event"), ("B", "B"), ("C", "C")])
    current_draw_weight = forms.FloatField(min_value=10.1, max_value=80)
    target_draw_weight = forms.FloatField(min_value=10.1, max_value=80, required=False)
    weekly_arrows = forms.IntegerField(min_value=0, max_value=3000)
    days = forms.MultipleChoiceField(choices=list(enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])), widget=forms.CheckboxSelectMultiple)
    minutes = forms.IntegerField(min_value=15, max_value=360, initial=90, label="Minutes available each training day")
    distance = forms.IntegerField(min_value=3, max_value=90, initial=70, label="Maximum available distance (metres)")

    def __init__(self, *args, athletes, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["athlete"].queryset = athletes
        today = timezone.localdate()
        self.initial.update(start_date=today, target_date=today + timedelta(days=84))

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        if (data["target_date"] - data["start_date"]).days > 365:
            self.add_error("target_date", "Choose a plan no longer than 365 days.")
            return data
        try:
            self.payload = GeneratePlanRequest.model_validate({
                "athlete_id": str(data["athlete"].pk),
                "baseline": {
                    "bow_division": data["athlete"].discipline,
                    "current_draw_weight_lbs": data["current_draw_weight"],
                    "target_draw_weight_lbs": data["target_draw_weight"],
                    "current_weekly_arrow_volume": data["weekly_arrows"],
                    "available_days": [{"day_of_week": int(day), "available_mins": data["minutes"], "max_distance_m": data["distance"]} for day in data["days"]],
                },
                "goal": {"primary_archetype": data["archetype"], "round_format": data["round_format"], "start_date": data["start_date"], "target_event_date": data["target_date"], "competition_tier": data["competition_tier"]},
            }).model_dump(mode="json")
        except ValidationError as exc:
            for error in exc.errors():
                self.add_error(None, error["msg"])
        return data
