.PHONY: build setup test lint fmt typecheck checkall Checkall precommit run resume clean package deploy

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
