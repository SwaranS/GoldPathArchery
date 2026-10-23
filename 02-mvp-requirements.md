# GoldPathArchery — MVP Requirements

Status: Requirements baseline · 22 October 2026  
Sources: [Brief](00-master-service.md), [decisions](01-product-decisions.md), [scoring](09-scoring-and-equipment.md)

## Capability and acceptance criteria

| ID | Capability | Required behaviour and acceptance |
|---|---|---|
| R01 | Public entry | Mobile homepage explains service; pilot access/sign-in routes work; no public athlete directory. |
| R02 | Accounts | Email confirmation, sign-in/out, recovery and reauthentication for closure/export; expired credentials fail safely. Privileged manager/admin roles are assigned by administrators, never self-selected. |
| R03 | Profiles/onboarding | Store stable athlete profile, declared birth date/timezone, goals, experience, current training volume, availability and range/equipment access. Reject missing essential planning inputs. |
| R04 | Coaches/discovery | Multiple active links, default view-only plans, per-coach editing grants and immediate revocation. Search is signed-in-only; hidden and under-16 profiles never appear. Private seven-day invitations require matching verified recipient acceptance. Hidden users/parents initiate their connections. |
| R05 | Managed AI plans | Assigned human manager requests/reviews AI draft, resolves validation and publishes; normal athlete coaches need not approve. Default 12 weeks, configurable 1 day–1 year. Failures retain last usable plan. |
| R06 | Plan lifecycle | One active plan; future activation scheduled; replacement warning/confirmation; independent inactive shared copies with recipient start date. Preserve prior plan/log/score histories. |
| R07 | Weekly recommendations | User-selectable review day/timezone; manager review before release; individual accept/edit/reject; full suggestion/review/decision/application history. Conflicting versions warn and cannot silently overwrite. |
| R08 | Sessions | Multiple daily shooting/non-shooting sessions; Rest Day with no required log. Move individual unstarted sessions within plan; warn before rest-day/conflict overrides. Started work retains actual date. |
| R09 | Logging | Completed/partial/skipped; actual arrows separate from plan; optional effort 1–10/notes. Missing log remains unknown. Non-shooting work requires no arrows. Support unplanned activity. |
| R10 | Round scoring | Required individual scores through keypad and target plotting; saved-arrow IDs optional. All launch formats in 09; multiple/double rounds preserve components and totals; save/resume and finish-as-partial work. Blank differs from M. |
| R11 | Corrections | Only athlete 16+ or editing parent may enter/correct actuals, including after completion. Old/new score, coordinates, actor and time retained; totals/analysis update; coaches/managers/AI denied. |
| R12 | Equipment | Multiple bows, named arrow sets, per-arrow identity, optional sight marks. Selection uses owned active equipment; archiving preserves historical equipment revisions and analysis. |
| R13 | Progress | Planned/actual volume and session status; per-physical-arrow average/count by day/range. Group compatible conditions; no-ID shots excluded only from physical-arrow averages. Corrections reflected. |
| R14 | Junior transitions | Under-14 parent-managed; 14–15 view-only junior login; 16 editing/export/closure passes to athlete. Existing parent editing becomes viewing until athlete chooses; revoked access stays revoked. Pilot birth-date/declaration flow has no manual verification. |
| R15 | Contribution history | Relationship end removes live/historical athlete access immediately; coach sees only own contribution snapshots, athlete retains received contributions. Exclude later athlete activity and other private notes; closure applies. |
| R16 | Operations/admin | Administrator assigns managers/cover with expiry and audit. Assigned manager sees agreed training fields only; no score editing. Routine administrator has no private-data browsing/debug view. |
| R17 | Export/closure | CSV detail/PDF summary, private expiring downloads, role/reauthentication checks. Immediate closure revocation; anonymisation within 30 days, delete where insufficient; linked child profiles handled explicitly. |
| R18 | Retention/recovery | Daily backups expire by 30 days; restored data remains isolated until closure suppression applied. Operational logs 30 days, minimal security metadata 90 days; no personal-data immortality through history. |
| R19 | Accessibility/reliability | Mobile and keyboard workflows, labels/contrast, visible errors and unsaved state, idempotent submissions. Plotting has equivalent numeric controls. Server checks every protected resource. |

## Critical cross-feature scenarios

1. Parent creates under-14 profile, enters training, invites coach and grants plan editing; coach cannot edit scores.
2. At 14, accepted junior login can view but cannot mutate actuals or relationships through UI or direct requests.
3. At 16, parent becomes viewing-only; athlete may grant editing but parent still cannot export/close.
4. Manager without assignment cannot load athlete data; temporary cover expiry revokes access on the next request.
5. Reviewed weekly change accepted against a newer plan version produces a conflict and no mutation.
6. Shared copy activates in recipient context without sender logs/identity or access grants.
7. Partial outdoor 36-arrow round saves/resumes; archive a referenced arrow and preserve old shots.
8. Closing an athlete anonymises contributions/exports/audits as well as profile records; restore cannot resurrect the account.

## Planning safeguards and AI evaluation

Use structured output matching a schema, deterministic constraint checks, reviewed instruction sources and synthetic cases across all bow types/ages. Scoring rules are computed by the application, not an LLM. Treat free text as data, not permission to change system rules. Record provider/model and generation version. Evaluate real plan usefulness with managers before pilot publication; never publish failed generation/validation.

## Scope and completion

All listed capabilities are launch scope. Detailed exercise tracking, teams, event registration, payments, native apps, automatic video analysis and private support-data views are deferred.

A feature is complete when its criteria and relevant access/conflict/correction cases pass in staging and documentation matches behaviour. These are software checks, not pilot business success criteria. The four-week pilot has no formal targets or pass/fail measure.
