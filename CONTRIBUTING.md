# Contributing to par-storygen

How to set up a development environment, run the gates, and land a change. Short and factual — the authoritative depth lives in `CLAUDE.md` and `docs/ARCHITECTURE.md`.

## Prerequisites

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/) for all Python tooling (no pip/poetry/pipenv)
- GNU-compatible `make`
- Node.js (for the `web/` frontend; see `web/package.json` for the pinned versions)

## Setup

```bash
git clone https://github.com/paulrobello/par-storygen
cd par-storygen
make build         # uv sync --extra api --dev  (installs the api + dev extras)
make web-install   # cd web && npm install       (frontend deps, only if you touch web/)
```

`make build` resolves with `--extra api --dev` so the FastAPI surface and the test/tooling deps are available in one shot.

## The gate

Run this before every commit. It is the same gate CI runs.

```bash
make checkall      # ruff lint + pyright (strict) + pytest
```

`make checkall` runs the Python gate today; the web gate (Next.js build + tests) is being wired in alongside it, so a full pre-push run also includes `cd web && npm run build` when you have touched anything under `web/`. The individual targets are available separately:

```bash
make fmt           # ruff format (mutates files — run on the files you touched only)
make lint          # ruff check .
make typecheck     # pyright
make test          # pytest (asyncio_mode=auto, 10s per-test timeout)
```

`make fmt` reformats in place. To avoid dragging unrelated reformatting into your diff, format only the files you changed rather than running it across the whole tree.

## Pre-commit

Pre-commit is required and ships secret scanning (`gitleaks`, `detect-private-key`) plus the Python checks wired to the Make targets.

```bash
uv tool install pre-commit
pre-commit install
pre-commit run --all-files      # or: make precommit
```

## Commit style

This repo uses [Conventional Commits](https://www.conventionalcommits.org/) — `type(scope): subject`. Recent history (`git log --oneline`) is the canonical reference: `fix(api):`, `refactor(web):`, `docs(audit):`, `test(arc-015):`, `chore(ci):`. Reference the audit/arc finding id in parentheses when a change resolves one (e.g. `fix(security): ... (SEC-101)`).

## Branches and pull requests

- Trunk-based on `main`. Cut a feature branch per unit of work (`fix/...`, `feat/...`, `refactor/...`).
- Keep PRs focused; one logical change per PR makes review faster.
- Before merging a branch, rebase it onto the latest `main` so the merge is a clean fast-forward.
- Every changed line should trace to the PR's stated goal — avoid drive-by edits in unrelated code.

## Design docs

Historical design specs and implementation plans live under `docs/superpowers/specs/` and `docs/superpowers/plans/` (one dated file per feature). `docs/ARCHITECTURE.md` is the implementation-depth reference; when you change a feature materially, cite the relevant spec in your PR description and note where the implementation has diverged.

## Help

- `CLAUDE.md` — toolchain, layered architecture, testing patterns, conventions.
- `docs/ARCHITECTURE.md` — implementation depth (beat pipeline, web surface, persistence).
- [`web/README.md`](./web/README.md) — frontend layout and data flow.
- [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md) — common runtime problems and fixes.
