# GoldPathArchery — Roles and Permissions

Status: Proposed model; review before implementation  
Dependencies: D02, D04–D06 and D12 in [product decisions](01-product-decisions.md)

## Principles

Deny access unless explicitly granted. Check both user identity and relationship to the requested resource on the server. Hiding a button is not an access control. Roles may overlap, but one role must not grant access to unrelated athletes.

## Proposed access matrix

| Action | Visitor | Archer | Coach | Parent / guardian | Administrator |
|---|---|---|---|---|---|
| View public pages | Yes | Yes | Yes | Yes | Yes |
| View archer profile | No | Own | Active linked athletes; approved fields | Verified linked juniors; fields TBD | Only under an approved support policy |
| Edit profile / goals | No | Own; junior rules TBD | Coaching fields only, if approved | Scope TBD under D06 | Explicit support actions only |
| Create / assign training plan | No | TBD under D02 | Active linked athletes | TBD under D06 | No routine coaching authority |
| View assigned plan | No | Own | Active linked athletes | Verified linked juniors, if approved | Explicit support access only |
| Record / edit session log | No | Own; junior rules TBD | Read-only proposed | TBD under D06 | No routine editing |
| View logs and progress | No | Own | Active linked athletes | Verified linked juniors, if approved | Explicit support access only |
| Establish / end coach relationship | No | Approval rights subject to junior rules | Request or end own relationship | Approval rights TBD | Support override policy TBD |
| Manage pilot accounts | No | No | No | No | Approved actions, audited |

## Relationship lifecycle

1. Proposed: a coach or athlete initiates an invitation.
2. The correct account holder or verified guardian accepts under the agreed rules.
3. Access begins only once the relationship is active.
4. Either eligible party can end the relationship.
5. Subsequent requests are rechecked; stale sessions or cached data must not preserve revoked access.
6. Historical access, retention and reassignment rules remain decisions under D05 and D12.

Parent relationships require a separate verification and lifecycle process. A declared role alone does not prove authority over a junior.

## Open policy decisions

- Junior account ownership, age transitions and guardian permissions.
- Multiple coaches, read-only coaches and which fields each sees.
- Who can edit completed logs and whether changes need an audit trail.
- Administrator support access, justification, audit and expiry.
- Account deletion, data export and removal of linked-user access.

## Required verification

Test own, linked and unrelated records for every operation. Include direct URL/API access, guessed identifiers, expired invitations, revoked relationships and role changes. Verify that permission failures never modify data.
