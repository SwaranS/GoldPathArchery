# GoldPathArchery — Roles and Permissions

Status: Implementation baseline · 22 October 2026  
Authority: [01](01-product-decisions.md) · Requirements: [02](02-mvp-requirements.md)

## Model

Deny by default. Authorise the actor, target athlete, operation and current relationship on every server request, including searches, exports, background work and reports. IDs, hidden UI and role labels are not access controls. Multiple roles do not grant access to unrelated athletes.

Eligibility is calculated from the profile's declared birth date in its timezone. Below 14 no login; 14–15 is read-only; 16+ can manage own training. Parent access uses explicit links/grants. Coach and Plan Manager permissions are separate.

## Access matrix

“Parent” below means managing parent for under-16s or the athlete's continued grant after 16. “Linked coach” requires active accepted relationship. “Assigned manager” includes active temporary cover.

| Action | Athlete 16+ | Junior 14–15 | Parent | Linked coach | Assigned Plan Manager | Administrator |
|---|---|---|---|---|---|---|
| View own/linked training profile, plan, actuals and reports | Own | Own read-only | Within grant | Linked training fields | Assigned training fields | No routine private browsing |
| Edit profile/goals/availability/equipment | Own | No | Editing grant | No | No | Account-status support only |
| Draft/review/publish generated initial plan | No manager authority | No | No manager authority | No manager authority | Assigned athlete | Only if separately assigned manager role |
| Edit future sessions/move/accept released AI changes | Own | No | Editing grant | Explicit per-athlete plan-edit grant | Release reviewed proposals; cannot accept for athlete | No |
| Activate/share/replace personal plan | Own | No | Editing grant | May propose/edit; cannot activate/share for athlete | Cannot activate/share for athlete | No |
| Enter/correct actual logs and scores | Own | No | Editing grant | No | No | No |
| Manage coach/parent grants | Own | No | Managing parent below 16; after 16 athlete controls grants | End own coach relationship only | No | No routine override |
| Export / close athlete profile | Own | No | Managing parent below 16 only | No | No | Execute authorised closure job, not self-authorise |
| Assign/reassign manager or cover | No | No | No | No | No self-assignment | Yes |
| Own coach contribution history after relationship end | Own received record | Own received record | Within grant | Own authored record only | No new access from former assignment | No routine content browsing |
| Private coach notes | No by default | No | No by default | Author only | No | No |
| Admin role/account-status operations | No | No | No | No | No | Yes, audited |

Technical administrators may operate infrastructure but that does not create an application permission to browse private records. Private-data debugging views are future scope.

## Field scope

Coach read access: display name, discipline, goals, availability, relevant equipment context, plans, session actuals, scores and shared feedback. Exclude exact birth date, account email/security data and other coaches' private notes.

Manager read access: same planning fields for assigned athletes plus age band relevant to planning. No exact birth date/account-security information or private coach notes. Administrators see account identity/status needed for invitations/assignments and age-transition support metadata, not training note content. Error logs must avoid those contents.

## Relationship and assignment lifecycle

- Invitation: recipient-bound, one-use, private, seven-day expiry; acceptance by matching verified account; revocation immediate.
- Hidden athletes/coaches initiate invitations themselves; parents initiate for under-16 athletes. Forwarding an invitation cannot transfer authority.
- Accepted coaches begin plan-view-only. Eligible athlete/parent may grant editing without granting scoring.
- End relationship: immediately deny all athlete-data requests, including history and pending exports; retain only the coach's own contribution snapshot.
- Administrators create dated manager assignments; temporary cover requires an explicit end timestamp (default seven days, maximum 30 days per grant). Extensions are explicit/audited. Normal reassignment ends the former assignment; temporary cover can coexist.
- Closing an athlete terminates relationships/assignments and disables queued tasks. Closing a manager/coach account revokes that account's access without deleting athlete training history.

## Age transition

Registration uses declared birth date and parent declaration in the pilot; email confirmation proves mailbox control only. No manual identity/guardian verification. Junior invitations link to the stable athlete profile.

At 16 local midnight: enable athlete editing/export/closure, change existing parent editing to view-only, preserve revoked links and notify linked parties. Without a junior login, allow self-service private claim; parent editing still ends. On next login ask the athlete to review each parent's view/edit/none grant. Parent editing after 16 excludes exports/closure and grant administration.

## Change and audit controls

Reauthenticate before export/closure or sensitive account changes. Keep attributed version history for plans, score corrections, recommendations, assignments and grants. No silent conflicting writes. History has the same object permissions as its current record; an old URL cannot bypass revocation.

Audit metadata records operation, actor reference, target reference, time and outcome with minimal payload. D12 closure/anonymisation applies to content and references; security metadata retention is not a reason to keep identifiable training payloads.

## Required checks

For every relevant operation, test own/linked/unrelated actors, view versus edit grants, hidden/under-16 search exclusion, direct identifiers, expired/replayed invitations, revoked links, expired cover, 14/16 boundaries and closure. A failed permission or version check must leave data unchanged.
