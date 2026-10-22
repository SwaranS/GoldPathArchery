# GoldPathArchery — Scoring and Equipment Specification

Status: Implementation baseline · 22 October 2026  
Authority: [01](01-product-decisions.md) · Acceptance criteria: [02](02-mvp-requirements.md)

## Preset catalogue

| App preset | Structure | Maximum | End size default |
|---|---|---|---|
| Indoor practice 30 | 30 arrows | 300 | 3 |
| Indoor 60 | 60 arrows | 600 | 3 |
| Indoor double 60 | 2 separately saved 60-arrow rounds | 1200 | 3 |
| Outdoor 720 | 72 arrows | 720 | 6 |
| Outdoor double 720 | 2 separately saved 72-arrow rounds | 1440 | 6 |
| Partial training result | Any positive recorded subset of a selected format | 10 × actual scored arrows | Selected format |

These are application format definitions, not universal event eligibility claims. Double 720 is two 720s; it must never be confused with the future multi-distance 1440 format. 1440 and 900 are future catalogue extensions only.

Baseline indoor distance/face: 18 m, 40 cm; full face and vertical/triangular triple layouts. Recurve/barebow use the normal ten; compound uses the smaller indoor ten. Baseline outdoor choices: recurve 70 m/122 cm, compound 50 m/80 cm six-ring, barebow 50 m/122 cm. Also offer explicitly selected junior/practice distances (30/40/60 m as applicable), without inferring age-class event eligibility from account age.

Numeric full-face scores allow 1–10/M; triple-face scores allow 6–10/M; compound six-ring allows 5–10/M. X counts as 10 outdoors; indoor X is disabled in these presets. Freeze score symbols/rules with the round.

Reference baseline: World Archery Book 2, version 27 January 2026, sections 4.5.1 and 7.2; Book 3, same version, section 12.2. Sources are pinned references, not a claim that this is the newest edition:
- [Book 2](https://extranet.worldarchery.sport/documents/index.php/Rules/Rule_Book_versions/2026-01-27/EN-Book_2_-_2026-01-27_Version.pdf)
- [Book 3](https://extranet.worldarchery.sport/documents/index.php/Rules/Rule_Book_versions/2026-01-27/EN-Book_3_-_2026-01-27_Version.pdf)

Check the effective edition before enabling an official-labelled preset. An event-specific rule change creates a new definition/version; it never rewrites existing rounds. Practice overrides are labelled and excluded from like-for-like official-format comparisons.

## Entry and saving

Choose athlete, bow/type, distance, face/format and optional arrow set before scoring. Allow several rounds and mixed practice formats in a training session; preserve each round's context. Equipment changes after scoring begins create a new segment with its own context, not retrospective relabelling.

Each shot stores end/position, raw score symbol, optional physical-arrow ID, optional plot coordinates/spot, entry method and version. Blank is unrecorded; M is an actual scored miss. Never infer shaft identity from sequence. No ID is required; selectors show only that athlete's active saved arrows. Do not prefill guessed physical IDs.

Save each confirmed entry idempotently. Show unsaved/offline state and allow retry; full offline synchronisation is future scope. Resume the same round at its next unrecorded entry. “Finish as partial” records actual count, maximum, dates and status; allow explicit reopening with history. Full completion requires all expected arrows. No conversion of unshot arrows into misses.

## Plotting and corrections

Keypad and plotting edit the same shots. Plot with zoom/drag, normalized coordinates relative to the selected spot and enough precision for correction; numeric-only shots have null coordinates, never invented centres.

The plot suggests a score using the selected face geometry. Let the athlete/parent confirm an observed line-cutter value. If shaft diameter is known, use it in line contact; otherwise treat the geometric suggestion as an estimate. A manual numeric override that conflicts with a plot retains the observed score, flags the mismatch and offers repositioning or clearing the location. Never manufacture coordinates to match a score. A miss may remain unlocated.

Triple-spot entry records spot identity and warns on repeated use in an end. Use a versioned rule evaluator for applicable penalties; retain raw impact values separately from effective scores and identify any override reason. This app records training; it does not claim tournament certification.

Only eligible athlete/parent users correct actuals. Keep old/new values, method/coordinates, actor/time and optional reason. Recalculate totals, X/10 counts and averages transactionally. Any completed AI review remains a historical snapshot; corrected actuals feed the next review.

## Equipment fields

| Entity | Required | Optional |
|---|---|---|
| Bow | Owner, display name, recurve/compound/barebow | Brand/model, handedness, draw weight with units, draw length with units, setup notes |
| Arrow set | Owner, set name | Brand/model, spine, length/unit, point weight/unit, shaft diameter, notes |
| Physical arrow | Set, identifier unique within that set | Notes, status |
| Sight mark | Bow, distance/unit, mark as text | Arrow set, sight extension/windage, date, notes |

Allow alphanumeric physical identifiers and distinguish sets. Equipment values describe actual equipment, not tuning recommendations. Create equipment revisions when specifications change; references on saved scoring retain their recorded revision. Archive rather than delete referenced equipment. Restoring an archived item is explicit; new shots cannot select an archived arrow.

## Reports

For each physical arrow, average = sum of effective score values / count of identified scored shots; include M as zero, exclude unrecorded shots. Show count and empty state. Bound day/range by athlete local scoring date; doubles and resumed rounds retain per-shot scoring dates.

Default grouping: physical arrow, bow/setup revision, distance and scoring-face version. Optional combined conditions view must say “mixed conditions.” Filter by date, bow, set, distance and format. Show archived arrows when they have relevant history. Corrections update reports; closure/anonymisation breaks identifying links under D12.

## Verification examples

- 36 recorded outdoor arrows produce a valid partial result; remaining blanks do not lower its average.
- A numeric shot followed by plotting modifies that shot only when selected; it never creates a duplicate implicitly.
- Arrow #7 in set A is distinct from #7 in set B.
- Identified 10, 8 and M give average 6.00 from 3 shots.
- Correcting 8 to 9 updates the result to 6.33 and keeps the old value in history.
- A face-version change leaves existing/resumed rounds and their plotted interpretation unchanged.
