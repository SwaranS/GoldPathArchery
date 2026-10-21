# GoldPathArchery — MVP Requirements

Status: Draft for review  
Sources: [Brief](00-master-plan.md), [decisions](01-product-decisions.md)

The capability areas below come from the brief. Detailed behaviour is proposed until reviewed. Open decisions must not silently become implementation assumptions.

## Requirements and acceptance criteria

| ID | Capability | User story | Acceptance criteria |
|---|---|---|---|
| R01 | Public homepage | As a visitor, I can understand the service. | Explains audience and benefits; provides a clear pilot access or sign-in route; works on mobile. |
| R02 | Accounts | As a user, I can securely access my account. | Supports the agreed registration/invitation flow, sign-in, sign-out and account recovery; invalid or expired credentials fail safely; protected pages require authentication. |
| R03 | Archer profile | As an archer, I can maintain information needed for training. | Approved fields and goals can be saved and edited; invalid values are explained; other users cannot access the profile without permission. |
| R04 | Coaching relationship | As an archer or authorised parent, I can control coach access. | Access requires the agreed authorisation flow; coach sees only linked athletes; ending the relationship prevents subsequent unauthorised access. Historical access follows D05. |
| R05 | Weekly plans | As a coach, I can prepare and assign sessions. | Session includes date, purpose, instructions and agreed training targets; draft content is distinguishable from assigned content; athlete sees only assigned sessions. Self-created plans depend on D02. |
| R06 | Session details | As an archer, I can understand today's practice. | Shows instructions, targets and current status; provides a route to logging; empty/rest days are clearly explained. |
| R07 | Session logging | As an archer, I can record my practice. | Records agreed date, actual arrows, optional score and feedback; invalid values are rejected; repeat submission does not create duplicates; authorised edits remain associated with the correct session. |
| R08 | Coach review | As a coach, I can review an athlete's progress. | Linked athletes' assigned plans and logs are visible; unlinked athletes are inaccessible through both UI and direct requests; missing logs are distinguishable from completed sessions. |
| R09 | Progress summary | As an archer, I can see training activity over time. | Shows actual arrow totals and session completion for a selected period; planned and actual values are distinguished; scores are compared only within compatible formats; empty data is handled clearly. |
| R10 | Administration | As an administrator, I can operate the pilot. | Approved account/support actions are available only to authorised administrators; sensitive actions are audited; routine administration does not imply unrestricted training-data access. |
| R11 | Junior / parent support | As an authorised parent, I can support a junior. | Implement only after D06 and the permission model are approved; verify relationships; restrict access to linked juniors; test removal and transfer of access. Required if juniors enter the pilot. |

## Quality requirements

- Enforce object-level permissions on the server for every profile, plan and log.
- Make core journeys usable on mobile with keyboard access, labelled fields and readable contrast.
- Preserve entered form data when validation fails and show clear success/error feedback.
- Separate staging and production credentials and data.
- Record operational errors without exposing credentials or unnecessary personal data.
- Define measurable performance and availability targets before pilot release.
- Test critical journeys and permission boundaries before each release.

## Scoring decisions

Confirm D11 before finalising log fields. Define maximum score, arrow count, distance, units and target-face rules for each supported format. Decide how partial rounds, multiple rounds on one date and unplanned sessions behave.

## Outside MVP

Payments, competition registration, equipment sales, video analysis, social feeds, native mobile apps and automatic AI coaching.

## Definition of done

Acceptance criteria pass; relevant permission and validation checks pass; screens have been reviewed on mobile; migrations and operational documentation are updated where applicable; feature is available in staging for review.
