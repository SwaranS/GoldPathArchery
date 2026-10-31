# Clubs & Organisations — Milestone 1 review

Implementation branch: `feature/club-foundation`, based on current `origin/main`
(`806e5bf`). This isolated worktree preserves the separate equipment checkout and incorporates its now-merged main baseline.
Only M1 is implemented; M2–M9 are excluded. The feature is disabled by default.

## Behaviour and permissions

- `/clubs/`: search/profile pages contain only public, active, verified clubs and
  approved public fields. Private, suspended and archived profiles return 404.
- `/clubs/request/`: signed-in eligible actors can save a partial private draft,
  continue editing it, or submit a complete new-club/known-listing application.
  Drafts never enter the reviewer queue or another reviewer's admin views.
- `/clubs/claims/<uuid>/`: applicant-owned status, decision history and responses
  to information requests. Submitted applications cannot be silently edited.
- `/clubs/verification/`: staff need the explicit `clubs.review_club_claim`
  permission AND MFA authenticated within the last five minutes. Self-approval
  and self-recorded evidence are denied, including for superusers. Staff status,
  the global Coach role and Google sign-in alone do not satisfy these controls.
- Approval requires unexpired positive independent contact evidence. Duplicate
  candidates use Unicode-normalized names, location/country, website domains and
  federation numbers. Similarity assists human review; it never proves ownership.
  Reviewers must explicitly resolve candidate warnings before separate creation.
  The most recent contact check must confirm authority; a later negative, expired
  or purged check cannot fall back to an older positive result. Selected known-club
  identity, provenance and location are shown separately from duplicate hints and
  require explicit confirmation. A signed target snapshot rejects approval if the
  directory identity changes after review or the token belongs to another claim.
- Draft saves, evidence registration, review decisions and information responses
  require the current claim version, checked under the claim lock. Every mutation
  advances it. Stale HTTP forms return 409 without side effects; reload using the
  page link before resubmitting. Missing versions cannot bypass the service guard.
- Approval locks the claim, a stable permission row and relevant known listing,
  then creates the club, initial membership, accepted administrator role and audit
  records in one transaction. Repeated/concurrent approvals cannot duplicate the
  initial club/admin. Existing-club replacement claims cannot transfer control;
  disputes/recovery remain platform case-management work in M8.
- `/clubs/<uuid>/manage/`: approved first-admin dashboard only. Suspended/archived
  clubs, inactive memberships, revoked roles, inactive accounts and closed athlete
  accounts are denied. Fresh account-bound MFA is required after the club role is
  authorized. This role grants no private-athlete access or platform reviewer rights.
- Known listings are curated with source/review date in Django admin. Club,
  submitted-claim, audit and security screens are read-only. Every club admin
  screen requires fresh MFA. Evidence has no generic admin/media URL.

The membership/role tables are only the bootstrap needed for M1. No joins,
member invitations, home club, sharing grants, facilities, programmes or events
are introduced. No existing athlete/scoring/guardian/equipment/training models
or URLs are rewritten. Existing age/closure policies are reused unchanged.

## Independent verification procedure

Use synthetic data until the release gates below are approved.

1. Search known listings and inspect potential duplicates before creating a club.
2. Locate the federation/official source independently. Do not rely on an
   applicant-provided website, mailbox or document as sole proof of authority.
3. Contact the official independently obtained contact. Record source URL,
   contact reference, check time, outcome and an explicit expiry. Do not invent
   evidence or contact outcomes. An unconfirmed/expired record cannot approve.
4. Review the proposed public profile and visibility before deciding. Request
   information when needed; applicant replies preserve the previous decision.
5. An independent authorized reviewer completes MFA and records approval/rejection
   and an applicant-visible reason. Keep private evidence out of that reason.
6. Confirm the applicant alone can open the new admin dashboard. For a private
   club, confirm directory, exact slug, application selectors and unrelated actors
   do not expose it. Confirm another actor's private athlete records stay denied.

## MFA, cache and storage configuration

`CLUBS_ENABLED=0` hides navigation and returns 404 for club routes. Install the
updated requirements, review the migration artifact and configure synthetic
staging before enabling. No application migrations or deployment were performed.

