# GoldPathArchery — Product Decisions

Status: Requirements baseline; remaining defaults selected under product-owner delegation  
Updated: 22 October 2026  
Branch: feature/requirements  
Brief: [00-master-service.md](00-master-service.md) · History: [08-decision-history.md](08-decision-history.md)

The product owner authorised ChatGPT to decide remaining details on 22 October 2026. Previously confirmed choices are preserved. Defaults below now guide implementation and may be revised through explicit changes; they are not claims of implemented behaviour or verified service availability.

## D01/D10 — Audience and value

Coaches and athletes are primary customers. Support recurve, compound and barebow at launch. Parents manage younger athletes. The return value is: know what to train today, record practice quickly and review progress. Clubs, states and teams remain future scope.

## D02 — Plans and AI workflow

- System Plan Managers are humans using AI/software; multiple managers are supported. AI leads drafting; a manager reviews every initial plan before publication and weekly recommendations before release.
- Default duration: 12 weeks; configurable from 1 day to 1 calendar year. Eligible athlete/parent and plan-editing coaches may request duration changes. Extend or trim future unstarted sessions after preview; never remove completed/started records. Extending the horizon requires manager-reviewed generation before new content is published.
- One active plan per athlete. New plans arrive inactive; the eligible athlete/managing parent selects a start date and confirms activation. Warn before replacement. Preserve previous plans, scores, logs and histories.
- A future activation remains scheduled/inactive until the selected local date; the current plan stays active until then. Only one pending replacement per athlete. Changing/cancelling it requires confirmation. Switch atomically; fail without deactivating the current plan if activation fails.
- AI updates adapt the existing plan using actual training, comparable scoring, feedback, availability and competition dates. Missing activity is unknown, never assumed skipped.
- Onboarding requires goals, bow discipline, experience, current weekly training/arrow volume, available days/time, range distances and equipment; competition dates are optional. Ask for missing essential data. No invented athlete history.
- Use reviewed planning guidance and configurable scheduling/volume constraints; do not invent universal progression percentages. Plan Managers resolve failed validation before publication. AI does not diagnose conditions or replace physio instructions.
- If generation fails, keep the existing usable plan and show a retry/status message.
- No mandatory approval by the athlete's own coach. Individual human edits remain allowed within the access model.

### Weekly recommendations

Athletes aged 16+ or managing parents choose their review day. Prepare reviews at 06:00 in the athlete profile's timezone (default Europe/Dublin, editable). Store an IANA timezone; display local dates and handle daylight-saving changes.

A changed review day/timezone affects the next not-yet-created review; it does not duplicate an existing weekly review. Permit one additional on-demand review per rolling seven days, routed through the same manager workflow.

Managers review recommendations before releasing them. Release time depends on manager availability, not a promise of instant delivery on the chosen day. Until accepted, the current plan stays active.

Eligible athlete/parent or a coach explicitly granted plan editing can accept, edit or reject each recommendation separately. Under-16 junior logins cannot act. Keep original suggestion, rationale, affected sessions, manager review, user decision/edits, actor, time and applied plan version. Rejected changes remain recorded.

Preserve human changes and completed history. If the underlying plan changed, warn, show the competing versions and require re-review of the current plan; no silent overwrite. Pending recommendations referring to replaced plans are superseded, not applied to the new plan.

### Session movement

Move individual unstarted sessions/exercises without exchanging days or changing other sessions. Preserve instructions/targets and change history. Moving onto a Rest Day requires a warning; the destination no longer appears rest-only.

Warn for range/competition/recovery conflicts; explicit confirmation can override schedule warnings, but cannot bypass permissions or invalid dates. Moves must stay inside the plan period. To move outside it, first extend the plan within the one-year limit. Started/completed sessions keep their actual dates; record remaining work as a new session instead of moving history. Multiple sessions per day and unplanned training logs are supported.

### Sharing

A shared copy belongs to the receiving archer and is independent. Copy instructions, structure and relative session dates, not the sender's identity, feedback, logs, scores or coach notes. Sender gains no recipient access.

Recipients accept a private share invitation; receipt creates an inactive copy. They choose a start date, preview availability/conflicts and activate under the one-active-plan rule. Sharing does not reuse the source athlete's planning context; later adaptation uses the recipient's data. Human-created or edited shared instructions are not silently rewritten by AI.

