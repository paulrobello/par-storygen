# Audit Remediation Report

> **Project**: par-storygen — AI-driven Textual TUI choose-your-own-adventure (+ FastAPI server `src/storygen_api/` + Next.js `web/`)
> **Audit Date**: 2026-07-16 (see `AUDIT.md`)
> **Remediation Date**: 2026-07-16
> **Severity Filter Applied**: `all` (all phases executed)
> **Base commit**: `a8f8c91` → **Head**: `33a3dd5` (branch `fix/audit-remediation`, 22 commits)

---

## Execution Summary

| Phase | Status | Agent | Issues Targeted | Resolved | Pre-resolved¹ | Partial | Manual/Deferred |
|-------|--------|-------|:--------------:|:--------:|:-------------:|:-------:|:---------------:|
| 1 — Critical Security | ✅ | fix-security (opus) | 4 | 4 | — | 0 | 0 |
| 2 — Critical Architecture | ✅ | fix-architecture (opus) | 5 | 5 | — | 0 | 0 |
| 3a — Security (remaining) | ✅ | fix-security (opus) | 7 | 5 | 2 | 0 | 0 |
| 3b — Architecture (remaining) | ✅ | fix-architecture (opus) | 12 | 8 | — | 3 | 1 |
| 3c — Code Quality (all) | ✅ | fix-code-quality (opus) | 10 | 8 | — | 2 | 0 |
| 3d — Documentation (all) | ✅ | fix-documentation (sonnet) | 21 | 12 | 6 | 2 | 1 |
| 4 — Verification | ✅ | orchestrator | — | — | — | — | — |

¹ *Pre-resolved* = verified already-done (by an earlier phase or by the pre-existing `a8f8c91` docs-sync commit); no code change needed.

**Overall**: of 59 audit issues — **42 fully resolved**, **8 verified already-done**, **7 partial** (safe subset done, remainder flagged for manual follow-up), **2 deferred/skipped** (1 external, 1 trivial). **Zero require urgent manual intervention**; the partials are long-term refactors the audit itself placed in backlog.

**Headline outcome**: the CI gate that was **red throughout the audit** (75 ruff + 5 pyright, QA-001) is now **green and read-only**. The unauthenticated, SSRF-exposed, non-functional web surface is now auth-gated, loopback-bound, SSRF-allowlisted, path-validated, rate-limited, and its WebSocket protocol actually matches the frontend contract — with 117 new tests (106 Python + 11 web) locking the behavior.

---

## Verification Results

| Check | Command | Result |
|-------|---------|--------|
| Build (web) | `cd web && npm run build` | ✅ Clean (all 7 routes) |
| Tests (Python) | `uv run pytest -q` | ✅ **886 passed** (was 769 at audit) |
| Tests (web) | `cd web && npm run test` | ✅ **11 passed** (vitest; was 0) |
| Lint | `uv run ruff check .` | ✅ **0 errors** (was 75) |
| Type Check | `uv run pyright src/ tests/` | ✅ **0 errors** (was 5) |
| Project gate | `make checkall` | ✅ Green (read-only after ARC-008) |

No regressions. The orchestrator independently re-ran every gate after each phase rather than trusting agent self-reports — which caught a class of test-file type/lint errors the Phase 2 and 3a agents had missed by scoping their checks to source files (those were all fixed in Phase 3c).

---

## Resolved Issues ✅

