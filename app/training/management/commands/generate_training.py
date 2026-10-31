import logging
import time

from django.core.management.base import BaseCommand
from django.db import transaction, close_old_connections
from django.utils import timezone

from accounts import relationships
from app.schemas.training_plan import GeneratePlanRequest
from app.services.periodization_engine import PeriodizationEngineService
from training.models import GeneratedPlan

logger = logging.getLogger(__name__)


def process_next():
    # Keep the row lock until the result is committed. A killed worker rolls back
    # its claim, so another worker can retry without losing a queued request.
    with transaction.atomic():
        job = GeneratedPlan.objects.select_for_update(skip_locked=True).filter(status="queued").order_by("created_at").first()
        if job is None:
            return False
        try:
            # The live athlete permission is checked again at execution time.
            with transaction.atomic():
                athlete = type(job.athlete).objects.select_for_update().get(pk=job.athlete_id)
                relationships.apply_age_transition(athlete)
                relationships.require(job.requested_by, athlete, "edit_plan")
                engine = PeriodizationEngineService()
                plan = engine.generate_plan(GeneratePlanRequest.model_validate(job.inputs), plan_id=job.pk)
                # A club role/grant can change while a provider is generating.
                relationships.require(job.requested_by, athlete, "edit_plan")
                job.roadmap = engine.to_roadmap_response(plan).model_dump(mode="json")
                # A generated suggestion is a draft until human review/activation exists.
                job.roadmap["status"] = "draft"
                job.status = "ready"
        except Exception:
            logger.exception("Training generation failed for %s", job.pk)
            job.status = "failed"
            job.error = "Generation failed or access changed. Review your inputs and try again."
        job.save(update_fields=["roadmap", "status", "error"])
    return True


class Command(BaseCommand):
    help = "Process durable training generation requests."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            worked = process_next()
            if options["once"]:
                return
            if not worked:
                time.sleep(2)