The `allauth.mfa` app supplies TOTP/recovery codes. Its upstream additive
migrations are also required, even while club routes are disabled. Existing
users without enrolled MFA keep their original login flow. Reviewers enroll at
`/accounts/2fa/`, then complete a challenge before verification or club admin
screens. Stale POSTs redirect without storing uploaded files or automatically
replaying decisions; return to the form and submit again after MFA.

The allauth minimum is 65.21.1: the reviewer gate explicitly passes the current
user to its account-bound authentication-record API. Unbound legacy records do
not authorize review. Both the real TOTP challenge and this negative case are
tested against the same version installed by clean CI builds.

Set `MFA_ENCRYPTION_KEYS` to a comma-separated Fernet key ring from secure secret
configuration, newest key first. Keep it distinct from `DJANGO_SECRET_KEY` and
back it up separately. Secrets are encrypted at rest; old keys allow rotation.
Missing/invalid keys fail closed. Never put keys, OTPs or recovery codes in source,
audit logs or PR descriptions. Test suite uses synthetic ephemeral keys.

A shared cache is required for production MFA replay/rate limits. The existing
PostgreSQL can serve Django DatabaseCache: set `DJANGO_CACHE_TABLE` to an approved
cache table name, then explicitly run `python manage.py createcachetable` during
an authorized rollout. This step is not automatic or executed here. Configure
shared caching and verify it across all web workers before onboarding.

Uploads default to disabled. Development can opt into
`CLUB_EVIDENCE_BACKEND=local` with an absolute `CLUB_EVIDENCE_ROOT` outside all
static/media roots; apply filesystem access control and encrypted disk storage.
Production uses `CLUB_EVIDENCE_BACKEND=azure`,
`CLUB_EVIDENCE_AZURE_CONNECTION_STRING`, and `CLUB_EVIDENCE_AZURE_CONTAINER`.
The adapter rejects public containers and non-HTTPS endpoints. Verify Azure
region, encryption at rest, network controls, credentials and permissions in the
actual deployment. Unit tests mock Azure; no live Azure outcome is claimed.
HTTPS validation occurs before even the authenticated container-properties request.

Production settings with clubs enabled fail system checks unless the MFA key
ring, Azure settings and shared-cache backend are configured. This does not
replace live environment verification. Feature-off deployments preserve their
existing checks and login behaviour.

## Evidence minimisation and cleanup

Attachments are optional JPEG/PNG only: at most 5 MB and 12 million pixels,
re-encoded to JPEG with original metadata/trailing content removed. PDF, Office,
SVG and other active documents are not supported. There is no antivirus service
integration; any future broader document support needs a scanning decision.

Opaque object keys have no public URL. Downloads recheck reviewer permission,
fresh MFA and expiry; return no-store attachments; and audit successful reads.
An applicant-reviewer cannot download verification evidence for their own claim.
Storage outages produce recoverable errors without exposing provider details.

Evidence expiry is mandatory and capped at 90 days from the contact check.
Expiry immediately denies use/download; it is also the payload-retention deadline.
Expired contact/source/outcome payloads are hidden from review pages immediately,
even if the daily deletion job has not yet run.
Before production, have the operator/privacy reviewer approve or shorten this
engineering default and define how claims/decisions/audit references are handled
by the wider erasure inventory. Do not promise indefinite retention.

Uploads persist a durable database intent before blob writes. A surrounding
application transaction is refused to prevent orphaning files through a later
rollback. Failures attempt immediate deletion; interrupted/failed deletions leave
an intent for retry. Successful evidence registration removes the intent atomically.

Schedule this operational command daily in the authorized environment:

```text
python manage.py cleanup_club_evidence                 # dry-run counts only
python manage.py cleanup_club_evidence --apply --limit 100
```

Apply mode deletes expired evidence blobs, scrubs source/contact/outcome/recorder
and storage key, and retains a minimal purge event/reference. It also removes
orphan upload intents older than 24 hours, preserves linked live blobs/current
uploads, and deletes operational security events older than 30 days. Retries are
idempotent; storage failures leave retryable records. Increase batching/frequency
if more than 100 records become due daily. Scheduling is a deployment task, not
silently provisioned by this PR.

Business audit records contain fixed action codes, actor/resource references,
UTC time and server-generated correlation IDs. Separate denied-access/MFA events
are rate-limited to one per actor/action/minute and contain no URLs, query strings,
addresses, tokens or private payloads. Admin interfaces cannot edit/delete logs.

## Validation

### PR #26 code-review fixes

