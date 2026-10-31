# Club group training programmes — Milestone 5

M5 adds coach-led training groups, versioned programme briefs and consent-based
personal draft requests. It reuses the existing Django `GeneratedPlan` queue and
training engine. The application currently produces reviewable drafts: there is
no connected activation workflow or live session runner in this increment.

## Enablement and routes

`CLUB_PROGRAMMES_ENABLED` defaults off. Clubs and memberships must also be enabled.
Review migration `clubs.0006_clubprogramme_clubprogrammeassignment_and_more` before
enabling it in an authorized environment. No running application database was
migrated during implementation.

Start at `/clubs/programmes/`, also linked from My clubs and club dashboards.
An accepted club coach can create a group assigned to themselves; club admins
can assign or replace its coach. Authoring and management require fresh MFA.
The exact accepted club coach role controls programme authoring; a global coach
role alone does not. Admins can archive a group whose coach has lost their role.

| Route | Purpose |
| --- | --- |
| `/clubs/<club>/training-groups/new/` | Create a group |
| `/clubs/<club>/training-groups/<group>/settings/` | Edit or archive a group |
| `/clubs/training-groups/<group>/` | Authorized group view |
| `/clubs/training-groups/<group>/invite/` | Invite a current club member |
| `/clubs/training-group-members/<member>/respond/` | Accept, decline or leave |
| `/clubs/training-group-members/<member>/remove/` | Authorized removal |
| `/clubs/training-groups/<group>/programmes/new/` | Create a programme revision |
| `/clubs/training-groups/<group>/programmes/<programme>/edit/` | Create another revision |
| `/clubs/programmes/<programme>/` | Review, publish or archive |
| `/clubs/programmes/<programme>/offer/` | Offer the published revision |
| `/clubs/programme-assignments/<assignment>/` | Owner consent, personal versions and private progress |
| `/clubs/programme-assignments/<assignment>/coach-progress/` | Separately authorized counts only |

Groups support zero, one or multiple memberships per athlete. Training groups
and facility access groups are independent: joining one does not grant venue
access. Group invitations expire after 14 days and require a separate response
from programme offers, which also expire after 14 days. Declining creates no
plan. A fresh explicit offer can follow a decline or withdrawal; old consent
cannot be replayed. Leaving and rejoining creates a new membership version.

## Programme and personal versions

The coach supplies a title, group instructions, dates, discipline, programme
archetype, round format and 1–14 weekly session references. Weekly references
contain a weekday, club-local clock time, duration and description. They are
programme guidance, not bookings or generated individual session schedules.
Each save creates an immutable revision; publication is explicit. Offers pin
the published revision, including its copied group/club/timezone details.
Later edits never replace an accepted source revision.

The athlete or currently authorized guardian accepts using their own declared
baseline and availability. Source dates and weekly availability are defaults
that can be customized. Group discipline is bound to the individual request.
No athlete's draw weight or arrow volume is copied to another athlete. Acceptance
creates a new queued personal draft. Customization creates another linked draft
version; existing personal plans and previous ready drafts remain intact.
The latest queued version alone may complete for that assignment.

The durable `generate_training` worker checks ordinary personal plan permissions
and current assignment authorization before and after generation. It uses the
existing periodization engine, preserving its volume, deload, poundage, taper
and division-specific scoring safeguards. Group free text is retained as source
guidance alongside the generated roadmap; it is not an instruction to the engine.
Private customization notes are stored separately and excluded from the roadmap.

The coach cannot accept on an athlete's behalf or read their individual draft
through a club role. Existing independent personal coach/guardian relationships
retain their established personal-plan permissions. A guardian can consent for
an eligible junior without creating a junior login. At age 16 guardian consent
authority ends under the existing policy; any continuing read access follows
the ordinary guardian rules.

## Progress and revocation

Progress is an owner-maintained session count and private note, available after
the current draft is ready. It is self-reported, not inferred adherence, a score
record or proof that a session occurred. Counts are bounded by the generated
draft's session count. Private notes are never returned to club recipients.

The separate `programme_progress` consent scope shares only counts, programme
title, assignment identifier and update time. It uses existing explicit club
grants with current recipient checks. Each result is checked against the exact
source club, preventing another club's grant from exposing it. A club coach role
alone grants no private progress. The assigned-coach progress route additionally
requires fresh MFA and current group responsibility.

Withdrawal, departure, coach-role loss, coach replacement or archival prevents
future authorized assignment generation and current source-based progress
sharing. Previously ready personal drafts and accepted source history remain
available through personal permissions. Group departure also cancels pending
offers. Closed accounts and lost guardian authority are rechecked. No historical
consent automatically revives after a role is reissued or a membership rejoined.

## Migration, rollback and release review

Migration 0006 adds seven club-owned tables: training groups, group members,
programmes, revisions, assignments, assignment-plan links and progress. It adds
constraints and protected references, including a nullable link to the existing
`training.GeneratedPlan`; it does not alter personal score, biomechanics or
training-plan table schemas. Concurrent consent is serialized and constrained
to one new draft for a given accepted version.

Before enablement: review the migration and permission/privacy behavior, back up
the database, inspect `migrate --plan`, then apply only in the authorized target.
Deployment remains manual-only. Startup can apply additive migrations even when
the feature flag is off. Turning the flag off disables M5 routes and new marked
generation jobs while retaining existing personal draft access and additive
tables. Do not reverse migrations after storing programme/consent history.

Real release still needs a staging coaching-group walkthrough with separate
coach, athlete and guardian identities, assistive-technology review, and operator
approval of retention/erasure handling for private notes and accepted history.
Local synthetic evidence does not supply these approvals. No deployment or
running-app configuration changes are part of this implementation.

## Reproduce local checks

From `app/`, with the repository root in `PYTHONPATH`:

```text
python manage.py test --settings=config.test_settings --noinput
python manage.py test --settings=config.clubs_test_settings --noinput
python manage.py check --settings=config.test_settings
python manage.py makemigrations --check --dry-run --settings=config.test_settings
```

From the repository root, also run `pytest -q tests/training_plans`. The PostgreSQL
settings target only the disposable localhost:55440 database. Browser, migration,
feature-off and backup/restore procedures are in
`tests/clubs_validation/README.md`. Django's optional migration formatter could
not launch on Windows (WinError 623); schema generation and consistency checks
succeeded.

## Local validation evidence

- Full PostgreSQL suite: 340 Django tests passed (119.784 seconds), including
  concurrent programme acceptance and existing PostgreSQL-only regressions.
- Full SQLite suite: 340 tests passed (53.250 seconds), with 10 PostgreSQL-only
  checks skipped.
- Training engine: 33 pytest tests passed (1.17 seconds).
- Django system check: no issues; migration consistency: no changes detected;
  `git diff --check`: clean.
- Browser/axe: 30 desktop/mobile views and 18 workflow checks passed; zero
  automated WCAG A/AA violations, duplicate IDs or horizontal overflow.
- All 14 migration/preservation/feature-off/backup/restore/cleanup checks passed.
  Restore fingerprints include the seven M5 models and both generated plans.
  Both fresh disposable databases were removed after the rehearsal.

Sanitized reports and representative synthetic screenshots are retained in
`docs/validation/clubs-m5/`. They identify the uncommitted `c46f373-dirty` source
baseline; they do not claim a committed CI result. Raw database dumps, fixture
sessions and private storage copies remain excluded from source control.
