# Disposable local M1 validation

These tools never deploy, contact a real club or provision Azure. They connect only
to the dedicated PostgreSQL account at `127.0.0.1:55440` from
`config.clubs_test_settings`. Each run creates fresh `clubs_validation_<random>`
and `clubs_validation_<random>_restore` databases, then removes only those databases.
No existing application database is migrated, restored over, or deleted.

From this directory, install the locked development dependencies:

```text
npm ci --ignore-scripts
node node_modules/playwright/cli.js install chromium
```

Use `PLAYWRIGHT_BROWSERS_PATH` for an unsynced local browser cache if the workspace
is in OneDrive. Set the same location with `--browser-cache` when running the tool.
The Node packages and downloaded browser are test-only, not application dependencies.
The axe adapter is pinned to a version compatible with the available Node 20 runtime.

Start the existing disposable test container (or create the PostgreSQL 17 container
described in `config.clubs_test_settings`), then run from the repository root:

```text
python tests/clubs_validation/validate_local.py --run
```

Optional: `--browser-cache <absolute-directory>` and `--container <test-container>`.
The container must expose the same disposable database at localhost port 55440.
The command requires the project's Python dependencies, Node 20+, and Docker CLI.

The run:

1. Applies the pre-clubs schema in a newly created database; makes synthetic
   athlete, guardian-managed junior, equipment revision, completed individual-arrow
   score and draft-plan records; fingerprints their complete stored values.
2. Applies the additive club/MFA migrations and verifies preservation.
3. Runs a real headless Chromium workflow with server-issued synthetic sessions:
   private draft → submission → reviewer TOTP → private evidence → target-confirmed
   approval → scoped dashboard, plus public profile and outsider-denial checks.
4. Scans desktop/mobile pages using axe WCAG 2 A/AA and 2.1 AA tags, duplicate-ID
   and horizontal-overflow checks, keyboard skip-link focus and PNG captures.
5. Exercises feature-off rollback while preserving personal data and additive tables.
6. Takes a real PostgreSQL custom-format backup and restores it into a separate
   empty database. Verifies legacy fingerprints and club/audit counts.
7. Copies synthetic blobs to a separate restore directory, exercises expired
   evidence cleanup twice, and checks that original source blobs remain untouched.

All outputs live under ignored `artifacts/run-<random>/`: JSON evidence, screenshots,
and a synthetic backup. Never use this harness with real data, Azure credentials or
real account sessions. No secrets/sessions are written into report JSON or console
output. The generated database dump contains only disposable synthetic records.

OAuth itself is not automated: fixture sessions replace that external prerequisite.
The actual TOTP challenge, CSRF forms, service permissions and HTTP routes are used.
The independent verification outcome is explicitly fictional. This is not an
independent human verification, real staging test, live Azure check, legal approval,
or a complete manual screen-reader/WCAG certification.

The PostgreSQL-only `clubs.test_release_validation` test additionally uses independent
Python processes against DatabaseCache and proves a TOTP code has exactly one winner
and remains rejected after those processes exit. No sensitive subprocess input is logged.

## Failure handling

Reports must not be marked passed if a browser stage fails. Created databases are
tracked and removed in `finally`, even on failure; only generated, allowlisted names
can be dropped. If the Python process is forcibly killed, inspect the exact generated
names in that run's report before manually removing any leftover test database.
Never substitute a deployed container/database or run restore cleanup against the
original storage namespace.
