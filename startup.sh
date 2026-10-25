#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/app"

python manage.py collectstatic --noinput

exec python -m gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
