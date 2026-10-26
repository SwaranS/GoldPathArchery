from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Stable app identity independent of Google email and provider."""
    pass


class UserRole(models.Model):
    class Role(models.TextChoices):
        ARCHER = "archer", "Archer"
        PARENT = "parent", "Parent/guardian"
        COACH = "coach", "Coach"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.CharField(max_length=20, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "role"], name="unique_user_role")]
