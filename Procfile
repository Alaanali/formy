# `make dev` runs these three through honcho. One Ctrl-C stops all of them.
api: uv run python manage.py runserver 8000 --settings=formy.settings.dev
worker: uv run celery -A formy worker -Q rollups,exports,mail -l warning --concurrency 2
web: pnpm --dir frontend dev
