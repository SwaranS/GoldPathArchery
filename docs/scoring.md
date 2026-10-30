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
- `/scoring/athlete/<uuid>/equipment/`: manage structured bows, arrow sets, physical arrows, specification revisions and sight marks; archive/restore records. Also available from the athlete Equipment tab at `/account/athletes/<uuid>/equipment/`.
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


## Equipment revisions and sight marks (R12 / T07)

Both equipment routes use one implementation. **Profile > Equipment** opens the selected athlete's equipment, with a link back to scoring history. Eligible athletes and editing parents manage records using the existing `edit_profile` grant. Read-only parents, junior athletes and linked coaches can view equipment and filter sight marks without score-writing permission or management controls. Current account, profile, relationship and grant checks run on every request and again under the athlete lock for writes.

Each `Equipment` row is a stable logical bow or arrow-set identity. `EquipmentRevision` stores complete, append-only specifications with a sequential revision number. The legacy name/division/details columns mirror the current revision for compatibility. Use **Revise** to change specifications; stale revision submissions are rejected and identical submissions do not add a revision. Equipment type cannot change. Optional measurement values must be positive and finite, with a matching supported unit; bow and arrow-set fields cannot be mixed. Spine remains a manufacturer specification string. No tuning recommendations are generated.

Physical arrows belong to the stable set, so revising a set preserves shaft identity and report continuity. New identifiers contain ASCII letters/digits, are case-sensitive and unique within a set (including archived arrows); the same label can be reused in another set. Optional arrow notes are saved. Equipment archive hides it from new selection without changing revisions, snapshots or individual arrow status. Restore is explicit; restoring a set leaves individually archived arrows archived. Archived arrows can remain on an existing shot during correction but cannot be newly assigned. The scoring selector hides those historical choices except on the shot that already recorded them.

Sight marks require an active current bow revision, positive distance (`m` or `yd`) and a text mark. They optionally capture an active current arrow-set revision, extension, windage, date and notes. Every reference is checked against the selected athlete. Marks are grouped by logical bow and sorted by physical distance (yards converted for sorting only), with a bow filter. A setup revision or archive makes its previous marks visibly **Historical setup**, never silently current. Archive and recreate a mark to correct it; mark archive/restore retains its recorded revision references.

New scoring sessions copy current revision IDs, numbers and all specifications into their equipment snapshot. Existing and resumed sessions are never relabelled. Arrow snapshots use the session's recorded set context even after a later set revision. Reports group by physical arrow and recorded bow/setup conditions; they display set IDs and bow revision numbers so reused labels remain distinguishable. An arrow-set revision alone does not split the same physical arrow's report when the bow and target conditions remain compatible.

### Migration and release

`scoring.0002_equipment_revisions_and_sight_marks` adds revision/sight-mark tables and arrow notes, then creates revision 1 for every existing equipment identity, including archived equipment. It copies only name, division and free-text details. It does not infer brand, measurements or spine from notes, rename legacy arrow labels, change arrow/set IDs or update any scoring/shot snapshot. Legacy missing bow divisions remain unknown in revision 1; supply a division when revising that bow before using it in a matching scoring session. Initial revision timestamps record migration time, not an invented historical setup date.

Back up and review the migration before the normal release process applies it. Do not reverse this migration after recording new revisions or marks without exporting/preserving that new data: dropping the new tables loses those records. Existing shared/production databases have not been migrated by this implementation. The deployment startup script already applies pending Django migrations, so deployment itself must be explicitly authorized.

Regression coverage: `scoring.test_equipment` covers structured validation, relationships/revocation/closure, cross-athlete references, history, stale revisions, sight-mark setup changes, individual archive/restore, both navigation routes and upgrade from the legacy scoring schema on a disposable test database. PostgreSQL row-lock behavior requires the normal PostgreSQL CI environment; local SQLite tests do not verify those locks.


## Advanced configuration scoring
Phase 2 equipment changes require a new session after the first arrow, including
correction, pause/resume and reopen flows. Equipment segments are not supported.
Before shooting, an equipment mutation may replace the selected setup atomically.
Configuration snapshots store exact component revisions. Sight marks remain tied
to exact versions; a later version never copies or endorses older marks.
