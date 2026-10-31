# M4: facilities and availability

Implementation branch: `codex/club-facilities`, from main `84f7bbf` (merged M3).
Scope is CLUB-013 and its security/integration requirements. This adds venues,
shooting areas, recurring/seasonal hours, date exceptions, restricted access
groups and controlled photos. No reservations, bookings, payments or implied
capacity guarantees are introduced. Existing athlete, equipment, scoring and
training schemas and personal access policies remain unchanged.

## Entry points and feature gate

`CLUB_FACILITIES_ENABLED=1` additionally requires `CLUBS_ENABLED=1`.
The new flag defaults off. Membership tables are reused for access decisions;
facility access does not depend on enabling athlete data sharing.

- Public club profile: Facilities and availability link.
- My clubs: Facilities links for active memberships, including represented juniors.
- Club dashboard: Manage facilities and availability.
- `/clubs/<club UUID>/facilities/`: audience-filtered venue list.
- `/clubs/facilities/<facility UUID>/`: filtered venue, areas and photos.
- `/clubs/areas/<area UUID>/availability/`: local calendar, 1–31 days per request.
- `/clubs/<club UUID>/facilities/manage/`: administration, including archived history.
- `/clubs/<club UUID>/facilities/groups/new/`: create a facility access group.
- `/clubs/facility-photos/<photo UUID>/`: controlled image bytes; no storage URL.

Public list/detail/calendar endpoints also support `?format=json`. They use the
same services and explicit field allowlists as HTML, with private no-store
responses. No precise address or coordinates are handed to public templates when
the actor lacks the location audience. Unknown/private/inactive resources return
404. Location audience never bypasses the outer club/facility audience.

## Permissions and history

Only current active club administrators can create/edit/archive venues, areas,
hours, exceptions, access groups or photos. Fresh account-bound MFA is required
on all facility administration HTTP routes and administrator projections of
public/detail/calendar/image endpoints. Membership managers and platform staff
do not acquire facility control merely from those roles.

Audiences are public, active club members, current club coaches, administrators
or a named facility access group. A private club remains hidden from non-members
even when an inner facility says public. Areas, schedules and individual photos
can narrow visibility further. Public descriptive text must not contain location
details intended for a more restricted audience; the form labels explain this.

Facility access groups contain explicit current memberships of the same club.
They do not create programme assignments or athlete-data permissions. A managing
guardian may represent a child member under the existing manage_grants policy;
the guardian does not join personally. Authority is recalculated after age,
relationship, closure or membership changes. Ending membership removes access
group links and audits that withdrawal; rejoining does not silently restore them.
Archiving a group immediately excludes its ordinary members from group audiences.
Future M5 training groups may explicitly relate to these access groups; no such
relationship is fabricated in M4.

Venue records belong to one club. Two clubs may record the same physical venue
independently without receiving access to each other's venue or schedules. UUIDs
and posted parent IDs cannot move a record between clubs. Descriptions are escaped.
All mutations use the club row lock and optimistic resource versions; stale forms
return 409. Concurrent overlapping hours cannot both pass validation. Mutations
produce fixed audit codes and references, never addresses, coordinates, photo
contents or exception reasons in operational logs.

Unchecking Active archives a record. Facility/area archival hides all descendant
public routes and photos but retains rows and image blobs. Historical references
use PROTECT rather than destructive cascading deletion. Archival can be reversed
by an authorized administrator explicitly editing the current version.

## Recurrence, seasons and exceptions

Hours belong to an area and use the facility's validated IANA timezone. Each rule
has weekday, effective start/end dates, same-day local start/end, priority,
audience and active state. Multiple separate slots per day are supported.
Overnight hours must be split across weekdays. Distances are positive metres up
to 1000, with 1–100 distances per area; lane/target capacities are 1–1000.
Facilities support paired latitude/longitude with standard geographic bounds.

For each local date:

1. The highest-priority active date exception wins. A closure removes all hours;
   a replacement supplies 1–20 non-overlapping windows for that date or date range.
2. Without an exception, only recurring rules at the highest applicable priority
   are used. Higher-priority seasonal rules replace the entire lower-priority
   day's schedule; add several same-priority rules for multiple seasonal slots.
3. Rules at the same priority cannot overlap their weekday/date/time ranges.
   Exceptions at the same priority cannot overlap date ranges.
4. Audience filtering is applied to the winning rules/exception. A hidden winner
   suppresses lower-priority public hours; its reason and identity are omitted.
   Otherwise a private closure could accidentally advertise an open range.

Dates/times are projected with zoneinfo. Both candidate folds are round-tripped
through UTC. Ambiguous or nonexistent boundary times are omitted with a clock
change confirmation notice; no arbitrary fold is silently selected. Valid
intervals expose local times/offsets and aware UTC endpoints. A valid window may
span a clock transition when both endpoints are unambiguous.

Local holiday closures are administrator-entered exceptions. No third-party
holiday feed, guaranteed capacity or booking functionality is claimed.

## Photos and orphan recovery

