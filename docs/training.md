# Django training generator

## Why the page was missing

Investigation on 29 October 2026 found:

- GitHub `feature/training-plan` at `a195032` added a FastAPI prototype (`app/main.py`, router, schemas, engine and model objects), with no Django URL, view or HTML page for `/training/new`.
- GitHub main at `0d47839` was three commits ahead and one training commit behind that branch. This integration starts from the training branch; main has not been merged or changed.
- The live Docker web container mounts `/home/swaran-u/projects/GoldPathArchery/app` at `/app`. That Linux checkout was already on the training branch. The Windows OneDrive checkout was a separate checkout on `codex/fix-account-ci`; edits there do not automatically reach the running container.
- Docker starts `python manage.py runserver 0.0.0.0:8000`, not FastAPI. Its requirements lacked Pydantic/FastAPI and its Python path did not support the prototype's `app.*` imports from `/app`.
- Django registered `/account/` and `/scoring/`, with an existing planning brief under `/account/athletes/<id>/plans/`. Rebuilding the unchanged branch could not create a missing training page.

## What is now connected

`/training/new` and `/training/new/` serve an authenticated intake form. Athlete choices derive from live Django relationships and `edit_plan` permission; callers cannot supply another athlete identity through headers. Bow division comes from the selected athlete profile. Submission validates dates, schedule, volume and poundage constraints, then stores a queued `training.GeneratedPlan` row. Generation runs outside the HTTP request in the `training-worker` service. Both submission and execution check permissions under the athlete row lock.

The worker calls the existing periodization engine and saves its complete roadmap, including phases, weeks, sessions and drill blocks, in PostgreSQL JSON. Results survive web/worker restarts. The result page checks current view permission on every request. Recent drafts are listed on the intake page; the athlete Plans page links there with that athlete selected.

Generation remains a **draft**, regardless of the prototype engine's internal `active` flag. Human review, publication/activation, live session logging and recalibration are not connected to Django yet. The prototype FastAPI routes are not exposed by this integration. No SQLAlchemy/Alembic migrations are run; Django owns the new persisted draft table. The existing plan brief remains independent and does not auto-submit or auto-generate a draft.

The worker holds a PostgreSQL row lock while generating, using `skip_locked` to allow multiple workers. If killed before commit, the queued request remains available for retry. A failed request is recorded without stopping later jobs. Refresh a queued draft page to check progress. For diagnosis, inspect worker logs. The engine's lightweight model fallback is used; generated hierarchies are persisted as Django-owned JSON rather than SQLAlchemy rows.

## Local sync and restart

The fix branch is `codex/django-training-generator` in both local checkouts. It has not been pushed. The live checkout and services have already been updated. Run these commands **inside Ubuntu/WSL** to rebuild/restart:

```bash
cd /home/swaran-u/projects/GoldPathArchery
git status -sb
git switch codex/django-training-generator
docker compose build web training-worker
docker compose up -d db
docker compose run --rm --no-deps web python manage.py migrate
docker compose up -d --force-recreate web training-worker
docker compose exec -T web python manage.py check
docker compose ps
curl -I http://127.0.0.1:8000/training/new
```

The signed-out URL should return `302` to `/accounts/login/?next=/training/new`; after signing in it displays the form. An athlete with plan editing permission is needed to submit. A `404` indicates the wrong code/URL configuration; a queued draft that never completes usually indicates a stopped worker or missing migrations.

To sync later committed changes from the Windows checkout, first ensure the Linux checkout has no conflicting edits (preserve any unrelated changes rather than discarding them):

```bash
cd /home/swaran-u/projects/GoldPathArchery
git fetch '/mnt/c/Users/swara/OneDrive/Documents/ChatGPT/GoldPathArchery 2' codex/django-training-generator
git switch codex/django-training-generator
git merge --ff-only FETCH_HEAD
```

Then run the rebuild/restart sequence above. `git pull origin feature/training-plan` alone cannot retrieve this unpushed local integration. Source changes in the Linux bind mount reload Django; dependency/Dockerfile changes need a rebuild, and worker code changes require restarting the worker. Keep the PostgreSQL volume; no `down -v` is needed.

## Validation

```bash
docker compose run --rm --no-deps web python manage.py test training accounts scoring
docker compose run --rm --no-deps web python manage.py makemigrations --check --dry-run
```

The original training tests live outside `/app`. Run them from the repository root in an isolated environment with `pip install -r requirements-training-tests.txt`, then `python -m pytest -q tests/training_plans`. FastAPI is a test-only dependency for those prototype route tests, not a deployed service.

Verified: 5 new Django integration tests, 102 existing Django tests and 33 original generator/API tests pass. Checks cover authentication, CSRF, durable draft generation, revoked/foreign athlete access, failure handling, bounded inputs and poundage lockout. Model/migration drift and Django system checks pass. The live URL returns the expected sign-in redirect after restart.
