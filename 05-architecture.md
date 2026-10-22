# GoldPathArchery — Architecture Baseline

Status: Logical design selected; provider/SKU and deployment costs require validation  
Updated: 22 October 2026 · [Requirements](02-mvp-requirements.md)

## Selected structure and stack

Use a modular monolith: Python/Django server, PostgreSQL database, server-rendered responsive pages and focused JavaScript/SVG for scoring/plotting. Django's built-in account/session, migration and admin capabilities reduce custom foundation work; a relational model suits grants, assignments, scoring and histories. Use supported release versions verified against official documentation when implementation begins.

Keep business modules separate: identity/profiles, relationships/grants, manager assignments, planning/recommendations, activity logs, scoring, equipment, reporting, exports/closure and operations. No microservices or standalone frontend framework are required for MVP.

Use one codebase and container image. A durable database job queue and a separate worker process run generation, reviews, exports, closure and scheduled activation. If colocated with the web app for a small pilot, keep process restart handling and job leases explicit; do not rely on web-request timers or in-memory queues.

## Logical topology

Browser → authenticated Django application → PostgreSQL.  
Worker → job records and provider adapter → external AI/email capability as needed.  
Application/worker → private export and backup storage.  
Scheduler → idempotent due-job creation; database leases prevent duplicate execution.

Request handlers never bypass server permissions. PostgreSQL transactions protect activation, score totals and version transitions. Queries scope all results to the current actor/athlete before pagination or export.

## Data model

| Group | Entities / important invariants |
|---|---|
| Identity | Account, AthleteProfile, GuardianLink, account confirmation/claim tokens; stable athlete ID independent of login |
| Access | CoachRelationship, PermissionGrant, ManagerAssignment/cover; active dates and revocation; admin-only assignment changes |
| Planning | Plan, PlanVersion, PlannedSession/revision, scheduled activation; unique active plan per athlete; historical versions immutable |
| AI | GenerationRequest, ManagerReview, Recommendation, RecommendationDecision; provider/model/prompt/schema version and source-plan version |
| Activity | SessionLog/status/actual date, linked rounds; log ownership distinct from plan editors |
| Scoring | Versioned FormatDefinition, stages/faces/rules, Round, End, ArrowShot, ScoreCorrection; blank/M distinct; doubles link component rounds |
| Equipment | Bow/revision, ArrowSet/revision, PhysicalArrow, SightMark; unique arrow label within set; archive preserves references |
| History | CoachContributionSnapshot, attributable plan/schedule events; no copies of unrelated athlete history |
| Operations | DurableJob, ExportJob/file expiry, ClosureJob, minimal closure-suppression data, AuditEvent |

Store normalized plot positions with face/spot/version. Do not manufacture locations for numeric shots. Persist actual equipment/scoring context per shot or immutable segment. Reports aggregate effective scores, not fabricated blanks.

## Consistency and schedules

Use optimistic version checks for edits and recommendation application. Return a conflict with current content; never silently use last-writer-wins. Atomically activate one plan and deactivate the prior one. Idempotency keys stop repeated submissions/jobs creating duplicate shots or plans.

Store instants in UTC and IANA profile timezones for local days, birth-date transitions and reviews. Review job key includes athlete and week; changing day cannot duplicate the week's existing review. Check live permissions and closure status again when a worker executes.

## AI boundary

Application-owned structured interface: validated training context in, schema-conforming plan/recommendations out. The model cannot authorise access, compute authoritative scores or directly write active plans. Validate dates, duration, session fields and configured constraints before manager review.

Separate instructions from user notes. Send only planning-relevant fields, no email, passwords or private coach notes. Record generated output and manager/user decisions without assuming all raw provider logs should be retained. Never use identifiable fixtures for evaluation.

No external archery API has been selected. Keep a provider adapter so a general LLM API or a contracted planning service can be evaluated. Select provider/model only after checking output quality, available European processing terms, deletion/retention behaviour and cost. A deploy-time gate blocks live generation until these checks are recorded; deterministic fixtures support development meanwhile.

## Accounts and infrastructure

Use framework-supported password hashing, secure HTTP-only sessions, CSRF protection, rate limits and expiring email confirmation/recovery tokens. MFA is required for administrators and Plan Managers; available to other users. Routine admin screens expose account/assignment/job status, not a private-data debug view.

Azure European region is required. Validate a costed web/worker, managed PostgreSQL or equivalent operable database, private storage and email configuration before choosing service SKUs. Staging and production have separate credentials/databases; synthetic staging may use local tooling initially. No hosting or AI subscription is provisioned by this document.

EUR 45/month is a total testing ceiling, not a verified cloud quote. Include tax/currency assumptions, email, storage/egress, AI requests, backups and capped log retention. Configure spending visibility and application usage limits. If no supportable configuration fits, document the shortfall before paid provisioning; do not silently omit backups or raise the budget. Production budget is a separate follow-up.

## Recovery and data lifecycle

Daily encrypted backups, rolling maximum 30 days; operational pilot targets RPO 24 hours/RTO 24 hours. Rehearse restore. These are operational design targets, not pilot success criteria.

Immediate closure revokes sessions/tokens/jobs/grants. A closure inventory covers profile data, raw generation context, free text, contributions, scoring links, exports and audit references. Anonymise within 30 days, deleting where necessary. Restore in isolation and reapply minimal closure suppression before exposing data. Suppression lasts only while relevant backups exist. No full individual history retained under an “Anonymous” label.

Export links are private and expire in 24 hours. Storage lifecycle and job cleanup enforce expiry even on retry failures. Daily expiry jobs remove logs/backups according to D12. Do not write credentials or training-note payloads into infrastructure logs.

## Deployment and outstanding implementation evidence

CI: formatting/static checks, migrations, relevant tests, dependency checks and container build. Deploy a versioned artifact to staging; review before production. Plan backward-compatible migrations and explicit rollback/restore steps.

Before paid deployment record: supported package versions; provider/model/data-processing configuration; Azure region/SKUs and itemised price estimate; email domain settings; actual domain/operator; restore evidence. These are engineering/procurement follow-ups, not missing product-scope decisions.
