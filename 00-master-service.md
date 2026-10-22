# GoldPathArchery — Product Brief

Status: Requirements baseline · 22 October 2026  
Details: [Product decisions](01-product-decisions.md)

## Purpose and audience

Help recurve, compound and barebow athletes know what to train today, record practice quickly and review progress with coaches. Coaches and athletes are the primary users; parents manage younger athletes. Clubs, states and teams are future scope.

## Core experience

A human System Plan Manager uses AI/software to create and review a personalised plan. Plans default to 12 weeks and can span 1 day to 1 calendar year. Plan Managers review initial plans and weekly AI recommendations. Eligible athletes, managing parents and authorised coaches can edit plans. Weekly changes are applied only after eligible-user acceptance, with decision history retained.

Each athlete has one active plan. Shared plans become independent inactive copies owned by the recipient, who chooses a start date. Sessions can move individually, including onto Rest Days after a warning. Basic strength, mobility and mental practice are included.

## First release

- Secure accounts, profiles, goals, availability and multiple coach relationships.
- Parent-managed profiles below 14; view-only junior logins at 14–15; athlete editing from 16.
- Individual arrow scores through keypad or target plotting; optional identifiers selected from saved arrows.
- Indoor 30/60/double-60-arrow formats; outdoor 720/double 720; saved partial training rounds and resumption.
- Multiple bows, named arrow sets, sight marks, equipment archiving and per-arrow averages by day/date range.
- Completion/partial/skipped feedback, actual arrows, optional effort 1–10 and notes.
- Assigned Plan Manager access, administrator controls, private invitations and profile search controls.
- CSV exports and PDF summaries; immediate access revocation on closure and anonymisation within 30 days.

## Access and privacy

Under-16 profiles never appear in search. Eligible accounts are discoverable to signed-in users unless “Stay out of Search” is enabled. At 16, existing parent access becomes view-only until the athlete chooses viewing, editing or no access. Scoring is controlled by the athlete/managing parent, never coaches or Plan Managers.

## Boundaries

Payments, competition registration, equipment sales, video analysis, social feeds, native apps, reusable template libraries, team management, autonomous coaching outside the agreed plan workflow, detailed exercise tracking and private-data debugging views are future scope.

## Pilot and operations

Free private pilot: 5–10 athletes, at least two coaches and one parent-managed junior, over four weeks. Gather feedback without formal success targets or a pass/fail assessment. Ordinary software acceptance checks still apply.

Azure in Europe; total testing budget EUR 45/month, including AI, database, email, storage, backups and monitoring. Architecture choices and cost validation are in 05. No prior code is assumed. Named participants, production budget, domain and release date are operational follow-ups, not unresolved feature requirements.
