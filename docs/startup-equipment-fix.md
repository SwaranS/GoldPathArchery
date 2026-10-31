# PR #25 startup and integration repair

Verified 31 October 2026 against feature merge 80bb393.

The merge retained advanced equipment routes, templates, migrations and services,
but replaced several integration files with their basic-equipment versions:

- `equipment_media` disappeared, making URL import fail during Django startup.
  Restored the authenticated GET endpoint backed by `photo_bytes`, with private,
  no-store responses, JPEG content type and nosniff. Authorization stays in the
  existing service: owners/live viewers can read ordinary photos; shared recipients
  require an approved connected share with that exact photo selected. Receipts
  require owner/editing-guardian permission. Removed photos are unavailable.
- `equipment` lost its section parameter and advanced handlers. Restored section
  validation, forms, page-specific templates, actions and redirects. Both account
  and scoring equipment URL families, including their legacy entry points, work.
  Photos remain alongside components/configurations and receipts under purchases.
- Advanced forms, revision filters, activity recording, configuration-based sight
  marks and scoring-start configuration snapshots were reverted as well. Restored
  those integrations without reverting the merged training module or navigation.
- The merge also reverted three section-aware test assertions; restored them.

Migrations 0003–0008 form a linear dependency chain after scoring 0002, with
accounts 0005 and the swappable user dependency where needed. Migration 0005
already adds configuration_revision and makes bow_revision nullable; restoring
the matching model resolves the drift. No new migration or historical migration
rewrite is needed. The populated 0002-to-latest upgrade test confirms athlete,
equipment, arrows, marks and scoring snapshots survive unchanged.

Verification:

- Django check: clean; makemigrations --check --dry-run: no changes.
- Full PostgreSQL 17 / Python 3.13 Django suite: 172 tests, all pass, no skips.
- SQLite suite: 172 tests, passes with four PostgreSQL concurrency tests skipped.
  Native tests require the repository root on PYTHONPATH, as startup.sh and Docker
  already configure for the merged training module.
- Fresh database migrations through scoring 0008 and training 0001: pass.
- Production settings check and collectstatic: pass (140 files, 420 processed).
- Isolated Compose build and web startup: pass; /accounts/login/ returns HTTP 200.
- URL callback signature audit and equipment/scoring page tests pass. Media tests
  cover anonymous/unrelated access, coach receipt denial, owner receipt access,
  removal, selected sharing/revocation, HTTP methods and response headers.

All database operations used a separate goldpath-startup-audit Compose project and
its new database, or Django's disposable test database. The existing WSL-mounted
application and its database were untouched. Audit containers were stopped and
their database volume retained. No database was reset, and main was not merged.
Azure storage round-trip and interactive browser accessibility QA were not run.
Fresh GitHub Actions results are reported separately after the feature push.
