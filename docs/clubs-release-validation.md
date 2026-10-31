# Milestone 1 validation and release record — PR #26

Date: 31 October 2026. Scope: validation on the draft feature branch; **no merge,
deployment, live club verification, Azure provisioning or application-database
migration is authorized or performed**. All new runtime evidence below uses
fresh local databases and fictional actors. The feature remains off by default.

## Gate status

| Gate | Evidence completed | Still required before real onboarding |
|---|---|---|
| Automated correctness/security | Full PostgreSQL suite; claim/club isolation, CSRF, evidence expiry, self-approval, target binding, stale writes, audit and migration tests | Independent human review/sign-off |
| Browser/accessibility | Chromium desktop/mobile workflow; zero axe violations for scanned WCAG 2 A/AA and 2.1 AA tags, no overflow/duplicate IDs, keyboard skip-link focus; screenshots inspected | Human assistive-technology/device review; automated scans are not complete WCAG certification |
| Verification workflow | Actual HTTP forms: private draft → submission → real invalid/valid TOTP → private evidence → explicit target confirmation → scoped admin dashboard | Independent operator walkthrough in the actual staging environment; no real official contact outcome has been asserted |
| MFA/shared cache | Two independent Python processes compete for one TOTP code through PostgreSQL DatabaseCache: one succeeds; the other and a third replay fail | Configure/verify the actual deployed cache and MFA key handling across web workers |
| Migration compatibility | Existing synthetic athlete, guardian, equipment revision, plan and complete arrow-by-arrow score fingerprints unchanged after applying club/MFA migrations | Approved staging backup, counts and migration review |
| Backup/restore | Real `pg_dump` archive restored into a different fresh database; full legacy and club/role/audit/MFA record fingerprints match; retained MFA key decrypts restored factors | Actual hosting backup/restore rehearsal and operator acceptance |
| Rollback | Feature-off rollback leaves personal records/tables intact and hides club routes | Record the approved artifact/rollback operator; do not downgrade to code that removes MFA |
| Cleanup | Restored expired evidence purged; repeat returns zero; cloned blob directory isolated from source, which remains intact | Provision/monitor a daily scheduled job and demonstrate it in the intended environment |
| Private storage | Adapter tests reject public containers/HTTP; downloads require current reviewer MFA, attachment/no-store headers and live expiry | Actual Azure account/container, encryption/network/access review and read-only anonymous-access probe |
| Retention/erasure | Technical inventory and implemented limits below | Named operator/privacy owner decisions and an approved erasure procedure; no policy approval is inferred |

## Local evidence

The reproducible harness is [documented here](../tests/clubs_validation/README.md).
It creates only allowlisted `clubs_validation_<random>` databases on the dedicated
localhost test server, never inherits deployment credentials, and removes those
databases afterward. Its host, port and database role are checked before it can run.
It adds no test login route or test authentication bypass to the application.
Server-issued synthetic sessions substitute for external Google sign-in; the
actual TOTP challenge, CSRF forms, application permissions and private downloads run
through the browser. Google provider authentication itself is not a local-browser
claim; its existing regression coverage remains separate.

Committed, sanitized machine summaries:

- [Local migration/browser/restore checks](validation/clubs-m1/local-report.json)
- [Browser page/axe/keyboard results](validation/clubs-m1/browser-report.json)
- [Mobile application capture](validation/clubs-m1/application-mobile.png)
- [MFA challenge capture](validation/clubs-m1/mfa-challenge.png)

The raw synthetic backup, generated test image and full screenshots
remain under ignored local `tests/clubs_validation/artifacts/`. No credentials or
real verification evidence are committed. Reports identify a dirty working-tree
revision because validation precedes the commit; CI reruns the same harness against
the committed source. A fresh report is generated per run, never overwritten by a
later run. No source or restore test database is left running after completion.
The browser fixture is passed through stdin, not saved as a fixture file. Backup
session rows belong only to synthetic accounts in the disposable databases.

Validation also found and corrected a dashboard authentication gap: the first club
administrator now completes fresh account-bound MFA before dashboard access, just
as platform reviewers do. A recent factor alone still grants no platform reviewer
permission. The browser exercises both administrator types, and regression tests
check immediate denial after factor removal and unrelated-actor isolation.

The preservation fixture contains one adult identity, two athlete profiles
(including an under-14 athlete with no login), one managing guardian link, a bow and
immutable revision, one completed score with individual `X`, `10`, `M` arrows and
six scoring audit records, plus a draft generated plan. Full stored-value hashes
match after migration, browser workflow and restore. Club administration gives no
access to that unrelated athlete. The test restore receives a *copy* of synthetic
private blobs before cleanup; restoring SQL alone must never point cleanup at an
original production container.

