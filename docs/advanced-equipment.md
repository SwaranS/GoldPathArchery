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

## Sharing connection policy
Connected means existing athletes with a common unrevoked guardian (view/edit), or
an athlete whose account has an explicit unrevoked coach relationship to the other.
A common self-selected coach role is insufficient. UUID entry never discovers a
recipient inventory. Each recipient must approve through its own edit-profile grant.
Live relationship and share checks apply to future selections. Shared payloads exclude
private notes and serial references. Transfers append an ownership revision, revoke
all prior shares and preserve original revisions and configuration snapshots.

## Private media, purchases and maintenance
Install requirements.txt. Local development: EQUIPMENT_MEDIA_BACKEND=local and
EQUIPMENT_MEDIA_ROOT to a private directory outside static/media hosting. Production:
EQUIPMENT_MEDIA_BACKEND=azure, EQUIPMENT_AZURE_CONNECTION_STRING from environment
secret management and EQUIPMENT_AZURE_CONTAINER naming an existing private container.
No container is created or made public. Storage checks reject public containers.
Every download passes live authorization; keys are never included in HTML payloads.
Receipts currently support photographed JPEG/PNG/WebP images, not PDF or office files.
Uploads accept at most 8 MB / 20 million pixels and re-encode to metadata-free JPEG
bounded to 2400 pixels. Active content formats are rejected. Images are not claimed
virus-scanned; Azure malware scanning can be applied as an operational defense.

Maintenance and purchases are append-only with correction links. Supported ISO
currencies are listed by the purchase form; no currency conversion or default is
inferred. Financial data and receipts require athlete/editing guardian authority,
including historical owner authority following transfers. Shared recipients cannot
read maintenance, purchase records or receipts. Removed images become immediately
inaccessible. Operators must periodically reconcile blob keys to EquipmentPhoto:
retain active keys, remove inactive keys only after the agreed retention interval,
and remove unreferenced keys older than 24 hours (never delete fresh uploads).
Failed metadata writes attempt immediate blob cleanup. Do not publicly serve the
local private directory. Test storage uses temporary directories only.