## D03 — Scope boundaries

No reusable template-library feature in MVP. System-created and shared personal plans still use versions and independent ownership. Future scope: payments, event registration, equipment sales, video analysis, social feeds, native apps, teams, detailed exercise tracking and private-data support/debugging views.

## D04/D05 — Coaches, discovery and invitations

Multiple coaches per athlete; physio/technical role labels do not grant permissions. Active linked coaches may view training goals, availability, plans, logs, scores and shared feedback. Editing is off by default.

Athletes aged 16+ or managing parents separately grant/revoke plan editing per coach. This permits future-session instructions/targets, movement and acceptance of AI changes. It does not allow editing actual logs/scores, account details, access grants, exports, closure or completed history. Coaches may add their own attributed proposals. Conflicts warn and require re-review.

“Stay out of Search” is off by default for eligible accounts. Listings are signed-in-only and show display name, role and bow discipline, not birth date, contact details or training data. Under-16 athlete profiles are always excluded.

Hidden users alone initiate new connections involving their profile; managing parents initiate for under-16s. If both people are hidden, they can exchange a private invitation outside discovery. Existing connections survive a search-setting change.

All invitation links are private, single-use, revocable and expire after seven days. Bind invitations to the intended verified account/email; no anonymous acceptance, public directory of links or access from merely opening/forwarding a link. Invalid/expired invitations disclose no hidden profile. Email account confirmation is automated; no manual administrator identity checks for the pilot.

Either connected party may end a relationship. Revoke athlete-data access immediately, including history. Coaches retain their own read-only contribution records; athletes retain those contributions too. Store dated authored instructions/revisions and their historical status, not whole athlete plans, later activity or other people's notes. Contributions follow closure/anonymisation rules; no permanent identifiable retention exemption.

Private coach notes, if used, are visible only to their author in MVP, not other coaches, Plan Managers or routine administrators. Plan feedback intended for athlete review must be explicitly shared.

## D06 — Juniors and parents

- Below 14: parent-managed athlete profile, no child login.
- Ages 14–15: optional view-only login for own plans, logs and progress; no edits, invitations, scoring, export or closure.
- From 16: athlete edits and controls relationships, export and closure. Existing parent editing becomes view-only until the athlete chooses viewing/editing/no access. Never restore previously revoked access.
- Parent editing granted after 16 includes logs and scores, but never automatic export/closure authority.
- Athlete controls and may revoke each parent's access. Only the athlete can export/request closure from 16; below 16 the managing parent can.
- Retain a stable athlete profile as logins change; do not copy or move training history between accounts.

Pilot registration uses entered date of birth and a parent/guardian declaration. These are self-declared, not independently verified. Confirm email ownership, not guardian identity. No manual administrator verification.

Parent initiates a junior login invitation at 14–15; the junior verifies a unique email and links to the existing profile. On the 16th birthday, age permissions change at local midnight based on stored birth date/timezone; notify the athlete and parent and show the parent-access chooser on next login. If the athlete has no login, make a self-service claim invitation available through the existing parent-managed account; parental editing still becomes view-only at 16. Link with a private single-use token, never date of birth alone. Birth-date corrections affecting age permissions require reauthentication, are audited, and cannot restore expired parent authority without the eligible athlete's grant.

## D07/D09/D14 — Pilot

Four weeks, 5–10 athletes, at least two coaches and one parent-managed junior. No formal pilot success criteria, numeric targets or pass/fail assessment. Gather feedback and fix problems. Engineering acceptance checks protect correct operation and are not pilot business success measures.

Participants and date will be arranged after staging and effort estimation; no invented commitments.

## D08/D13 — Hosting and budget

Azure in Europe. Testing ceiling EUR 45/month across application, database, AI, email, exports, backups and monitoring. Start as one application; avoid paid provisioning before a costed configuration is available. Use synthetic data for development. Provider/model, exact region/SKUs and production budget remain architecture/procurement tasks requiring current price and availability validation, not further product questionnaire items.

## D11 — Scoring and equipment

