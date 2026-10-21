# GoldPathArchery — Product Decisions

Status: In review — confirmed decisions and outstanding choices recorded below  
Source: [Product brief](00-master-plan.md)  
Updated: 21 October 2026  
Working branch: feature/requirements

## How to use this document

This is the current product decision record. **Confirmed** means the product owner has supplied the direction. **Partial** means the direction is agreed but behaviour remains unresolved. **Proposed** means a recommendation awaiting review. **Deferred** means a decision will intentionally be made later.

Details recorded as proposed are not approved requirements. Finish this document before updating the remaining requirements and architecture documents.

## Established direction

Build a fresh archery training service for coaches and athletes, initially focused on recurve. Support juniors in the private pilot. The first release covers accounts, athlete profiles, AI-led personalised training plans with human editing and sharing, multiple coaching relationships, weekly plans, session logging, basic progress summaries and administration.

Club, state and team memberships are future scope. Payments, competition registration, equipment sales, video analysis, social feeds and native apps remain outside the first release. AI-led plan generation is now included in the first-release direction, superseding the original exclusion of automatic AI coaching for this specific capability; other autonomous coaching features are not assumed. A reusable template library is not required in version one.

## Decisions

| ID | Topic | Current decision | Status |
|---|---|---|---|
| D01 | Primary customers | Coaches and athletes. Future releases may add club, state and team memberships with access to defined sets of data. | Confirmed |
| D02 | Plan creation and adaptation | AI takes the lead in creating personalised training plans. Eligible athletes, parents managing junior profiles and authorised coaches can edit the athlete's plan. Human authorship or mandatory coach approval is not the default workflow. AI recommends weekly changes based on completed training and available feedback; an eligible user accepts changes before they update the active plan. Sharing creates an independent copy owned by the receiving archer, subject to their age and access permissions. | Partial |
| D03 | Reusable templates | A reusable template library is outside version one. Shared AI-generated plans become independent copies owned by their receiving archers. | Confirmed |
| D04 | Multiple coaches | An athlete can have multiple coaches, including a physio and an archery technical coach. Exact permissions per relationship remain to be defined. | Partial |
| D05 | Coach relationships and discovery | Coaches and athletes can invite, accept or reject one another. Both may choose whether to be listed. Listing audience, junior restrictions and access after a relationship ends remain to be defined. | Partial |
| D06 | Junior access | Below 14, a parent creates an account and manages a linked child athlete profile. At ages 14–15, the junior may have a login with view-only access to their own training information; the parent continues to manage edits. From age 16, the athlete can edit their own training data through the agreed account transition. | Partial — age thresholds confirmed; verification and parent-access transition pending |
| D07 | Pilot participants | Juniors are included. Participant numbers, coaches and recruitment arrangements remain to be confirmed. | Partial |
| D08 | Testing budget | EUR 45 per month on Azure. Cost planning must include the application, database, email, backups and monitoring. The production budget is separate and not yet agreed. | Confirmed for testing |
| D09 | Pilot date | Set after the MVP scope is agreed and estimated. No committed launch date yet. | Deferred |
| D10 | Main return value | Know what to train today, record practice quickly and review progress with coaches. Parents record practice for juniors with view-only access. | Proposed |
| D11 | Scoring | Both indoor and outdoor scoring are essential. Exact round formats and logging detail remain to be agreed. | Partial |
| D12 | Leaving, account deletion and retention | On confirmed account closure/deletion, remove access and delete or genuinely anonymise user-related data. Attempt anonymisation only where identity cannot reasonably be recovered; delete data that cannot be sufficiently anonymised unless a documented retention obligation applies. Permanent retention of identifiable or merely renamed records is not the policy. Operational timescales, export and backup expiry remain to be agreed. | Partial |
| D13 | Hosting | Azure, in Europe. Specific region and services will be selected after requirements and budget review. | Confirmed direction |
| D14 | Pilot success | Assess core-journey completion without assistance, repeat weekly use, logging activity and participant feedback. Targets below are proposed. | Proposed |
| D15 | Session feedback | Start with completion status, actual arrows, optional score, perceived effort and a short training note. No dedicated diagnosis, treatment or injury-record fields in MVP unless separately agreed. | Proposed |

## D02 — AI-led plan creation, ownership and sharing

