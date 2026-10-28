from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from .models import AthleteProfile


class PlanSetup(models.Model):
    """Athlete-supplied planning brief; not a generated or published training plan."""

    athlete = models.OneToOneField(AthleteProfile, on_delete=models.CASCADE, related_name="plan_setup")
    goals = models.TextField(blank=True, max_length=4000)
    experience = models.TextField(blank=True, max_length=2000)
    weekly_sessions = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(100)])
    weekly_arrows = models.PositiveIntegerField(null=True, blank=True, validators=[MaxValueValidator(100000)])
    availability = models.TextField(blank=True, max_length=4000)
    range_access = models.TextField(blank=True, max_length=2000)
    equipment = models.TextField(blank=True, max_length=2000)
    duration_days = models.PositiveSmallIntegerField(default=84, validators=[MinValueValidator(1), MaxValueValidator(365)])
    competition_date = models.DateField(null=True, blank=True)
    review_day = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(6)])
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
