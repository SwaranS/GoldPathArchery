from django import forms

from .plan_models import PlanSetup

DAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
        (4, "Friday"), (5, "Saturday"), (6, "Sunday")]


class PlanSetupForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput)
    review_day = forms.TypedChoiceField(choices=DAYS, coerce=int, label="Preferred weekly review day")

    class Meta:
        model = PlanSetup
        fields = ["goals", "experience", "weekly_sessions", "weekly_arrows", "availability",
                  "range_access", "equipment", "duration_days", "competition_date", "review_day"]
        labels = {
            "goals": "What would you like to achieve?",
            "experience": "Your archery experience",
            "weekly_sessions": "Current training sessions per week",
            "weekly_arrows": "Current arrows per week",
            "availability": "Available days and training time",
            "range_access": "Range access and distances",
            "equipment": "Equipment available for training",
            "duration_days": "Requested plan length in days",
            "competition_date": "Next competition date (optional)",
        }
        help_texts = {
            "experience": "Tell us how long you have been shooting and what your current training involves.",
            "weekly_sessions": "Enter 0 if you are not currently training.",
            "weekly_arrows": "Enter 0 if you are not currently shooting.",
            "availability": "List the days you can train and the time available on each day.",
            "range_access": "Describe indoor/outdoor access, available distances and any restrictions.",
            "equipment": "Describe your bow, arrows and any equipment available for strength or mobility work.",
            "duration_days": "Defaults to 84 days (12 weeks). Request between 1 and 365 days.",
        }
        widgets = {name: forms.Textarea(attrs={"rows": 3}) for name in
                   ["goals", "experience", "availability", "range_access", "equipment"]}
        widgets["competition_date"] = forms.DateInput(attrs={"type": "date"})

    def __init__(self, *args, submitting=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.submitting = submitting
        self.fields["review_day"].help_text = "Used when weekly reviews are connected. Your profile timezone applies; manager availability affects release time."

    def clean(self):
        data = super().clean()
        if self.submitting:
            for name in ["goals", "experience", "weekly_sessions", "weekly_arrows",
                         "availability", "range_access", "equipment"]:
                if data.get(name) in (None, "") and name not in self.errors:
                    self.add_error(name, "Complete this before submitting your setup.")
        return data
