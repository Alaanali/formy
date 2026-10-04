# Common workflows. `make` on its own lists them.
#
# Every target assumes `uv` and Docker. The containers bind non-default
# ports (5440/6390) so this stack never collides with anything else running
# locally.

.DEFAULT_GOAL := help
.PHONY: help install up down reset bootstrap flush migrate migrations seed \
        run run-load worker beat dev frontend \
        test test-fast cov lint fmt check e2e load load-headless perf \
        schema shell dbshell logs clean

SETTINGS ?= formy.settings.dev
PORT     ?= 8000
RESPONSES ?= 50

help: ## List available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- setup -------------------------------------------------------------------

install: ## Install dependencies, including dev and load-test groups
	uv sync --all-groups

up: ## Start Postgres and Redis, waiting for health checks
	docker compose up -d --wait

down: ## Stop the containers, keeping data
	docker compose down

reset: ## Destroy the containers and their data, then start fresh
	docker compose down -v
	docker compose up -d --wait
	$(MAKE) migrate

bootstrap: up ## One-shot setup: containers, .env with keys, migrate, seed
	@# Writes an encryption key only when .env does not already have one.
	@# Overwriting an existing key would leave every stored answer unreadable.
	@test -f .env || cp .env.example .env
	uv sync --all-groups
	@grep -q 'FIELD_ENCRYPTION_KEY=REPLACE' .env && \
		sed -i "s|FIELD_ENCRYPTION_KEY=.*|FIELD_ENCRYPTION_KEY=$$(python3 -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())')|" .env \
		&& echo "Generated a field encryption key." || echo "Keeping the existing encryption key."
	uv run python manage.py migrate --settings=$(SETTINGS)
	uv run python manage.py seed_demo --responses $(RESPONSES) --settings=$(SETTINGS)

# --- database ----------------------------------------------------------------

migrate: ## Apply migrations
	uv run python manage.py migrate --settings=$(SETTINGS)

migrations: ## Create migrations for model changes
	uv run python manage.py makemigrations --settings=$(SETTINGS)

seed: ## Seed a published demo survey (RESPONSES=50 by default)
	uv run python manage.py seed_demo --responses $(RESPONSES) --settings=$(SETTINGS)

flush: ## Delete all data, keeping the schema
	uv run python manage.py flush --no-input --settings=$(SETTINGS)

# --- running -----------------------------------------------------------------

run: ## Run the development server (PORT=8000)
	uv run python manage.py runserver $(PORT) --settings=$(SETTINGS)

dev: ## Run API, worker and frontend together (Ctrl-C stops all three)
	@# honcho rather than backgrounded jobs: it forwards the interrupt to
	@# the whole process group, so nothing is left holding port 8000.
	@test -d frontend/node_modules || $(MAKE) frontend
	uv run honcho start

frontend: ## Install the frontend's dependencies
	pnpm --dir frontend install

run-load: ## Run the server with throttles raised, for load testing
	@# A load test comes from a single address, so the per-IP rate limits
	@# that protect the real deployment would cap the run instead of the
	@# application. Raised here and nowhere else.
	THROTTLE_SUBMISSION_START=100000/hour \
	THROTTLE_SUBMISSION_WRITE=1000000/hour \
	THROTTLE_AUTH=100000/minute \
	uv run python manage.py runserver $(PORT) --settings=$(SETTINGS)

worker: ## Run a Celery worker for every queue
	uv run celery -A formy worker -Q rollups,exports,mail -l info

beat: ## Run the Celery scheduler
	uv run celery -A formy beat -l info

shell: ## Django shell
	uv run python manage.py shell --settings=$(SETTINGS)

dbshell: ## psql against the application database
	uv run python manage.py dbshell --settings=$(SETTINGS)

logs: ## Tail the container logs
	docker compose logs -f

# --- quality -----------------------------------------------------------------

test: ## Run the full test suite
	uv run pytest

test-fast: ## Run the suite, stopping at the first failure
	uv run pytest -x -q

lint: ## Check formatting and lint rules
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Apply formatting and autofixable lint rules
	uv run ruff check --fix .
	uv run ruff format .

check: ## Everything CI would run: lint, format, migration drift, tests
	uv run ruff check .
	uv run ruff format --check .
	uv run python manage.py makemigrations --check --dry-run
	uv run pytest -q

cov: ## Run the suite with a coverage report
	uv run pytest --cov=accounts --cov=analytics --cov=core --cov=exports \
	       --cov=invitations --cov=responses --cov=surveys \
	       --cov-report=term-missing --cov-report=html

schema: ## Write the OpenAPI document to schema.yaml
	uv run python manage.py spectacular --file schema.yaml --fail-on-warn

# --- verification against a running server -----------------------------------

e2e: ## Walk every endpoint over HTTP against a running server
	API_BASE=http://127.0.0.1:$(PORT) uv run python scripts/e2e_smoke.py

perf: ## Check rollup counters hold under concurrent submissions
	@# Needs `make run-load`, not `make run`: 40 concurrent starts exceed the
	@# default 20/hour public throttle and would all be rejected.
	API_BASE=http://127.0.0.1:$(PORT) uv run python scripts/concurrency_check.py

load: ## Open the Locust web UI (http://localhost:8089)
	uv run locust -f loadtest/locustfile.py --host http://localhost:$(PORT)

load-headless: ## Run a fixed load profile and fail on the configured thresholds
	@# Requires `make run-load`. Against `make run` the public throttles
	@# reject most of the burst and the run fails for the wrong reason.
	uv run locust -f loadtest/locustfile.py --host http://localhost:$(PORT) \
		--headless --users $(USERS) --spawn-rate $(SPAWN) --run-time $(RUNTIME) \
		--html loadtest/report.html --csv loadtest/results

USERS   ?= 50
SPAWN   ?= 10
RUNTIME ?= 1m

clean: ## Remove caches and generated artifacts
	@# Everything here is untracked or gitignored, so this never turns a
	@# clean tree into pending deletions.
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage schema.yaml \
	       loadtest/report.html loadtest/results_*.csv
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
