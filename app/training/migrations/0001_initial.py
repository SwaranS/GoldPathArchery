import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("accounts", "0004_plansetup")]
    operations = [migrations.CreateModel(
        name="GeneratedPlan",
        fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("status", models.CharField(max_length=12, default="queued")),
            ("inputs", models.JSONField()),
            ("roadmap", models.JSONField(default=dict)),
            ("error", models.TextField(blank=True)),
            ("athlete", models.ForeignKey(to="accounts.athleteprofile", on_delete=django.db.models.deletion.CASCADE)),
            ("requested_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE)),
        ],
    )]
