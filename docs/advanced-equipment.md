# Advanced equipment implementation record

## M0 baseline (30 October 2026)
Remote main fetched at 0d47839; original clean checkout feature/user-equipment at da1e25b.
New branch codex/advanced-equipment-management starts at remote main. Main lacks the
revision/sight-mark implementation assumed by the specification. Reused da1e25b and
its athlete-discipline migration prerequisite 3a44018, without the training module.
Original main: 102 Django tests passed, 3 skipped (SQLite, from app directory).
Running discovery from the repository root finds zero tests and is not validation.

Architecture: Django views/forms -> equipment services -> scoring models. Authorization
uses accounts.permissions.can per operation, never self-selected roles. Existing
Equipment, revisions, arrows and sight marks remain authoritative legacy records.
No automatic inference of legacy components; basic equipment remains usable.

Schema decisions: stable components have one owner and append-only typed snapshots.
Configurations reference exact component revisions through normalized membership.
All writes lock the athlete and target rows, check current grants and optimistic
revision tokens, then append audit data in the same transaction. PostgreSQL row-lock
verification is required before release; SQLite cannot establish concurrency safety.
Do not run shared database migrations or deploy from this branch without review.
Test database creation/migration is isolated to disposable test databases.

## M1/M2
Component specs use schema version 1, documented in the workspace field reference
and `scoring/component_specs.py`. Numeric names carry units; optional fields are not
inferred. Configuration membership uses immutable revision foreign keys. Component
updates require explicit configuration adoption; rename is a material version change.
All physical fit remains unverified and requires acknowledgement; declared discipline
conflicts are rejected. Interface mismatch is an acknowledged warning, not fit advice.
Seven statuses apply to physical components; only active components are selectable.
Legacy equipment retains its existing active/archive behavior.
