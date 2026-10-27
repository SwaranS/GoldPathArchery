# Scoring system

Implemented on `feature/scoring-system`. The supplied 27 October 2026 scoring requirements define this increment; the user's request authorizes implementation. No official event certification is claimed.

## Setup

From `app/`, with the normal database/environment configured:

```sh
python manage.py migrate
python manage.py seed_scoring
```

The seed command creates missing practice configurations and leaves existing administrator edits intact. It includes 20/40/60/80/122 cm targets, explicitly labelled 60 cm junior faces, full/vertical triple/triangular triple/four-face layouts, indoor 30/60, 720 and Double 720. A Double 720 is represented by two ordered stages. Administrators can add custom multi-distance rounds. Seed size/layout combinations are configurable practice examples, not assertions of official eligibility.

## Administration and access

Use Django admin for Target faces, Scoring rule sets and Round definitions. Standard Django staff access plus the corresponding model permissions are required; selecting a Coach role does not grant these permissions. Add a stage with positive distance, 1–100 ends and 1–36 arrows per end. Every round needs at least one stage. Round maximum is calculated from stage counts and maximum configured points. Configurations can be duplicated (inactive by default), activated and deactivated.

Target geometry and scoring rules are separate JSON configurations. Geometry uses `spots: [[centre_x, centre_y, radius], ...]` on a square canvas from −1 to 1, with increasing normalized `rings` radii. `diameter_cm` identifies the nominal individual face size; canvas position is not a physical calibration. Rules use increasing `zones`, each with `radius`, unique `symbol`, integer `points`, optional boolean `x`; miss is always `M`, zero points. X is explicitly seeded as ten points with a separate X flag. Compound indoor ten uses radius 0.05 rather than 0.1. A point exactly on a scoring boundary earns the inner zone. The UI allows an observed score override with a reason. Tap precision does not replace judging or account for shaft diameter. Multi-spot sessions record spot identity and warn about prior use; event-specific repeated-spot penalties are not automated.

Athlete, guardian and coach access reuses `accounts.permissions`. All session/equipment reads and writes enforce authorization on the server. Coaches can view their linked athletes but cannot log scores. Existing age and adult-parent-grant rules apply. The session administration page is read-only except for an explicit permission-checked verification action. Administrators with `scoring.change_scoringsession` may verify completed competition results without holding an athlete relationship. Verification locks scores and lifecycle edits. Authorized athlete/guardian users can still soft-delete or restore a verified result, retaining the lock and history.

## Routes and use

Open an athlete's profile and choose **Scoring sessions and personal bests**:

- `/scoring/athlete/<uuid>/`: history, compatible comparison groups, separated Training/Competition PBs, physical-arrow averages and date filtering.
- `/scoring/athlete/<uuid>/start/`: choose a configured round and explicit context, or custom training target/rules/distance/counts. Bow and arrow set are optional.
- `/scoring/athlete/<uuid>/equipment/`: save bow setups, arrow sets and unique physical-arrow identifiers; archive/restore equipment. Save a new setup for changed specifications.
- `/scoring/session/<uuid>/`: enter/correct arrows, pause/resume, review/complete, reopen completed training, inspect totals, distribution, impact positions and audit history, confirm soft-deletion/restoration or invalidate.
- `/scoring/session/<uuid>/save/`: CSRF-protected JSON POST. Each mutation requires `action`, `version`, UUID `key`. Shot requests also specify zero-based `position`, `method` (`manual` or `tap`), optional saved `arrow`, and score `symbol` for manual entry. Tap requests specify normalized `x`, `y`, zero-based `spot`, optional observed `symbol` and correction `reason`.

Manual buttons and target taps edit the same shot slots. Manual entry clears coordinates. A tap computes its value server-side; mismatching observed values require a reason. SVG transforms preserve coordinate mapping when scaled. Numeric coordinate entry provides a keyboard alternative. Repeated requests with the same key and identical payload are idempotent, including retries after a lost response. Different data with a reused key or stale versions return 409. The UI blocks input during saves, suppresses double-tap entry, retains failed requests in memory for retry and warns before leaving with an unsaved change. Keep the tab open while offline; durable offline synchronization is outside this release.

## History and derived results

Every session copies ordered stages, face size/layout/geometry, rule zones, division, category and verification policy into a snapshot. Changes to shared configurations do not alter existing or resumed sessions. Equipment details and physical-arrow labels are also copied. Snapshot fields are not exposed through write APIs or editable admin forms. All score and lifecycle mutations append actor/time/before/after/reason audit records; audits cannot be modified or deleted through admin.

Only fully recorded, completed, valid, non-deleted sessions qualify for PBs. Competition results requiring verification qualify only once verified. Training and Competition remain separate. Compatibility includes evaluator version, bow division, category, ordered distances, face dimensions/layout/geometry, scoring rules, ends and arrow counts. Display names are excluded from compatibility. PBs are derived on read, so reopening, correction, deletion, restoration, verification and invalidation cannot leave stale cached bests.

End/running totals, average, progress, 10/X/9 counts, distribution and individual impact coordinates are available. History lists results with comparison-group identifiers; compare totals only within the same group. Arrow reports include only identified shots, count misses as zero, filter each shot by the athlete's local recording date and keep bow/target/rules/distance conditions separate. Archived equipment remains in historical reports.

## Verification and limits

Run from `app/`:

```sh
python manage.py check --settings=config.test_settings
python manage.py makemigrations --check --dry-run --settings=config.test_settings
python manage.py test --settings=config.test_settings --noinput
```

SQLite tests cover application behavior. PostgreSQL-specific locking tests elsewhere in the project require the normal PostgreSQL test environment. No retention duration has been defined, so soft-deleted records are retained without an automated purge. Advanced hit-map/grouping analysis, graphical trend charts, calibrated shaft/line contact, event penalty evaluators, partial completion and full offline synchronization remain follow-on work. Verification is a deliberate administrator action; no external official-results integration is assumed.
