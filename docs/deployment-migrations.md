# Database migrations during development deployments

The relationship release adds migration `accounts.0003_athleteprofile_relationshipaudit_and_more`. The account profile page queries these tables even if the signed-in user has not created an athlete yet.

The GitHub Actions `checks` job applies migrations only to a disposable PostgreSQL container. Packaging and deploying the application does not migrate the Azure database. Previously `startup.sh` collected static files and started Gunicorn without updating that database. Serving the relationship release over the `0002_userrole` schema therefore raises a missing-table database error on `/account/profile/`.

`startup.sh` now runs `python manage.py migrate --noinput` before collecting static files and starting workers. The script exits if migration fails. Ensure App Service's startup command uses `bash startup.sh` and that `DJANGO_SETTINGS_MODULE=config.production` and the existing database environment variables are configured. Google authentication configuration is unchanged.

## Diagnose and recover the already deployed application

Check Azure Log stream for the request traceback. A missing relationship migration typically reports `relation "accounts_athleteprofile" does not exist` (or another new accounts table). Without the actual traceback this remains a likely diagnosis, not a verified live root cause.

In App Service SSH, using the same Python environment, database configuration and Django settings as the running application, run from the deployed `app` directory:

```sh
python manage.py showmigrations accounts
python manage.py migrate --noinput
python manage.py showmigrations accounts
```

Confirm `[X] 0003_athleteprofile_relationshipaudit_and_more`, then reload `/account/profile/`. These commands apply the supplied schema migrations; do not use `--fake`, reset the database, or delete existing accounts. If 0003 is already applied or migration fails, inspect the actual traceback before taking further corrective action.

The durable fix requires deploying this updated startup script through the usual reviewed release process. This fix was prepared on `feature/user-accounts`; no merge, Azure database migration or deployment was performed by the coding agent.

## Regression coverage

`accounts.test_release_upgrade.AccountReleaseUpgradeTests` temporarily downgrades only the disposable test database to accounts migration 0002, creates an existing logged-in user and parent role, reproduces the profile-page missing-table exception, then migrates forward and verifies HTTP 200 with the same account, session and role preserved. Run:

```sh
python app/manage.py test accounts --settings=config.test_settings
```

The same regression runs against PostgreSQL with normal settings in Docker CI. For a future multi-instance deployment, move migrations to a serialized release job before routing requests to the new release rather than allowing multiple application instances to migrate concurrently.
