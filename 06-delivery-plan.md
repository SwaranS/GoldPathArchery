# GoldPathArchery — Delivery Plan

Status: Requirements baseline; implementation not started  
Updated: 22 October 2026 · [Requirements](02-mvp-requirements.md)

## Milestones

| Stage | Deliverable | Engineering evidence |
|---|---|---|
| M0 Requirements | Reconciled documents 00–09 | Links, scope, permissions and delegated defaults consistent |
| M1 Foundation | App/database, accounts, migrations, CI, synthetic staging | Repeatable startup and deploy; account and object-access checks |
| M2 Relationships/equipment | Parent transitions, coach grants, manager assignments, saved bows/arrows | Role/age/revocation/cover expiry cases verified |
| M3 Plan journey | Managed initial generation, publishing, activation, session display and basic logs | Manager → athlete/parent → log journey works with persisted history |
| M4 Scoring | Keypad/plotting, partial/double rounds, corrections, saved IDs, analysis | Preset fixtures and arrow-level arithmetic/history checks |
| M5 Adaptation/sharing | Weekly review, decisions, moves, independent copies and future activation | No duplicate job, silent overwrite or more than one active plan |
| M6 Data/operations | Exports, closure, backup restore, monitoring and privacy information | Restore suppression and anonymisation inventory demonstrated |
| M7 Pilot | Four-week free pilot with agreed roles | Gather feedback and prioritise improvements; no success targets/pass-fail assessment |
| M8 Production | Reviewed release, custom domain and operational ownership | Release checklist and smoke checks; no claim of completion until performed |

Engineering evidence verifies software behaviour; it is not a business success measure for the pilot.

## First complete implementation slice

An administrator assigns a manager to a parent-managed athlete. Manager uses a fixture-backed generator initially, reviews/publishes a short plan. Parent activates it, views instructions and records a session. A linked coach can read it but cannot edit scores. An unrelated user is denied.

Replace fixtures with the evaluated provider adapter after cost/data/quality validation. Fixtures are a development aid, not a substitute for live AI at pilot release. Include assigned-manager restrictions and under-16 permissions from the beginning.

## Issue-ready backlog

This table is the development backlog; separate GitHub issues have not been created.

| Task | Scope | Depends on | Requirements |
|---|---|---|---|
| T01 | Repository scaffolding, module layout, supported dependency selection | Baseline | R19 |
| T02 | Database migrations, container, CI and synthetic staging | T01 | R18–R19 |
| T03 | Accounts/email/reauthentication and stable athlete profiles | T02 | R02–R03 |
| T04 | Parent links, junior claim and 14/16 transitions | T03 | R14,R17 |
| T05 | Coaches, discovery, hidden initiation, private invitations/grants | T03,T04 | R04,R15 |
| T06 | Administrator-managed assignments and expiring cover | T03 | R16 |
| T07 | Saved bows/arrows/revisions/sight marks/archive | T03,T04 | R12 |
| T08 | Planning input, schema/constraints, fixture generator and manager review | T03,T06 | R05 |
| T09 | Versioned plans, one-active-plan lifecycle and session logging | T04,T08 | R06,R08–R09 |
| T10 | Versioned scoring presets and arithmetic fixtures | T02 | R10–R11 |
| T11 | Keypad/plotting, save/resume/partial/double rounds and corrections | T07,T09,T10 | R10–R11 |
| T12 | Per-arrow means/counts and grouped progress reports | T11 | R13 |
| T13 | AI provider evaluation and itemised Azure cost validation | T08 | R05,R07 |
| T14 | Live provider adapter, scheduled weekly reviews and decision history | T09,T13 | R07 |
| T15 | Session moves, conflicts, plan sharing and scheduled activation | T05,T09,T14 | R06–R08 |
| T16 | Coach contribution snapshots and immediate access termination | T05,T09,T15 | R15 |
| T17 | CSV/PDF export, closure inventory and anonymisation jobs | T04,T11,T14,T16 | R17 |
| T18 | Backup expiry/restore suppression and operational runbooks | T02,T17 | R18 |
| T19 | Mobile/accessibility and end-to-end permission/retry checks | T11–T18 | R01–R19 |
| T20 | Pilot setup, feedback collection and issue triage | T19 | D07/D14 |
| T21 | Production config/domain, release and smoke checks | T20, costed hosting | 07 checklist |

Each issue should carry outcome, scope, linked R IDs, acceptance examples and dependencies. Do not write tests that merely mirror implementation; focus on permissions, arithmetic, state transitions, concurrency and recovery.

## Launch follow-ups

Before pilot: identify actual athletes/coaches/parents, accountable operator and support channel; record suitable live-provider terms and cost estimate. Budget EUR 45 testing total is unchanged.

Set calendar dates and effort estimates after initial scaffolding/provider feasibility. Exact production domain, spend and deployment are not authorised merely by requirements consolidation. Keep work on feature branches; do not merge feature/requirements to main as part of this update.
