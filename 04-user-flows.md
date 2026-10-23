# GoldPathArchery — User Flows and Screen Outline

Status: Implementation baseline · 22 October 2026  
[Decisions](01-product-decisions.md) · [Permissions](03-roles-and-permissions.md)

## Navigation

Public: Home, pilot access, sign in.  
Athlete/parent: Today/Week, Plans, Score, History/Progress, Equipment, Profile/Connections. Parent has an explicit athlete selector.  
Coach: Linked athletes, plan review/edit, proposals, own contribution history.  
Plan Manager: Assigned athletes, draft/review queue, weekly review queue.  
Administrator: Account status/roles, assignments/cover and operational job status.

Use the selected athlete's name prominently on edits and scoring. Role switching cannot silently change the target athlete.

## A — Registration and juniors

Open private pilot invitation → create account → confirm email → choose athlete/parent/coach use → enter required profile data.

Parent flow: declare relationship → enter child birth date/profile → complete goals/availability → request plan. Under-14 has no child login; ages 14–15 can receive an optional junior login invitation, with read-only screens after email confirmation.

At 16: notification and existing-profile claim if needed → parent editing becomes viewing → athlete sees parent permission chooser. Previous history stays on the same profile. No manual administrator verification.

## B — Initial plan

Athlete/parent supplies goals, experience, current volume, schedule, equipment/range access, optional event date and duration → system validates input → assigned Plan Manager generates AI draft → reviews assumptions/constraints → adjusts if necessary → publishes inactive plan → athlete/parent chooses start date and activates.

If another plan is active, show replacement warning and date; confirm immediate or scheduled switch. Failure leaves previous plan active. Manager sees generation status and retry option; users see preparation status without raw provider errors.

## C — Weekly adaptation

On selected review day, system prepares proposals → Plan Manager reviews/edits/releases → eligible athlete/parent/editing coach sees individual changes and reasons → accept, edit or reject each.

Show original/proposed session and human-edit indicators. Record all decisions, including rejection. If the plan changed since preparation, show conflict and require re-review; no silent overwrite. Pending proposals for replaced plans become superseded. Prior plan and recommendation histories remain accessible under current permissions.

## D — Practice and rescheduling

Today/Week shows instructions, targets and Rest Day entries. Choose one unstarted session → select destination date within plan → preview conflicts → warning/confirmation if needed → move only that session.

Rest-day destination displays the activity afterwards. Other sessions stay put. Started/completed sessions retain dates; remaining work can become a new session.

Log completed/partial/skipped → actual shooting arrows and optional effort/notes → save. Non-shooting sessions use basic instructions/status/feedback without arrow requirement. No action required for Rest Day. Unlogged is unknown.

## E — Scoring

Select athlete → session/new practice → bow/type, saved arrow set optional, distance/format/face → start round. Display actual context and running totals.

For each shot use keypad or tap/zoom target. Optional arrow selector uses saved arrows only; no identifier required. Changing method uses the same shot record. Show “saved,” “unsaved” or retry state. Triple layout shows chosen spot and collision warnings.

Save/leave → resume same round; or Finish as partial → confirm recorded count and maximum. Doubles show both component rounds and combined totals. Score correction shows old/new values; conflicting plot requires reposition/clear-location decision. Only athlete/parent can save actuals.

## F — Equipment and analysis

Profile → Equipment → add bow / named arrow set / identifiers → optional sight marks by distance/set. Archive with history-preservation explanation. Historical shots keep equipment version.

Progress → day/date range → compatible bow/distance/face groups → each physical arrow's average and count → drill into scored shots. Optional mixed-conditions report is labelled. No-ID shots remain in overall statistics but not individual-arrow means.

## G — Connections and contribution history

Eligible profile search lists minimal data for signed-in users. Stay out of Search hides the profile; under-16 profiles never appear.

Initiator sends private account-bound invitation → intended recipient verifies/signs in → accepts → default view-only coach link. Athlete/parent can grant editing. Hidden users initiate their own links.

End relationship → explanation → confirm → live/history access revoked. Coach's My contributions shows own read-only authored snapshots only; athlete still sees received contributions. Private notes never appear in shared feedback automatically.

## H — Share plan

Owner chooses recipient via private invitation → recipient accepts → independent inactive copy → start-date/availability preview → activation with replacement warning if needed. No source logs, identity, feedback or relationships are copied.

## I — Export and closure

Athlete/eligible parent → export → reauthenticate → CSV/detail or PDF summary → private 24-hour download. Download is optional.

Close profile → verify authority → show linked-profile implications → reauthenticate and confirm → immediate access revocation → anonymisation within 30 days. Parent-account closure requires transfer or explicit closure of under-16 child profiles. No orphaned child profiles and no restoration of closed accounts from backup.

## Screen design and verification

Produce mobile wireframes for Today/Week, logging/scoring, manager review, parent transition and per-arrow analytics before implementation. Include loading/empty/error/conflict/permission states. Numeric scoring is the accessible equivalent to plotting. Preserve valid form entries after errors; every write gives a clear outcome without duplicate submissions.
