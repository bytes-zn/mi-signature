.PHONY: up down build migrate logs test test-integration lint format check sync lock secrets prod-up prod-down prod-config

# --- Docker ---
up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

migrate:
	docker compose run --rm migrate

logs:
	docker compose logs -f

# Production stack (adds the production baseline, see docker-compose.prod.yml)
prod-up:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

prod-down:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml down

prod-config:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml config

# --- Local development (uv) ---
sync:
	uv sync

lock:
	uv lock

# Print the secrets required for a production deployment.
secrets:
	uv run python scripts/generate_secrets.py

test:
	uv run pytest

test-integration:
	RUN_INTEGRATION_TESTS=1 uv run pytest tests/integration

coverage:
	uv run pytest --cov=app --cov-report=term-missing

lint:
	uv run ruff check .
	uv run black --check .
	uv run isort --check .
	uv run mypy app

format:
	uv run ruff check --fix .
	uv run black .
	uv run isort .

check: lint test
