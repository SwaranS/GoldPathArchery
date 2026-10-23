# GoldPathArchery — Release Checklist

Status: Operational checklist; unchecked items are not completed claims  
Updated: 22 October 2026 · [Architecture](05-architecture.md) · [Delivery](06-delivery-plan.md)

The pilot gathers feedback without formal success criteria, numeric targets or pass/fail assessment. This checklist concerns software correctness and operating the service.

## Product and access verification

- [ ] Implemented behaviours match R01–R19 and the selected scoring definitions.
- [ ] Mobile/keypad/plotting and basic non-shooting/Rest Day journeys reviewed.
- [ ] Under-14/no-login, 14–15/read-only and 16+ transitions work; parent default becomes viewing.
- [ ] Self-declaration/email confirmation is clearly explained; no manual verification claimed.
- [ ] Signed-in search excludes under-16/hidden profiles; invitation recipient/expiry/replay checks pass.
- [ ] Per-coach view/edit grants do not permit actual log or score editing.
- [ ] Manager scope, admin-only assignments and cover expiry enforced on each request.
- [ ] Routine admin has no private-data support/debug view.
- [ ] Relationship end revokes history access; separate authored contributions reveal no later athlete data.
- [ ] One active plan, future activation and independent shared-copy ownership verified.
- [ ] Session moves preserve started/completed actuals and warn for rest-day/conflict cases.
- [ ] Recommendation original/review/decision/application histories retained; no silent conflicting write.
- [ ] Partial/double scoring, blank versus miss, optional saved identifiers and correction totals pass.
- [ ] Per-arrow averages/counts and compatible-condition grouping correct; archived equipment retained historically.

## AI and scoring readiness

- [ ] Planning guidance and configured load constraints reviewed by Plan Managers.
- [ ] Generated output validated and reviewed before publication/release.
- [ ] Provider/model/version, data handling, European processing suitability and cost recorded.
- [ ] No private coach notes/account-security fields sent to AI; worker permissions rechecked.
- [ ] Effective rulebook edition verified before official-labelled scoring presets are enabled.
- [ ] Face geometry, compound indoor ten, symbols, line-cutters and multi-spot handling verified.
- [ ] Failure/retry cases preserve the prior plan and entered scores; no duplicate generation/application.

## Data and operations

- [ ] Export CSV detail/PDF summary and role checks verified; downloads expire after 24 hours.
- [ ] Closure revokes access immediately and completes anonymisation within 30 days.
- [ ] Anonymisation inventory includes free text, AI payloads, contributions, histories, jobs and exports.
- [ ] Under-16 child management is transferred or explicitly closed before parent-account closure.
- [ ] Backup retention never exceeds 30 days; log/security retention jobs configured.
- [ ] Restore rehearsed in isolation; closure suppression applied before access.
- [ ] Pilot recovery targets RPO/RTO 24 hours documented and supported by the runbook.
- [ ] Current actual processing/privacy arrangements reviewed, including junior data and provider handling.
- [ ] Secrets/configuration, least-privilege credentials and privileged-role MFA configured.
- [ ] Staging/production credentials and databases separated.
- [ ] Costed Azure Europe configuration includes all services; testing total fits EUR 45 or shortfall is reported before provisioning.
- [ ] Alerting, failed-job queue, generation limits and storage lifecycle enabled without sensitive log payloads.
- [ ] Backward-compatible migrations and version rollback/restore procedures recorded.

## Pilot and production execution

- [ ] Identify operator/support contact and named pilot participants: 5–10 athletes, at least two coaches and one parent-managed junior.
- [ ] Arrange four-week pilot dates and feedback channel; no business success scorecard.
- [ ] Record production budget and approved hosting configuration before production provisioning.
- [ ] Confirm domain ownership, DNS, HTTPS, email and renewal responsibility.
- [ ] Record release commit/version, limitations and rollback version.
- [ ] Deploy reviewed version; verify homepage, sign-in, plan and scoring with authorised test accounts.
- [ ] Verify unrelated account is denied; verify closed account cannot sign in.
- [ ] Confirm monitoring/backup jobs after deployment.
- [ ] Gather feedback and prioritise fixes before expanding access.

## Release record

| Field | To be completed when executing release |
|---|---|
| Operator/support | Name and contact |
| Participants/dates | Actual pilot list and agreed dates |
| Hosting/AI | Region, services, provider/model and cost evidence |
| Domain/version | Actual domain and deployed commit |
| Restore/rollback | Evidence and runbook reference |
| Known limitations | Concrete limitations and issue links |
| Release authorisation | Recorded approval for actual deployment |
