.PHONY: build setup test lint fmt typecheck checkall web-check precommit run resume clean package deploy api-dev web-install web-dev web-build

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
	uv sync --extra api --dev

setup:
	uv sync --extra api --dev

test:
	uv run python -m pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

typecheck:
	uv run pyright

# ARC-008: the gate is read-only — `fmt` MUTATES files (ruff format rewrites
# the tree), so running it before `lint`/`typecheck` would auto-fix any
# formatting drift and mask failures rather than surfacing them. Pre-commit
# already runs `ruff format` on staged files; CI runs `make checkall` as the
# authoritative green gate. Run `make fmt` explicitly to format.
checkall: lint typecheck test web-check

# QA-004: the web gate (eslint + vitest + tsc). Tolerates an absent
# web/node_modules with a clear notice instead of failing, so `make checkall`
# stays runnable in environments that carry only the Python toolchain (notably
# CI's python-gate job, where the web surface is covered by the separate
# web-build / web-e2e jobs). Locally, run `make web-install` once to enable it.
web-check:
	@if [ ! -d web/node_modules ]; then \
		echo "web-check: web/node_modules absent - skipping (run 'make web-install' to enable; CI covers web in the web-build/web-e2e jobs)"; \
	else \
		cd web && npm run lint && npm run test && npx tsc --noEmit; \
	fi

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