Regression tests cover six findings: the selected directory target was not visible
outside duplicate hints; forms could overwrite or approve stale application state;
older positive evidence could override a newer negative check; expired private
contact details remained rendered until purge; Azure HTTPS validation happened
after the first authenticated network request; and listing-curation audits missed
the web request correlation. These are fixed on the PR branch; staging/visual and
environmental release gates below remain open.

Run from `app/` with the workspace virtual environment and set `PYTHONPATH` to the
repository root (required by the existing training imports). In PowerShell use
`$env:PYTHONPATH = (Resolve-Path ..).Path`. Exact final outputs are
recorded in the draft PR. The local PostgreSQL settings use only disposable
`127.0.0.1:55440` credentials, never deployment credentials.

```text
python manage.py check --settings=config.test_settings
python manage.py makemigrations --check --dry-run --settings=config.test_settings
python manage.py test --settings=config.clubs_test_settings --noinput
python manage.py test --settings=config.test_settings --noinput
```

The current-main regression baseline also runs the merged equipment/training
modules. From the repository root, `python -m pytest -q tests/training_plans`
passes all 33 original generator/API tests.

The suite covers private/public visibility and selectors, claimant isolation,
private draft save/edit/submit, missing/expired independent evidence, replay and
competing approvals, self-approval, account age/closure, CSRF, valid/invalid TOTP
HTTP reauthentication, stale/deleted MFA, encrypted key rotation, read-only admin
permissions, bounded security logs, upload recovery/cleanup, mocked Azure privacy,
and migration forward/reversal without deleting legacy identities. Legacy account
and scoring regression tests run in the same full suite. Seven PostgreSQL-only tests
are skipped on SQLite and executed on PostgreSQL.

Production `check` and `collectstatic` also run using synthetic configuration and
a temporary static output directory; no live database connection or deployment.
Django's optional migration formatter could not launch (Windows WinError 623);
actual migration generation, consistency checks and tests succeed.

The reproducible headless Chromium rehearsal now exercises real local HTTP forms,
desktop/mobile rendering, axe scans, keyboard focus, platform/club administrator
MFA and private evidence. It replaces the earlier static-preview limitation without
controlling the user's native browser. See the [validation/release record](clubs-release-validation.md)
for machine evidence, screenshots, restore checks and the remaining human/staging
gates. This is not a real staging sign-off or complete manual accessibility certification.

## Migration / release controls

`clubs/0001_initial.py` adds only club-domain tables/constraints/indexes and
`clubs/0002_clubclaim_version.py` adds the claim's concurrency version;
allauth adds its existing MFA tables. No personal data backfill or automatic
home-club choice occurs. The test runner applies migrations only to disposable
SQLite/PostgreSQL databases, then destroys those test databases. The dedicated
migration test reverses/reapplies the club schema there and preserves legacy
identity/table checks.

`startup.sh` runs `migrate --noinput`: deployment applies these schemas even with
clubs disabled. Deployment is therefore a separate explicitly authorized step.
Capture backups and baseline account/score/plan counts before staging rollout;
verify preservation after synthetic walkthroughs. Application rollback/feature-off
should retain additive tables. Reversing clubs to zero after use deletes claims
and audit history and must not be treated as a safe production rollback.

Local browser/accessibility, cross-process DatabaseCache MFA, synthetic verification,
legacy-data preservation, isolated backup/restore, feature-off rollback and repeated
cleanup rehearsals are complete. CI runs the local rehearsal as an additional gate.

Draft-PR release gates still open in the actual environment:

- Human code/security/privacy review; no merge authorized.
- Human assistive-technology/device review (local automated browser checks passed).
- Independent verification process exercised end-to-end in synthetic staging.
- Live Azure private/encrypted access and cross-worker MFA/cache checks.
- Approved retention/erasure policy and demonstrated daily cleanup scheduling.
- Reviewed staging migration/backup/restore and rollback procedure.

No production/staging deployment or merge is part of this work. M2 begins only
from a reviewed/merged M1 base; disputes, recovery and complete lifecycle remain M8.

## Manual deployment gate

Pushes and pull requests run CI without deploying. To deploy the development app,
an authorized operator must manually run the GoldPathArchery CI and deployment
workflow on main and explicitly select the deploy input. Both validation jobs
must pass before deployment. Other branches cannot deploy through this workflow.
Startup still applies database migrations during an authorized deployment.
