# Club data sharing: Milestone 3

Branch `codex/club-permissions`, based on merged M2 (`d7fb4b9`). This adds explicit
club-dependent data consent without expanding the existing broad personal
athlete permissions. No application database migration or deployment is part of
implementation. Migration `clubs.0004` creates one club-owned grant table.

## Configuration and navigation

Enable only after migration review: `CLUBS_ENABLED=1`,
`CLUB_MEMBERSHIPS_ENABLED=1`, `CLUB_DATA_SHARING_ENABLED=1`.
The third flag defaults off. My clubs links authorized athletes/guardians to
Manage data sharing and recipients to Shared athlete data.

- `/clubs/athletes/<uuid>/sharing/`: grant/revoke and own sharing history.
- `/clubs/shared/`: current recipient permissions by category.
- `/clubs/athletes/<uuid>/shared/<category>/`: protected category view; the same
  checks apply to `?format=json`. Responses are no-store.

## Consent and permission boundaries

The owner or an authorized managing guardian chooses a club, exactly one named
club coach OR one bounded club role, categories, purpose, start and expiry.
Role consent explicitly includes current and future active holders of that role.
Membership alone, staff status, a global coach label or a superuser flag do not
authorize sharing. Recipient selection shows only coaches of the athlete's
eligible clubs. The service rechecks that the selected coach belongs to the
selected club, not merely another eligible club.

Grants require active verified club membership for the athlete, an eligible
recipient and live authority of the original approver. Existing manage_grants
rules control guardian authority; turning 16 invalidates guardian-issued consent
even if the parent retains an adult editing grant. Child-only profiles need no
login. Closed profiles/accounts and expired/future/revoked grants fail closed.

Named coach consent is bound to a coaching appointment that already existed when
consent was issued. Revoking and later reappointing that coach does not revive
the old grant. Ending membership revokes dependent grants and audits each
transition; rejoining never restores them. A suspended/archived club cannot
authorize reads or generation. Independent direct coaching relationships retain
their existing permissions and are not revoked by club consent changes.

Grants are immutable except revocation. To change scope/purpose/recipient/time,
revoke and issue a replacement. Defaults are 30 days in the form, with a mandatory
expiry and a maximum 365-day window. These are conservative engineering defaults,
not a substitute for operator privacy/retention approval.

## Supported categories

| Category | Shared fields / actions |
|---|---|
| Basic profile | Display name and disciplines; no birth date, account email, goals or medical data |
| Training read | Generated draft dates, archetype, weekly totals and prescribed session/drill schedules; no raw contexts, pain flags, linked private IDs or notes |
| Training draft generation | Request a new draft through the existing durable worker; also requires training read consent |
| Scoring read | Session time/status and individual arrow symbols, points and X flags; excludes equipment/arrow snapshots and deleted sessions |
| Equipment read | Legacy inventory, current component name/manufacturer/model/category/status and configuration names; no serial references, receipts, maintenance notes or media URLs |
| Sight marks read | Distance, unit and sight value; no private notes or equipment snapshots |

The read views return at most 100 sessions/plans or 1000 inventory/sight-mark
rows per collection. They do not grant unrestricted exports or score writes.
Existing file endpoints remain protected by their original policy; club grants
never confer file or receipt access. Tests probe direct/saved file URLs.

The existing generated-plan module has no connected plan editor, activation or
session-log workflow. Accordingly, the UI does not promise those operations:
training_edit authorizes requesting a new generated draft only. It cannot replace
or activate a personal plan. Shared recipients see a scoped summary at training
detail rather than the original broad renderer. The worker checks permission
both before generation and before persisting a result, so revocation during a
provider call cannot commit the generated result.

Programme progress is not offered because programmes/assignments do not exist
until M5. Independently selectable photo
permissions and future programme progress need their own category adapters; they
must not be implemented by granting the generic athlete view permission.

## Audit, privacy and rollout

Grant issue, revoke, membership termination and scoped reads produce fixed action
codes with resource references and request correlation. Purpose, categories,
scores, notes and private payloads are not copied into operational logs. Existing
bounded denied-access telemetry applies to club HTML/JSON routes. Platform audit
screens remain restricted to authorized reviewers with fresh MFA.

Before real onboarding, review the new purpose/consent retention and account
erasure inventory. Named-recipient account deletion cascades its grants rather
than leaving a recipientless live grant or blocking deletion; the minimal audit
reference remains under existing audit policy. Approver deletion makes access
invalid immediately. Athlete closure never grants residual access.

Apply migration only to a backed-up, authorized environment after artifact review.
All schema testing and restore rehearsals here use disposable databases. To roll
back functionality, disable the sharing flag and retain additive tables; do not
reverse the migration after writing consent history. Startup applies migrations
during an explicitly authorized deployment, regardless of feature flags.

## Validation and review gates

Automated tests cover categories versus operations, role/club boundaries, guardian
transitions, expiry/future start, revocation, membership/role loss, scoped training
jobs, worker rechecks, CSRF, JSON/HTML no-store responses, denied legacy routes,
private receipts and sanitization of scoring/training payloads. The local browser
rehearsal tests owner consent and revocation with real HTTP forms. Backup/restore
fingerprints include consent records.

Human security/privacy review, negative-access walkthrough, assistive-technology
testing, deployment configuration and synthetic staging sign-off remain release
gates. The current increment does not claim all future programme/editor/photo
adapters are implemented. Nothing is merged or deployed by this work.

### Local validation results

- Full PostgreSQL suite: 279 Django tests, OK (83.284 seconds).
- After the final schedule allowlist update: all 19 grant tests passed again on PostgreSQL.
- Full SQLite suite on final source: 279 tests, OK (eight PostgreSQL-only skips).
- Training engine: 33 pytest tests passed.
- System checks: no issues. Migration consistency: no changes detected.
- Browser/axe and restore evidence is stored under `docs/validation/clubs-m3/`.

Run Django tests from `app/` with the repository root in PYTHONPATH. The fixed
`config.clubs_test_settings` uses only the disposable localhost:55440 test account.
The browser harness creates two newly named disposable databases and removes
both after validation; it never uses the running app database or local reviewers.
Reports record the uncommitted `d7fb4b9-dirty` source baseline honestly; no committed
CI or deployment result is implied by these local artifacts.

Final browser rehearsal: 19 desktop/mobile views, 12 workflow checks, zero axe violations/duplicate IDs/overflow. All 13 migration/preservation/restore/cleanup checks pass; both disposable databases were removed.
