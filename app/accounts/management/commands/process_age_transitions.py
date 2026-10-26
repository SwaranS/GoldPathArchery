from django.core.management.base import BaseCommand

from accounts.models import AthleteProfile
from accounts.relationships import transition


class Command(BaseCommand):
    help = "Idempotently downgrade parent grants and create durable in-app age-16 notices. Run regularly."

    def handle(self, *args, **options):
        for pk in (
            AthleteProfile.objects.filter(
                closed_at__isnull=True, transitioned_at__isnull=True
            )
            .values_list("pk", flat=True)
            .iterator()
        ):
            transition(pk)
        self.stdout.write("Age transitions processed.")
