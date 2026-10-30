# GoldPathArchery

Archery training, scoring and coaching service for recurve, compound and barebow.

## Scoring implementation

See [scoring setup and behavior](docs/scoring.md) for migrations, practice seed data, administration, score entry, session history, equipment and personal bests.

## Planning baseline

Product choices were gathered with the owner and remaining defaults selected under delegated authority on 22 October 2026. Documents below describe intended behaviour; application implementation has not started. Work is on `feature/requirements`; this update does not merge to main.

| Document | Purpose |
|---|---|
| [00-master-service.md](00-master-service.md) | Product brief and launch scope |
| [01-product-decisions.md](01-product-decisions.md) | Current decisions and delegated defaults |
| [02-mvp-requirements.md](02-mvp-requirements.md) | R01–R19 and acceptance scenarios |
| [03-roles-and-permissions.md](03-roles-and-permissions.md) | Role, age, relationship and assignment rules |
| [04-user-flows.md](04-user-flows.md) | Main screens and journeys |
| [05-architecture.md](05-architecture.md) | Selected logical stack and operational design |
| [06-delivery-plan.md](06-delivery-plan.md) | Milestones and issue-ready development backlog |
| [07-release-checklist.md](07-release-checklist.md) | Checks to perform before real release |
| [08-decision-history.md](08-decision-history.md) | Historical/superseded decisions |
| [09-scoring-and-equipment.md](09-scoring-and-equipment.md) | Round definitions, plotting, equipment and analytics |

Start implementation with T01–T03 in 06, then build the assigned-manager → parent/athlete → logged-session journey. Use synthetic data and a fixture generator until a live AI configuration is evaluated.

## Scope reminders

Human Plan Managers review initial plans and weekly AI recommendations; eligible users accept weekly changes. Default duration is 12 weeks, configurable up to one year. Scoring supports individual arrows, optional saved physical-arrow IDs, keypad and plotting.

Pilot: four weeks, 5–10 athletes, at least two coaches and one parent-managed junior; feedback-focused, no formal success targets. Testing budget: EUR 45/month across all Azure/AI/email/storage costs. Provider/SKU prices, domain, operator, named participants and dates require execution-time evidence.

## Advanced equipment

See [advanced equipment](docs/advanced-equipment.md) for schema, permissions, private Azure/local media configuration, migration review, isolated test commands and rollout/rollback constraints. Both athlete equipment routes remain supported. Do not deploy to preview: startup may apply migrations automatically.
