#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/app"
export PYTHONPATH="$(dirname "$PWD")${PYTHONPATH:+:$PYTHONPATH}"
# CI migrates a disposable database, not the App Service database. Apply the
# deployed release's migrations before any worker can serve its new models.
# set -e stops startup if the database upgrade fails.
python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec python -m gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