Confirmed product direction:
- AI is the primary creator of personalised shooting plans.
- Athletes aged 16+ may edit their own plans.
- Parents managing junior profiles and authorised coaches may edit the athlete's plan within their agreed permissions.
- Ages 14–15 remain view-only; this decision does not expand junior editing rights.
- A mandatory human author or coach-approval step is not the default plan-creation workflow. Exceptions for incomplete inputs or plans that fail validation remain to be defined.
- The earlier proposed human System Plan Manager publishing role is superseded as the primary plan creator. Whether any separate content-management role is needed remains open.
- Sharing creates a separate, independent copy owned by the receiving archer.
- Changes to either plan do not alter the other, and the sender gains no access to the recipient's data through sharing.
- The recipient's copy follows the existing age and access rules: ages 14–15 remain view-only, with an eligible parent or authorised coach managing edits.
- Only plan instructions and structure are copied; the sender's profile, logs, scores and feedback are not shared.
- AI reviews completed training and available feedback weekly and recommends adjustments to upcoming sessions.
- Weekly recommendations require acceptance by an eligible athlete aged 16+, a parent managing the junior profile, or a coach with the necessary plan-editing permission before changing the active plan.
- Ages 14–15 can view recommendations but cannot accept changes.
- Until accepted, the active plan remains unchanged. Completed-session history is preserved.

Proposed weekly review details:
- Consider actual versus planned arrow volume, session completion, comparable scores, recorded effort, training notes and known schedule or competition changes where available.
- Explain each proposed change and its supporting observations; show current and proposed sessions together.
- Treat missing logs as unknown rather than assuming the athlete did not train.
- Preserve human edits and highlight any proposed changes to edited sessions.
- Review the current plan version when applying accepted changes so newer human edits are not silently overwritten.
- If evidence is insufficient, explain the uncertainty and recommend retaining the plan or requesting missing information rather than inventing progress.
- Weekly review timing, partial acceptance and rejection behaviour remain to be defined.

Proposed MVP behaviour:
- Generate a personal plan from the athlete's goals, experience, current training volume, schedule, range access and competition dates.
- Ask for missing essential inputs rather than inventing athlete details.
- Validate generated plans against agreed scheduling, volume and progression rules before making them active. Define these rules and evaluate plan quality before pilot use.
- Show the plan's assumptions and allow eligible users to edit it.
- Save plan versions and identify whether changes came from AI, the athlete, a parent or a coach.
- Preserve completed-session history. AI regeneration must not silently overwrite human edits; propose changes for review or preserve edited sessions.
- If generation or validation fails, retain the last usable plan and explain what needs attention.
- Include AI usage costs when evaluating the EUR 45 monthly testing budget.

Still to decide:
- Which AI provider or external service will generate plans? No provider or integration is selected.
- What day/time should weekly recommendations be prepared, and can users request an additional review?
- Can users accept individual recommendations, reject them, or edit them before applying?
- Which active-plan edits can each coach make, and how are conflicting edits handled?
- How is a shared copy received and activated? Copy ownership is confirmed; receipt and activation flow remain to be defined.

This introduces AI plan generation into MVP scope. The other project documents will be reconciled only after this product decision document is completed.

## D04/D05 — Coaching access and listings

Confirmed: multiple coaches and mutual invitations are required.

Proposed MVP behaviour:
- Access starts only after an invitation is accepted by the eligible account holder or guardian.
- Each relationship has explicit permissions; being labelled a physio or technical coach alone grants no additional access.
- Coaches do not automatically gain access to another coach's private notes.
- Either eligible party may end a relationship. Subsequent access to the athlete's private data is revoked, including historical records.
- A personal copy of a plan already shared is distinct from continuing access to the originating athlete's data.
- Listing is opt-in and limited to signed-in eligible users. Junior profiles are not listed.
- A parent handles coaching invitations for a junior whose access is view-only.

Confirm these rules before treating them as requirements.

## D06 — Junior profiles, logins and transitions

Confirmed product direction:
- Under 14: the parent manages a child athlete profile; no independent child login.
- Ages 14–15: a junior login can view that athlete's assigned plans, session history and progress.
- From 16: the athlete can edit their own training data, including recording sessions and adapting personal plans within the agreed athlete permissions. This does not grant coach, plan-manager or administrator authority.
- At ages 14–15, view-only means no changes to training data, no logging, no plan sharing and no management of coach relationships.
- Until the age-16 transition, the parent continues to enter logs and make permitted changes. Coaches may act only within their separately agreed permissions.
- Reaching 14 does not automatically remove parental access.

Proposed design implication: retain one stable athlete profile and link the junior's login to it, rather than duplicating or moving training records. Account security and privacy requests need separate handling from read-only training permissions.

Still to decide:
- How is the confirmed age-16 editing transition activated and verified?
- How are age and guardian authority verified, and how is the junior login activated?
- Which actions remain available to parents after greater independence is granted?

A read-only login is a product permission, not a substitute for a lawful basis for processing children's data. In Ireland, the digital age of consent is 16 where an online service relies on consent. The proposed age-14 viewing threshold does not by itself establish independent consent.

