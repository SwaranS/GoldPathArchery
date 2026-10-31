from django.core.management.base import BaseCommand
from clubs.facilities import cleanup_uploads


class Command(BaseCommand):
    help = "Dry-run orphan facility photo uploads older than 24 hours; --apply deletes unlinked blobs."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        count = cleanup_uploads(apply=options["apply"], limit=options["limit"])
        self.stdout.write(f"{'Removed' if options['apply'] else 'Would remove'} {count} orphan facility photo upload(s).")