## Release procedure to review — not executed in staging

1. Identify the actual staging target and private Azure storage namespace. Use
   synthetic accounts/data only. Assign a named independent verification reviewer.
2. Approve the schema/artifact and backup first. Capture legacy counts and stable
   score/equipment/plan snapshots. Review the MFA table additions and claim version.
3. Configure a valid separate MFA encryption key ring and private HTTPS Azure
   container. Record region/encryption, public-access denial, least-privilege service
   access and credential/key recovery. Do not publish credentials in the PR.
4. Configure shared DatabaseCache; explicitly create its table in the approved
   environment. Verify one-use TOTP and rate-limit state across actual workers.
5. After separate deployment authorization, apply the artifact/schema to staging
   with clubs initially disabled. Check legacy workflows and record counts.
6. Enable clubs only for the authorized synthetic staging rehearsal; complete the
   verification steps in [the operations runbook](clubs.md). Record actor, source,
   approval, audit correlation and negative-access outcomes. Do not confuse a
   federation listing or supplied email with ownership proof.
7. Configure a managed daily invocation of
   `python manage.py cleanup_club_evidence --apply --limit 100` using the reviewed
   artifact/environment. Record scheduler ID, last-success evidence, retry/alert
   ownership and remaining dry-run counts. Increase capacity if more records are due
   than the batch can clear. No scheduler has been installed by this PR.
8. Rehearse isolated database **and blob** recovery. Keep restored jobs, notifications
   and outbound integrations disabled until reviewed. Demonstrate feature-off
   rollback and preserved personal histories. Retain the current MFA-capable code:
   a pre-MFA code downgrade could remove factor enforcement and is not an approved
   rollback. No destructive schema downgrade after club data exists.
9. Obtain the human policy/security/staging approvals listed above. Real junior or
   club onboarding stays blocked until these are recorded.

The repository's existing workflow deploys the Azure development app on a successful
push to `main`, and startup runs migrations automatically. This PR adds a local
validation dependency to those existing checks; it does **not** turn deployment
into an independently approved manual action. Do not authorize a merge while
deployment is forbidden. If merge and deployment must be separate later, change or
gate that trigger first under review. No such main-branch action is taken here.

## Retention and erasure inventory for owner review

This records implementation facts and undecided policy, not legal/compliance
approval. No new retention decisions are silently made by this validation work.

| Data | Current control | Owner decision / remaining work |
|---|---|---|
| Evidence image, official source/contact/outcome/recorder | Explicit expiry; maximum 90 days from contact check; immediate view/use/download denial on expiry; cleanup deletes blob and clears private fields | Approve/shorten limits and verify physical Azure lifecycle/soft-delete/backups; demonstrate scheduled cleanup |
| Orphan uploads | Durable intent; failed writes try immediate deletion; cleanup retries intents older than 24 hours | Operational retry/alert ownership and storage-outage retention behavior |
| Operational security events | Payload-free actor/action/correlation/time; per-actor/action rate limit; cleanup after 30 days | Approve/shorten limit; assess aggregation/anonymisation needs |
| Application/claim text and applicant/reviewer identities | Applicant/private-review access; state history retained; account FKs use `SET_NULL` on account deletion | Decide retention for draft/rejected/approved claim text and map closure/anonymisation into the account lifecycle; no automatic claim-text purge is implemented |
| Applicant-visible decision/response text | Scoped private history; no copy in operational audit payloads | Decide lifecycle/retention and approved redaction/erasure mechanism |
| Membership/role history | Scoped minimal references; user/athlete links nullable; club archive does not delete athlete records | Define lawful retention/anonymisation when an account closes; complete later membership lifecycle separately |
| Business audit metadata | Fixed action codes and actor/resource/time/correlation references; admin read-only; actor nullable on account deletion | Approve retention/anonymisation and include all references in the erasure inventory; no indefinite retention promise |
| Backups and restored jobs/files | Local rehearsal checks recovery and source isolation only | Apply the existing platform backup policy; document key recovery, suppression/revocation reapplication and safe restored-job handling in the actual host |

An account/profile closure is not the same as physically deleting a `User` row.
`SET_NULL` alone must not be presented as an implemented closure/anonymisation job.
The unresolved inventory items therefore remain launch blockers, not passed tests.
