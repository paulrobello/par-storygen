# par-storygen Agent Guide

Agent-oriented orientation for the par-storygen repository. Read `CLAUDE.md` next — it carries the authoritative project guidance (toolchain, layered architecture, testing patterns, conventions).

The repository ships three surfaces that share the `storage` / `llm` / `images` / `pipeline` layers:

- **TUI** (`src/storygen/`) — the primary Textual choose-your-own-adventure app (`uv run storygen`).
- **FastAPI server** (`src/storygen_api/`, optional `[api]` extra; `uv run storygen-api serve`) — a second composition root exposing the wizard + play loop over REST + WebSocket on `:8101`.
- **Next.js frontend** (`web/`) — drives the API from the browser on `:8100`.

Before non-trivial work, consult `docs/ARCHITECTURE.md` (implementation depth), `docs/DOCUMENTATION_STYLE_GUIDE.md` (prose conventions), and `AUDIT.md` (known findings).

read @CLAUDE.md
