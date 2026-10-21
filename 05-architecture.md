# GoldPathArchery — Architecture Proposal

Status: Proposal; technology and hosting decisions pending  
Dependencies: [product decisions](01-product-decisions.md), [requirements](02-mvp-requirements.md)

## Proposed approach

Use one deployable application organised into modules, backed by a relational database. This keeps operation manageable for one maintainer while keeping responsibilities clear. Revisit only when a concrete requirement justifies additional services.

This document does not select a framework, database product, cloud provider or paid service.

## Logical components

| Component | Responsibility |
|---|---|
| Public website | Product information and access entry points |
| Application UI | Archer, coach and approved parent workflows |
| Server application | Validation, permissions, planning, logging and reporting |
| Relational database | Accounts/references, relationships, plans, sessions and logs |
| Identity capability | Sign-in, verification and recovery; managed versus framework-supported approach TBD |
| Email capability | Account and invitation messages; provider TBD |
| Operations | Deployment, secrets, error reporting, monitoring and backups |

## Proposed modules

Accounts and access; archer profiles; coaching/guardian relationships; planning; session logging; progress reporting; restricted administration.

All protected reads and writes pass through server-side authorisation. Reports use the same access rules as underlying records.

## Candidate data model

| Entity | Purpose / key relationship |
|---|---|
| User | Account identity or external identity reference |
| ArcherProfile | Training profile associated with an account or agreed junior ownership model |
| CoachingRelationship | Coach, athlete, status and lifecycle dates |
| GuardianRelationship | Guardian, junior, verification and status; design pending D06 |
| TrainingPlan | Athlete-specific plan and ownership/version context |
| PlannedSession | Date, instructions and targets within a plan |
| SessionLog | Actual activity linked to athlete and, where applicable, planned session |
| ScoringFormat | Agreed round definitions and validation metadata |
| AuditEvent | Approved security and administration events with restricted retention |

Exact columns, uniqueness rules, deletion behaviour and plan revision strategy follow the unresolved product decisions. Do not assume one session per date. Prevent duplicate submissions without preventing legitimate multiple sessions.

## Environments and deployment

- Local development, staging and production use separate configuration.
- Staging and production use separate databases and credentials.
- Automated checks run on proposed changes.
- A reviewed release deploys a versioned artifact with controlled migrations.
- Production has HTTPS, a custom domain, health checks and error reporting.
- A rollback plan covers both application versions and migration compatibility.

## Data and operations

Store secrets outside source control. Minimise collected personal data. Define region, retention, export, deletion and access audit rules before production. Specify backup frequency, retention, recovery point and recovery time targets, then test restoration. Avoid real junior data in development fixtures.

## Decisions and validation still required

1. Confirm account and permission model.
2. Compare framework options against maintainer experience and MVP needs.
3. Select relational database and migration tooling.
4. Compare hosting, identity and email options using current official documentation and pricing.
5. Record accepted choices in architecture decision records with alternatives, rationale and cost assumptions.
6. Define upload needs before introducing object storage.
7. Complete a security and operational review before pilot use.

No capacity, cost or availability commitments are made by this proposal.