Reference: [Irish DPC guidance on children's data and parental consent](https://www.dataprotection.ie/sites/default/files/uploads/2023-04/DPC_ChildrensData_ParentalConsent.pdf).

## D11 — Scoring detail to confirm

Proposed MVP starting point:
- Session/round totals rather than individual-arrow entry.
- Record indoor/outdoor, distance, round/format, arrows shot, total score and applicable maximum.
- Support more than one round in a session.
- Compare scores only within compatible formats.

The product owner must specify the initial supported rounds, whether double rounds are needed and whether individual-arrow entry is essential. Indoor/outdoor alone does not define score validation.

## D12 — Account closure and anonymisation

Confirmed intent: attempt to anonymise all user-related data on leaving/deleting an account, while preserving useful data only where it is genuinely anonymous.

Proposed operating rules:
1. Treat leaving as an explicit closure request; sign-out, inactivity or ending a coaching relationship alone does not trigger deletion.
2. Offer a data export before closure and verify that the requester is authorised. Junior and guardian closure rules require explicit definition.
3. Revoke account access, invitations and active relationships when closure is confirmed.
4. Assess all relevant records, including profiles, session histories, free text, relationships, identifiers, logs and any files.
5. Do not treat changing a name to "Anonymous" as sufficient. Remove or generalise identifying details and linkages; prefer anonymous aggregate statistics where detailed histories could identify someone.
6. Delete data that cannot be adequately anonymised, subject to any documented retention obligation.
7. Define closure-processing deadlines and finite backup retention. Restoring a backup must not permanently reintroduce deleted accounts or data.
8. Keep any required retained records restricted, purpose-limited and subject to an agreed expiry.

Still to decide: export format, processing deadline, backup expiry, inactive-account policy and what anonymous statistics have a useful purpose. No guarantee is made that every detailed record can safely be retained.

References:
- [Irish DPC: storage limitation and retention](https://dataprotection.ie/en/faqs/responsibilities-data-controllers/how-long-should-personal-data-be-held-meet-obligations-imposed-gdpr)
- [Irish DPC: anonymisation and pseudonymisation](https://www.dataprotection.ie/en/dpc-guidance/anonymisation-pseudonymisation)

## D14/D15 — Proposed pilot and feedback defaults

These are review suggestions, not commitments:
- Pilot: 5–10 athlete profiles, at least 2 coaches and at least 1 parent-managed junior.
- Observe usage for 4 weeks.
- At least 80% of pilot participants complete their role's core journey without assistance.
- At least 60% of athlete profiles have weekly recorded activity in 3 of the 4 weeks, including parent-entered activity.
- No unresolved critical access-control or data-loss defects at release.
- Collect feedback from each participating role.
- Required logging: session status and actual arrow count for shooting sessions.
- Optional logging: round score, perceived effort on a defined scale and a short training note.
- Confirm handling of rest days, skipped sessions and exercise-only sessions.
- Do not assume a short free-text note cannot contain sensitive information; explain its intended training use and restrict access.

## Decision record

| Date | Decision IDs | Decision / change | Owner |
|---|---|---|---|
| 21 October 2026 | D01–D08, D11–D13 | Recorded product-owner answers; unresolved details remain visible. | Product owner |
| 21 October 2026 | D06 | Revised age-14 junior access to viewing only; parent continues to manage edits. | Product owner |
| 21 October 2026 | D06 | Confirmed editing rights from age 16; ages 14–15 remain view-only. Parent access after transition remains unresolved. | Product owner |
| 21 October 2026 | D02 | Confirmed AI-led personalised plan creation with human editing; supersedes the proposed human-first publishing workflow and the original MVP exclusion for AI plan generation. | Product owner |
| 21 October 2026 | D02 | Confirmed weekly AI recommendations based on completed training and feedback, with eligible-user acceptance before changes update the active plan. | Product owner |
| 21 October 2026 | D02 | Confirmed that sharing creates an independent copy owned by the receiving archer, subject to existing age and access rules. | Product owner |
| 21 October 2026 | D12 | Replaced blanket permanent retention with deletion or genuine anonymisation on explicit account closure. | Product owner |

## Completion checklist

- [x] Confirm AI as the primary plan creator, with eligible athlete, parent and coach editing.
- [x] Confirm weekly AI recommendations with eligible-user acceptance before plan updates.
- [x] Confirm shared copies belong to the receiving archer and are independent of the original.
- [ ] Confirm weekly review details, validation, edit preservation and shared-copy receipt/activation.
- [ ] Confirm coach permissions, listing audience and relationship termination rules.
- [x] Confirm junior editing threshold: 16; ages 14–15 are view-only.
- [ ] Confirm verification and parent/junior transition rules.
- [ ] Confirm initial scoring formats and totals versus individual-arrow entry.
- [ ] Confirm retention operations and closure timescales.
- [ ] Accept or revise D10, D14 and D15 proposals.
- [ ] Identify pilot participants; keep D09 deferred until scope estimation.
- [ ] Mark this document approved before propagating decisions to documents 02–07.
