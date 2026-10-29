import uuid

from django.conf import settings
from django.db import models


class GeneratedPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    athlete = models.ForeignKey("accounts.AthleteProfile", on_delete=models.CASCADE)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, default="queued")
    inputs = models.JSONField()
    roadmap = models.JSONField(default=dict)
    error = models.TextField(blank=True)
