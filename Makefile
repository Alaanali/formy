# Common workflows. `make` on its own lists them.
#
# Every target assumes `uv` and Docker. The containers bind non-default
# ports (5440/6390) so this stack never collides with anything else running
# locally.

.DEFAULT_GOAL := help
.PHONY := help install up down reset bootstrap flush migrate migrations seed \
        run run-load worker beat \
        test test-fast cov lint fmt check \
        schema shell dbshell logs clean

SETTINGS ?= formy.settings.dev
PORT     ?= 8000

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

bootstrap: up ## One-shot setup: containers, .env, migrate
	@test -f .env || cp .env.example .env
	uv sync --all-groups
	uv run python manage.py migrate --settings=$(SETTINGS)

# --- database ----------------------------------------------------------------

migrate: ## Apply migrations
	uv run python manage.py migrate --settings=$(SETTINGS)

migrations: ## Create migrations for model changes
	uv run python manage.py makemigrations --settings=$(SETTINGS)

flush: ## Delete all data, keeping the schema
	uv run python manage.py flush --no-input --settings=$(SETTINGS)

# --- running -----------------------------------------------------------------

run: ## Run the development server (PORT=8000)
	uv run python manage.py runserver $(PORT) --settings=$(SETTINGS)

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

schema: ## Write the OpenAPI document to schema.yaml
	uv run python manage.py spectacular --file schema.yaml --fail-on-warn

clean: ## Remove caches and generated artifacts
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage schema.yaml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
