# GoldPathArchery — Delivery Plan

Status: Proposed sequence; estimates and dates pending  
Scope: Fresh implementation based on the committed product brief

## Milestones

| Milestone | Work | Exit criteria |
|---|---|---|
| M0 — Requirements | Resolve product decisions; review requirements, access matrix and flows | Pilot scope and blocking decisions agreed |
| M1 — Foundation | Select architecture; initialise app; configure database migrations, CI and staging | Application deploys to staging; health check and baseline checks pass |
| M2 — Identity and relationships | Accounts, profiles and agreed coach/guardian access lifecycle | Own/linked/unrelated access and revocation checks pass |
| M3 — Complete training journey | Create and assign session; view instructions; record log; coach review | End-to-end journey works in staging with representative test accounts |
| M4 — Pilot scope completion | Progress summaries, administration, mobile refinement and error states | All agreed MVP acceptance criteria pass |
| M5 — Private pilot | Invite agreed participants; collect feedback; resolve blocking defects | Agreed pilot success measures evaluated and release risks resolved |
| M6 — Production release | Domain, operational checks and release review | Release checklist complete; deployed version verified |

## First implementation slice

A coach assigns one session to one linked archer. The archer views the instructions and logs completion. The coach reviews that log. Another user cannot access any part of the athlete's private data.

Implement this after the account model is settled. If juniors join the pilot, the agreed guardian requirements belong in this slice.

## Proposed initial issue backlog

These are issue outlines, not GitHub issues already created.

| ID | Proposed issue | Dependencies |
|---|---|---|
| T01 | Confirm customer, plan ownership and pilot participants | None |
| T02 | Agree junior/guardian and coach permissions | T01 |
| T03 | Define scoring, session fields and plan-change behaviour | T01 |
| T04 | Review mobile screen sketches with pilot users | T02, T03 |
| T05 | Record stack, hosting, identity and data decisions | T02, T03, budget |
| T06 | Set up application, CI, migrations and staging | T05 |
| T07 | Implement accounts, profiles and relationships | T02, T06 |
| T08 | Implement plan assignment and session viewing | T03, T04, T07 |
| T09 | Implement logging and coach review | T08 |
| T10 | Verify complete journey and permission boundaries | T09 |
| T11 | Complete progress, administration and pilot review | T10 |
| T12 | Complete release readiness and deploy | T11 |

## Issue format

Include the user outcome, linked requirement IDs, agreed scope, acceptance criteria, dependencies and relevant verification. Keep tasks small enough to review independently.

## Working agreement proposal

Use feature branches and reviewed pull requests into main. Keep decisions and acceptance criteria current as scope changes. Separate proposals from accepted requirements. Schedule the pilot after scope and estimates are available.
