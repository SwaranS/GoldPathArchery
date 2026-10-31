from django.core.management.base import BaseCommand
from clubs.services import cleanup_evidence, cleanup_security_events


class Command(BaseCommand):
    help = "Purge expired evidence payloads and day-old orphan uploads. Defaults to dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            from django.core.management.base import CommandError
            raise CommandError("Limit must be positive.")
        counts = cleanup_evidence(dry_run=not options["apply"], limit=options["limit"])
        self.stdout.write(f"{'Purged' if options['apply'] else 'Eligible'}: {counts[0]} expired evidence records; {counts[1]} orphan uploads.")
        security_count = cleanup_security_events(dry_run=not options["apply"])
        self.stdout.write(f"{'Purged' if options['apply'] else 'Eligible'}: {security_count} expired security events.")
