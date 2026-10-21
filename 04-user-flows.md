# GoldPathArchery — User Flows and Screen Outline

Status: Draft for review; text wireframes, not final visual designs  
Dependencies: [requirements](02-mvp-requirements.md), [permissions](03-roles-and-permissions.md)

## Proposed navigation

Public: Home → Pilot access / Sign in.  
Archer: This week, History, Progress, Profile.  
Coach: Athletes, Athlete plan, Athlete history / progress.  
Parent: Linked junior selector and approved views; dependent on D06.  
Administrator: Separate restricted administration area.

## Flow A — Onboarding

Visitor reads homepage → follows the agreed invitation/registration route → verifies account as required → completes approved profile fields → sees the next useful action.

Review: how roles are assigned; whether standalone archers can join; how junior onboarding and guardian verification work. Empty state must explain how to obtain or create a plan.

## Flow B — Assign a session

Coach signs in → selects linked athlete → opens week → creates draft session → reviews date, instructions and targets → assigns session → receives confirmation.

Proposed fields: date, title, purpose, instructions, planned arrows, distance/format where applicable. Decide rest days, multiple sessions per day, plan copying and revisions before expanding this form.

Changes after assignment must have defined behaviour. Completed logs must retain enough context to understand what the athlete performed.

## Flow C — View and log practice

Archer signs in → sees today's session within the week → opens instructions → selects Log session → enters actual arrows, optional score and feedback → saves → sees completion and can return to the week.

Logging screen:
- Session title, date and instructions remain accessible.
- Inputs show expected units and validation.
- Save action has a visible pending and success state.
- A failed save preserves entered values.
- Repeated submission does not duplicate the log.

Decide partial completion, skipped sessions and unplanned sessions before implementation.

## Flow D — Review progress

Coach selects linked athlete → chooses period → sees planned versus completed sessions and actual arrow totals → opens an individual log.

Archer sees the equivalent view for their own data. Scores require matching format context. Empty states must distinguish no plan, no recorded activity and no access.

## Flow E — End coaching access

Eligible user opens relationship settings → reviews consequence → ends relationship → sees confirmation. Coach loses subsequent access according to the agreed policy. Training-data ownership and historical access follow D05/D12.

## Screen review checklist

- Is the primary action clear on a phone?
- Can a user reach today's instructions and logging quickly?
- Are validation, empty, loading and permission states defined?
- Can keyboard users complete each core journey?
- Are parent and coach permissions clear to the account holder?
- Can pilot users complete the journey without verbal guidance?

## Design work remaining

Produce low-fidelity layouts for homepage, weekly plan, session detail/log form and coach athlete review. Review with representative pilot users before detailed styling.