Recurve, compound and barebow; keypad and target-face plotting at launch. Individual arrow scores are required; identifiers are optional and picked only from the athlete's saved arrows. No free-text physical identifier during scoring.

Launch indoor formats: 30 arrows, 60 arrows and double 60 (120 arrows total). Outdoor: 720 and double 720. Save/resume any unfinished round. A 36-arrow training result is valid. Allow “Finish as partial” with actual count/maximum, never convert unscored arrows to misses. Multiple rounds may be logged per session; doubles retain separate round totals and combined totals. Future 1440/900 formats must be easy to add, but are not launch scope.

[09-scoring-and-equipment.md](09-scoring-and-equipment.md) defines versioned presets, bow-specific scoring, plotting, corrections and equipment fields. Defaults include 18 m/40 cm indoor and explicit distance/face selection outdoors; shortened-distance practice is labelled as practice, not an official standard round.

Only the athlete aged 16+ or managing parent with editing authority enters/corrects scores and actual logs. Coaches, Plan Managers and AI cannot change them. Corrections after completion retain original/new values, actor/time and recalculate totals/analysis. Plot corrections keep positions consistent or explicitly unlocated.

Save multiple bows, named arrow sets and physical arrows; select equipment per session/round. Optional sight marks by bow, distance and arrow set. Archive equipment to remove new selection while preserving historical versions.

Per-physical-arrow averages and sample counts for a chosen local day/date range are launch scope. Only explicitly identified scores contribute. Separate equal labels in different sets; retain archived-arrow analysis. Default comparisons group by bow/setup, distance, target/scoring definition; an explicitly requested combined view is labelled mixed conditions.

## D12 — Export, closure and retention

Export training plans, logs and scores as CSV plus a readable PDF summary before closure. CSV includes individual scores and saved identifiers; download is optional. Authentication and role checks apply; exports use a short-lived download and expire after 24 hours.

Closure uses reauthentication and explicit confirmation. End account access, invitations, assignments and active relationships immediately; anonymise within 30 days. If adequate anonymisation fails, remove identifying content or delete affected records. Include contributions, free text, audit payloads, identifiers, queued jobs and export files. Keep only demonstrably anonymous aggregate statistics: monthly usage/arrow totals, without individual histories or small groups (suppress groups below 10). Do not claim that renaming a user anonymises records.

Under-16 profile closure by the managing parent is separate from parent-account closure. Before closing a parent account, transfer management of each under-16 profile through a private accepted invitation or explicitly close those profiles too; never leave an orphan profile or silently delete children. From 16, closure/export belongs to the athlete.

Inactive accounts remain available until explicit closure for this release; revisit this provisional policy in future.

Operational defaults: encrypted daily backups, maximum retention 30 days, no indefinite snapshots. This is a rolling backup lifetime, not an extra 30 days after the anonymisation deadline. Remove affected export files promptly; restrict backup access. Maintain a minimal restricted closure-suppression record while affected backups exist. Any restore occurs in isolation and reapplies closures/anonymisation before user access; expire suppression records once no affected backup remains. Record completion without unnecessary identity data.

Contribution/correction/recommendation histories persist while the account is active; account closure rules apply to them. Operational logs expire after 30 days, security/access-administration metadata after 90 days with minimal payloads. No extra identifiable retention is assumed without a documented purpose and expiry. These operational policies must be reviewed against actual processing and validated in implementation; they are not a declaration of legal compliance.

## D15 — Feedback and non-shooting work

Completed/partially completed/skipped; actual arrows separate from planned; optional effort 1–10 (1 very easy, 5 moderate, 10 maximum perceived effort) and optional notes. Link scores instead of duplicating totals. Unlogged remains unknown.

Basic strength, mobility and mental-practice sessions use title/type, instructions, status, optional effort/notes; no required arrows. Detailed sets/reps/weights and medical records are future scope. Rest Days are displayed with no required logging and excluded from session-completion denominators.

## Baseline completion and follow-ups

Product choices and delegated defaults are now consolidated. Continue with the linked requirements, permissions, flows and implementation backlog. No further product interview is required to start detailed design.

Before deployment: cost/region/model validation, actual processing/privacy review, rulebook-version verification, named operator/domain/participants and release date. These are tracked in 05–07. No software has been implemented or deployed by this document update.
