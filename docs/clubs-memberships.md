# Clubs Milestone 2: memberships, roles and home club

Implemented on `codex/club-memberships` from main `59c3c51`. This increment covers
CLUB-001/003/004/006/007/008. It does not introduce grants, facilities, programmes,
events, payments or private athlete analytics. Existing athlete, scoring,
equipment and training tables are unchanged.

## Feature gate and entry points

Both `CLUBS_ENABLED=1` and `CLUB_MEMBERSHIPS_ENABLED=1` are required. The second
flag defaults off; M1 navigation and verification remain available independently.

- `/clubs/memberships/`: own memberships, requests, appointments, management
  context and per-athlete home-club links. Context never changes permissions.
- Public profile: Request to join, when the administrator accepts requests.
- `/clubs/<uuid>/members/`: limited membership roster and pending actions for
  that club's active admins and membership managers, after fresh MFA.
- `/clubs/<uuid>/invite/`: create an invitation for a verified account email.
- `/clubs/invitations/<uuid>/`: recipient supplies the separate invitation code.
- `/clubs/appointments/<uuid>/`: accept/decline a role after fresh MFA.
- `/clubs/athletes/<uuid>/home/`: explicitly choose/clear home club.

## Permissions and operational choices

Public active verified clubs can receive join requests. Private clubs require an
invitation. Closing join requests never disables authorized invitations. Join
decisions recheck applicant and guardian authority; a manager cannot decide their
own request. Membership managers can approve/reject joins and invite/revoke
invitations. Only club admins change request settings, offer/revoke roles or
suspend/remove members. All management HTTP endpoints require fresh MFA.

Invitation tokens are random, stored only as SHA-256 digests, valid for 14 days,
single use and bound to a matching verified allauth EmailAddress. The inviter's
current role and the club lifecycle are rechecked on acceptance. Links contain
only a UUID; the code is submitted in the POST body rather than URLs/logs. The
code appears once to the inviter on a no-store page. Email delivery is not
implemented or claimed: share the invitation privately. Expired offers remain
historical pending records but cannot be accepted.

Role offers expire after 14 days and require acceptance by the member's eligible
account. Multiple predefined roles can coexist: admin, membership_manager, coach.
A child-only membership cannot hold a privileged role. Additional admins derive
authority from an accepted appointment by a current admin of a verified club;
they do not need a second first-claim approval. Original verified-claim links are
retained. Revocation takes effect immediately. These appointments do not transfer
ownership or resolve disputes; those remain platform recovery work in M8.

Guardian operations reuse `can(..., 'manage_grants')`, preserving the existing
under-16 managing-guardian rule and the athlete's authority from 16. A continued
adult parent edit grant or coach relationship does not authorize membership or
home-club changes. A guardian never becomes a member merely by acting for a
child. Eligible 14–15-year-old logins can see own membership status but cannot
perform membership writes. Closed accounts/profiles cannot exercise privileges.

Membership is a durable row; actions and audit metadata preserve join/leave and
role history. Left members can request again; suspended/removed members require
a new invitation issued after their membership ended. Reactivation never restores
revoked roles. Leaving/removal clears that membership's home-club preference and
records history, while preserving other memberships and all personal records.

Home club is never inferred from joining or administrative context. One nullable
preference per athlete records explicit changes with UTC effective timestamps.
Only active memberships in active verified clubs are eligible. Score/event
snapshots are untouched. Preference writes use optimistic versions; membership
and role changes serialize on the club row. Last-admin removal/resignation is
blocked until another eligible administrator has accepted their role; concurrent
departures cannot remove both administrators.

## Migration and rollback

Migration 0003 adds three club-owned tables, membership metadata, request settings
and appointment attribution; it expands roles and permits a null original claim
for accepted appointments. No personal-data backfill or default home club occurs.
The MFA encryption key and evidence storage remain configured as in M1.

Review the generated migration before applying it to any application database.
Only disposable test databases are migrated during implementation. For a later
authorized rollout: back up, inspect `migrate --plan`, apply migrations, then
enable the second feature flag. Rolling the flag off hides M2 routes and
navigation. Preserve forward-compatible tables and do not reverse 0003 after
membership/history records exist. Deployment remains manual and is not authorized
by this document.

## Validation and remaining release gates

Tests cover multi-club membership, invitation expiry/replay/recipient verification,
role acceptance and revocation, guardian transitions, cross-club identifiers,
last-admin concurrency, home history, CSRF, MFA, feature-off routes and immediate
denial after lifecycle changes. The isolated browser harness also exercises real
HTTP membership forms and audits desktop/mobile layouts. Backup/restore includes
the new action and home-club tables.

Before real onboarding: human permission/privacy review, retention/erasure review
for invitation email and membership/home history, assistive-technology review,
and a synthetic pilot on the authorized test site. No real email delivery,
federation verification, Azure check or staging sign-off is claimed.

### Local validation evidence

- Full PostgreSQL suite: 260 tests, OK (92.534 seconds); all locking checks executed.
- Full SQLite suite: 260 tests, OK (eight PostgreSQL-only skips).
- Training engine: 33 pytest tests passed.
- Django system check: no issues; migration consistency: no changes detected.
- Disposable HTTP/browser rehearsal: 17 desktop/mobile views, 11 workflow checks,
  zero automated axe WCAG A/AA violations, duplicate IDs or horizontal overflow.
- All 13 migration/preservation/restore/cleanup checks passed; the two disposable
  databases were removed. Original application records were not modified.
- Reports and representative screenshots: `docs/validation/clubs-m2/`.

Run Django commands from `app/` with the repository root in PYTHONPATH:

```text
python manage.py test --settings=config.test_settings --noinput
python manage.py test --settings=config.clubs_test_settings --noinput
python manage.py check --settings=config.test_settings
python manage.py makemigrations --check --dry-run --settings=config.test_settings
```

Run the isolated browser procedure from `tests/clubs_validation/README.md`.
The report records `59c3c51-dirty`, identifying the uncommitted implementation
under test rather than claiming this source was already committed or deployed.
The browser's synthetic sessions bypass Google sign-in only; real TOTP, CSRF,
role authorization and all membership mutations execute through HTTP.
