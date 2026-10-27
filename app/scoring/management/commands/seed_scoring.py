"""Idempotent practice catalogue; no claim of official event certification."""
from django.core.management.base import BaseCommand
from django.db import transaction
from scoring.models import TargetFace, ScoringRuleSet, RoundDefinition, RoundStage


class Command(BaseCommand):
    help = "Create missing practice targets/rules/rounds without overwriting administrator changes."

    @transaction.atomic
    def handle(self, *args, **options):
        faces = {}
        for size in (20, 40, 60, 80, 122):
            for layout, spots in (
                ("full", [[0, 0, 1]]),
                ("vertical triple", [[0, -.66, .32], [0, 0, .32], [0, .66, .32]]),
                ("triangular triple", [[0, -.48, .4], [-.45, .42, .4], [.45, .42, .4]]),
                ("four face", [[-.5, -.5, .45], [.5, -.5, .45], [-.5, .5, .45], [.5, .5, .45]]),
            ):
                name = f"Practice {size} cm {'junior ' if size == 60 else ''}{layout}"
                faces[size, layout], _ = TargetFace.objects.get_or_create(name=name, defaults=dict(
                    diameter_cm=size, layout=layout,
                    geometry=dict(spots=spots, rings=[i / 10 for i in range(1, 11)])))
        rule_sets = {}
        for name, minimum, compound, outdoor in (
            ("Practice indoor ten", 1, False, False),
            ("Practice indoor compound inner ten", 1, True, False),
            ("Practice triple 6–10", 6, False, False),
            ("Practice outdoor X", 1, False, True),
            ("Practice six-ring X", 5, False, True),
        ):
            zones = []
            if outdoor:
                zones.append(dict(radius=.05, symbol="X", points=10, x=True))
            zones.append(dict(radius=.05 if compound else .1, symbol="10", points=10))
            for points in range(9, minimum - 1, -1):
                zones.append(dict(radius=(11 - points) / 10, symbol=str(points), points=points))
            rule_sets[name], _ = ScoringRuleSet.objects.get_or_create(name=name, defaults=dict(rules=dict(boundary="inner", zones=zones)))
        for division in ("recurve", "compound", "barebow"):
            indoor_rules = rule_sets["Practice indoor compound inner ten" if division == "compound" else "Practice indoor ten"]
            for label, ends, arrows, distance, size, rule, stage_count in (
                ("Indoor 30", 10, 3, 18, 40, indoor_rules, 1),
                ("Indoor 60", 20, 3, 18, 40, indoor_rules, 1),
                ("Junior 60 cm 30", 10, 3, 18, 60, indoor_rules, 1),
                ("720", 12, 6, 50 if division != "recurve" else 70, 80 if division == "compound" else 122,
                 rule_sets["Practice six-ring X" if division == "compound" else "Practice outdoor X"], 1),
                ("Double 720", 12, 6, 50 if division != "recurve" else 70, 80 if division == "compound" else 122,
                 rule_sets["Practice six-ring X" if division == "compound" else "Practice outdoor X"], 2),
            ):
                round, created = RoundDefinition.objects.get_or_create(name=f"Practice {label} · {division}", defaults=dict(division=division))
                if created:
                    for index in range(stage_count):
                        RoundStage.objects.create(round=round, order=index + 1, distance_m=distance,
                            target=faces[size, "full"], rules=rule, ends=ends, arrows_per_end=arrows)
        self.stdout.write(self.style.SUCCESS("Practice scoring catalogue ready. Existing configurations preserved."))
