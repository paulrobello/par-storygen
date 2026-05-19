.PHONY: build setup test lint fmt typecheck checkall Checkall precommit run resume clean package deploy api-dev web-install web-dev web-build

# ── Web (Next.js) ──
web-install:         ## Install Next.js frontend dependencies
	cd web && npm install

web-dev:             ## Start Next.js dev server on :8100
	cd web && npx next dev --port 8100

web-build:           ## Build Next.js for production
	cd web && npm run build

# ── API (FastAPI) ──
api-dev:             ## Start FastAPI dev server on :8101
	uv run uvicorn storygen_api.main:app --reload --port 8101

api-prod:            ## Start FastAPI production server on :8101
	uv run uvicorn storygen_api.main:app --port 8101 --workers 1

build:
	uv sync

setup:
	uv sync

test:
	uv run python -m pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

typecheck:
	uv run pyright

checkall: fmt lint typecheck test

Checkall: checkall

run:
	uv run storygen

resume:
	uv run storygen run --resume

clean:
	rm -rf .pytest_cache .ruff_cache .pyright build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

precommit:
	uv run pre-commit run --all-files

package:
	uv build

deploy:
	gh workflow run release.yml