### Security (11)
- **[SEC-001]** No API auth → added bearer-token dependency (`src/storygen_api/security.py`: `verify_token`, `ws_authorize`, `RequireToken`) read from `STORYGEN_API_TOKEN`, fail-closed (503 / WS 4403) when unset, applied router-wide; `serve` default host → `127.0.0.1`.
- **[SEC-002]** SSRF + key-exfiltration chain → auth-gated `PUT /api/settings` (SEC-001) + provider base-URL allowlist (`validate_provider_base_url`) sanctioning only known provider hosts; private/link-local IP ranges rejected.
- **[SEC-003]** Path traversal → `_validate_game_id` (uuid) / `_validate_node_id` / `_validate_char_id` added to `storage/paths.py` (mirrors the existing `library_id` pattern), applied at every path builder.
- **[SEC-004]** Exception-string info leak → bare `except: raise HTTPException(500, str(exc))` replaced with `logger.exception(...)` + generic `{"detail":"internal error"}`; WS emits `{"type":"error","code":"internal_error","message":...}`. (This also performed the B904 sweep — 45 of QA-001's 75 errors.)
- **[SEC-005]** Plaintext `state.json` → `os.chmod(tmp, 0o600)` in `write_app_state` (now in `storage/app_state/io.py`).
- **[SEC-007]** No rate limiting → in-process sliding-window limiter (`src/storygen_api/rate_limit.py`, default 30/min/IP) on all cost-incurring endpoints; configurable via `STORYGEN_API_RATE_LIMIT`.
- **[SEC-008]** CORS permissiveness → `allow_methods`/`allow_headers` pinned to actual usage; origins configurable via `STORYGEN_API_ALLOWED_ORIGINS`; `web/src/lib/api.ts` reads `NEXT_PUBLIC_API_BASE`.
- **[SEC-009]** Export filename → `sanitize_title` applied to the `Content-Disposition` filename in `routers/games.py`.
- **[SEC-011]** WS origin/size → `ws_check_origin` allowlist + 64 KiB `receive_text` cap (close 1009) in `security.py` / `routers/ws.py`.
- **[SEC-006]** Default bind `0.0.0.0` → *pre-resolved by SEC-001* (host default is `127.0.0.1`); verified.
- **[SEC-010]** `node_audio_glob` injection → *pre-resolved by SEC-003* (`node_id` validated before glob interpolation); verified.

### Architecture (13)
- **[ARC-003]** Adapter duplication/divergence → extracted `src/storygen/runtime/adapters.py`; resolved the `result.usage` (property, correct) vs `result.usage()` (method, silently swallowed) divergence — `deps.py` was dropping usage tracking on every API-side call.
- **[ARC-002]** Zero API tests → added `test_api_deps.py`, `test_api_ws.py` (WS contract vs `ws-types.ts` schema), `test_api_full_flow.py` (integration), incl. auth tests.
- **[ARC-001]** WS protocol divergence → server now emits the TS contract's exact fields (`narration_delta.text`, `beat_committed.choices[]`, `image_committed`, `image_failed.error`, full `new_characters` cards, `error.message`).
- **[ARC-005]** `WizardFlow` in `screens/` → moved to `src/storygen/runtime/wizard_flow.py`; `screens/wizard.py` re-exports for back-compat; API router imports from `runtime/`.
- **[ARC-013]** `app_state.py` God module → split into `app_state/{defaults,models,io}.py` with back-compat `__init__.py` re-exporting all 76 public names.
- **[ARC-004]** Single-worker guard → `lifespan()` enforces `WEB_CONCURRENCY == 1` (fail-fast) + loud warning documenting the in-process state.
- **[ARC-006]** No CI → `.github/workflows/ci.yml` on push+PR: `python-gate` (`uv sync --extra api --dev`, `make checkall`) + `web-build` (`npm ci`, `npm run test`, `npm run build`).
- **[ARC-007]** WS input validation → `routers/ws.py` validates `from_node_id`/`choice_id` against the save before `pipeline.advance`.
- **[ARC-008]** `checkall` ran `fmt` → `checkall: lint typecheck test` (read-only); `fmt` kept separate.
- **[ARC-009]** Broadcast race → `WebSocketManager` snapshots `_connections` under an `asyncio.Lock`; `disconnect` is now async.
- **[ARC-010]** ARCHITECTURE.md web-surface → expanded to 7 subsections mirroring TUI depth (composition root, single-worker, WS contract, validation, auth/SSRF, config sources, frontend flow).
- **[ARC-014]** Floating deps → bounded `textual`, `pydantic-ai`, `openai` to `>=current,<MAJOR+1>`.
- **[ARC-016]** Hardcoded ports → `web/src/lib/config.ts` single source (`API_BASE`/`WS_BASE`); 8 files swept; server side via `STORYGEN_API_ALLOWED_ORIGINS`.

### Code Quality (8)
- **[QA-001]** Red gate → **0 ruff, 0 pyright**: `ruff --fix` (I001/F401/UP035), B008 per-file-ignore for `src/storygen_api/**` (FastAPI idiom), `presets.py` return types, and fixed 16 test-file pyright errors the prior phases had introduced (generator-fixture annotations, a real `ImageStatus` literal bug).
- **[QA-003]** No API/web tests → resolved via ARC-002 (Python) + ARC-015 (web).
- **[QA-004]/[QA-005]** Silent exception swallowing → `_logger.warning(..., exc_info=True)` at the 3 `pipeline.py` sites; helper extraction skipped as over-engineering.
- **[QA-007]** `_private` cross-module imports → renamed `images/_prompts.py`→`prompts.py`, `widgets/_image_util.py`→`image_util.py`, `widgets/_header_util.py`→`header_util.py`; 19 importers updated (`git mv` preserved history).
- **[QA-008]** `image_cost` shim footgun → deleted the divergent-signature shim + redundant pin tests; migrated one drift-guard test to `test_pricing.py`.
- **[QA-009]** Undocumented `# type: ignore` → documented 25 sites across `preset_picker.py`, `wizard.py`, `main.py` with `# pyright: ignore[code] - reason`.
- **[QA-010]** Minor → hoisted `_PACING_OPTIONS` to module level; import-sort folded into QA-001.

### Documentation (12 resolved + 6 verified-already-done)
- **Resolved**: DOC-001 (README Web API section), DOC-002/012 (web/README replaced), DOC-004/010 (host default + arch depth), DOC-009 (CLAUDE.md API/web), DOC-013 (web/AGENTS + CLAUDE), DOC-015 (root AGENTS.md H1), DOC-016 (hotkeys — verified against actual `BINDINGS`, corrected the audit's stale premise), DOC-017 (.env.example TTS keys), DOC-018 (design-docs index), DOC-019 (CI badge).
- **Verified already-done** (by `a8f8c91`): DOC-003 (image-default `gpt-image-2`), DOC-005 (v0.4.0 features), DOC-006 (TOC anchors), DOC-007 (CORS comment), DOC-008 (`Ctrl+L`), DOC-011 (FastAPI version).

---

## Requires Manual Intervention 🔧

These could not be safely completed in an automated pass. They are **long-term backlog** items (the audit's own roadmap defers them), not blockers. The green gate is unaffected.

### [ARC-011] `pipeline.py` — `PrefetchCoordinator` extraction (Partial)
- **Done**: pure prompt helpers extracted to `pipeline_prompts.py` (pipeline.py 1077→973 LOC).
- **Why deferred**: prefetch lifecycle is tightly coupled to `BeatPipeline`'s instance state (`_prefetch_tasks`/`_prefetch_failure_logged`/`_prefetch_semaphore`) and `advance()`'s cache-hit path — not a clean, obviously-safe move.
- **Recommended approach**: a dedicated follow-up that either passes the private fields into a coordinator or does a larger responsibility split, with integration-test coverage first.
- **Estimated effort**: medium.

### [ARC-012 / QA-002 / QA-006] God screens + complexity (Partial)
- **Done**: dispatch-table refactors for `wizard._advance_worker` (cc 34→low) and `play.check_action` (cc 31→low) — behavior-preserving, all screen tests green.
- **Why deferred**: `settings._save_settings` is a linear validation pipeline (not a dispatch candidate — needs a validator-list pattern); `portraits.on_button_pressed` couples to widget identity + per-character state in ways that resist mechanical extraction.
- **Recommended approach**: dedicated follow-up per screen with integration-test coverage before decomposing; consider per-section controller classes.
- **Estimated effort**: large.

### [ARC-015] Playwright e2e (Partial)
- **Done**: vitest + jsdom layer (config + `useWebSocket` contract, 11 tests).
- **Why deferred**: an end-to-end Playwright test requires a running `api-dev`/`web-dev` pair and browser download — heavier setup.
- **Estimated effort**: small-medium.

### [DOC-014] `storygen_api` module docstrings — routers/ws/main (Partial)
- **Done**: docstrings added to `deps.py`, `session.py`, `schemas.py` (the files the Documentation agent owned).
- **Why deferred**: the router/ws/main files were owned by the Security agent in the same round; they still lack one-line module docstrings.
- **Recommended approach**: a quick follow-up sweep adding one-line docstrings to `routers/*.py`, `ws.py`, `main.py`.
- **Estimated effort**: small.

### [DOC-020] `pipeline.py` headline-symbol docstrings (Partial)
- **Done**: `StoryGenApp` class docstring.
- **Why deferred**: `pipeline.run`/`generate_portrait`/`generate_scene` live in `pipeline.py`, which other agents owned during the doc round.
- **Estimated effort**: small.

### [DOC-021] `pyproject.toml` Documentation URL (Deferred)
- **Why deferred**: `pyproject.toml` was owned by other agents in-round.
- **Recommended approach**: repoint `[project.urls] Documentation` at a docs index (or leave as README). Trivial.
- **Estimated effort**: trivial.

### [ARC-017] par-mem friction (Skipped — external)
- Already filed to `~/Repos/PAR-MEM-FEEDBACK.md` by the audit's architecture agent. No project code change.

### Incidental observation (not an audit item)
- `web/src/components/story/AudioPlayer.tsx` imports `Volume2`/`VolumeX` from `lucide-react` but never uses them. **Pre-existing** (the ARC-016 sweep only added the `@/lib/config` import; it did not touch these). Flagged per surgical-change discipline; not deleted.

---

## Files Changed

**100 files** across 22 commits (+7,997 / −1,845): **25 created, 70 modified, 1 deleted, 4 renamed.**

Notable new modules/files:
- `src/storygen/runtime/{__init__,adapters,wizard_flow}.py` — shared headless layer (ARC-003/005)
- `src/storygen/storage/app_state/{__init__,defaults,models,io}.py` — split God module (ARC-013)
- `src/storygen/pipeline_prompts.py` — extracted pure helpers (ARC-011)
- `src/storygen_api/{security,rate_limit}.py` — auth + SSRF + rate limiting (SEC-001/002/007)
- `tests/unit/test_api_{deps,ws,security,rate_limit,main}.py`, `tests/integration/test_api_full_flow.py`, `tests/integration/_stub_pipeline.py` — new API/WS test layer (ARC-002)
- `.github/workflows/ci.yml` — push/PR gate (ARC-006)
- `web/src/lib/config.ts`, `web/vitest.{config,setup}.ts`, `web/src/{lib/config,hooks/useWebSocket}.test.ts` — web config + tests (ARC-015/016)

Full commit list (`a8f8c91..33a3dd5`): see `git log --oneline a8f8c91..HEAD`.

---

## Next Steps

1. **Review the Partial/Manual items above** and assign the backlog refactors (ARC-011 PrefetchCoordinator, ARC-012 screen decomposition, DOC-014/020/021) — none are blockers.
2. **Sweep `DOC-014` docstrings** into the `routers/`/`ws.py`/`main.py` files (small, quick).
3. **Re-run `/audit`** to regenerate `AUDIT.md` against the remediated state — it should now show the Critical/High security + architecture findings cleared and the gate green.
4. **Decide on the security-config rollout**: the API now requires `STORYGEN_API_TOKEN` (fail-closed) and defaults to `127.0.0.1`. Operators exposing it beyond loopback must set the token and an allowed-origin/SSRF config. Documented in README + ARCHITECTURE.md.
5. *(Wrap-up, on confirmation)* Update CHANGELOG, then merge `fix/audit-remediation` to `main` (rebased) and delete `AUDIT.md` + this file.