Facility photos use the existing bounded metadata-stripping JPEG normalization:
JPEG/PNG only, up to 5 MB and 12 million pixels, re-encoded at a maximum 2400 pixels.
Up to 20 active photos per facility are supported, with at most one primary photo
enforced in PostgreSQL. Primary switches are atomic and advance affected versions.
Caption and audience are explicit; visual image content may reveal a location
even after EXIF metadata is stripped, so the UI makes audience choice clear.

Storage is isolated from verification evidence configuration/cleanup:

```text
CLUB_FACILITY_PHOTO_BACKEND=local
CLUB_FACILITY_PHOTO_ROOT=<absolute path outside served static/media folders>
```

Local storage requires an explicit private mount and OS access controls. No local
folder or mount was provisioned in the running app by this implementation.
For production photos use:

```text
CLUB_FACILITY_PHOTO_BACKEND=azure
CLUB_FACILITY_PHOTO_AZURE_CONNECTION_STRING=<secret configuration>
CLUB_FACILITY_PHOTO_AZURE_CONTAINER=<private container>
```

The adapter checks HTTPS before authenticated container-properties I/O and rejects
public containers. Production configuration rejects local/unknown photo backends
and incomplete Azure settings. Leaving the backend disabled permits venues and
calendars to operate without photo uploads. Verify actual storage encryption,
region, privacy and permissions in the authorized environment before release.

Upload intents are committed before blob writes, with authorization/version
rechecked under lock before registration. Interrupted or failed cleanup leaves
a retryable intent. Outer transactions are refused for this workflow. Downloads
recheck current feature, club, facility, photo, audience and MFA where required,
return JPEG/no-store/nosniff, and never reveal blob keys or original filenames.
Archive hides the image but preserves the blob for historical/retention review.

Clean orphan facility uploads older than 24 hours separately from evidence:

```text
python manage.py cleanup_facility_uploads                 # counts only
python manage.py cleanup_facility_uploads --apply --limit 100
```

This never deletes a linked photo, including archived photos. Failed storage
deletion leaves the intent for retry. Cleanup scheduling and lawful archival/
erasure retention need operator review before real onboarding; no scheduler or
automatic historical-photo erasure policy is invented here.

## Event integration interface

`facilities.event_conflicts` accepts a scoped area, aware UTC interval, actor and
optional provider. The M6 provider must return only actor-authorized event
summaries for that club/area/interval. The calendar highlights returned overlaps.
Without a provider the response explicitly reports event checks as unconnected;
the UI says to confirm events with the club. No event models, registrations or
actual event-conflict service exist in M4.

## Migration and release review

Migration 0005 adds seven club-owned models (plus the group/member join table),
constraints and protected references. No personal-data backfill or changes to
existing score/training/equipment tables occur. Schema testing uses disposable
databases only; no running application database has been migrated for M4.

Before enabling: review the migration, back up database and private blobs, inspect
`migrate --plan`, apply in the authorized test environment, configure storage if
photos are wanted, then enable the flag. Startup applies migrations during an
authorized deployment even if the feature is off. Deployment is manual-only.

Rollback is feature-off while retaining additive tables. Do not reverse the
migration after storing venue/history/photo records. Database backup alone does
not include private blobs; the rehearsal verifies an isolated copy of facility
photo objects as well as database/group membership fingerprints.

Release gates remain human permission/privacy review, actual storage validation,
cleanup/retention approval, assistive-technology review and a manual calendar
walkthrough through a seasonal change, closure and replacement day. The synthetic
browser test is local engineering evidence, not a staging or legal sign-off.


## Local validation evidence

- Full PostgreSQL suite: 312 Django tests, OK (100.141 seconds), including the new
  competing-rule locking check and all existing PostgreSQL-only regressions.
- Full SQLite suite: 312 tests, OK (53.839 seconds), nine PostgreSQL-only skips.
- Training engine: 33 pytest tests passed (1.12 seconds).
- System check: no issues; migration consistency: no changes detected;
  git diff --check: clean.
- Browser/axe rehearsal: 25 desktop/mobile views and 16 workflow checks passed,
  zero automated WCAG A/AA violations, duplicate IDs or horizontal overflow.
- All 14 migration/preservation/backup/restore/cleanup checks passed. Restore
  fingerprints include access-group membership links, and facility photo blobs
  were copied and verified separately. Both disposable databases were removed.

Sanitized reports and representative screenshots: `docs/validation/clubs-m4/`.
They record the `84f7bbf-dirty` uncommitted source baseline accurately; no committed
CI result is implied. No actual club, storage credential, login cookie or live
verification outcome appears in the retained evidence.

Reproduce from `app/` with the repository root in PYTHONPATH:

```text
python manage.py test --settings=config.test_settings --noinput
python manage.py test --settings=config.clubs_test_settings --noinput
python manage.py check --settings=config.test_settings
python manage.py makemigrations --check --dry-run --settings=config.test_settings
```

The fixed PostgreSQL test settings use only localhost:55440 synthetic test
credentials. See tests/clubs_validation/README.md for the browser/restore procedure.
Django's optional migration formatter could not launch on Windows (WinError 623);
migration generation and schema consistency checks succeeded.
