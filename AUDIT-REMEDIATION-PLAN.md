# Audit Remediation Playbook

> **Companion to**: `AUDIT.md` (2026-07-16, index @ b30f26c)
> **Consumer**: `/fix-audit` agents (any model). Every entry is written to be executable
> without re-deriving the analysis — read the entry, make the edits, run the Verify commands.
> **Ordering**: entries appear in Remediation Plan phase order (Phase 1 → 2 → 3a → 3b → 3c → 3d).
> **Ground rules for all entries**:
> - Re-`Read` every file before editing — a prior phase may have changed it (see the File Conflict Map in AUDIT.md).
> - The authoritative Python gate is `make checkall` (ruff + pyright strict + 908 tests). Run it after every entry that touches Python.
> - Web checks: `cd web && npm run lint && npm run test && npx tsc --noEmit`.
> - par-mem is indexed (repo_id `par-storygen`). For multi-site changes, enumerate callers with
>   `get_symbol_context` / `get_impact` on the symbol before editing, and re-Read files for current line numbers (the index lags edits).
> - **Never auto-generate or replace auth tokens/secrets** (repo security policy). Security fixes are opt-in and preserve existing configuration.

---

## Phase 1 — Critical Security (sequential, first)

### [SEC-101] Remove/gate the unauthenticated `games_root` static mount
- **Files**: `src/storygen_api/main.py:117-124`; read-only reference: `src/storygen_api/routers/images.py`, `src/storygen_api/routers/tts.py`, `web/src/stores/game-store.ts`, `web/src/lib/api.ts`
- **Steps**:
  1. Read `src/storygen_api/main.py` and locate the `app.mount("/api/images", StaticFiles(directory=str(games_root())), ...)` call (~line 117-124).
  2. Enumerate every URL the frontend builds under `/api/images/`: `rg -n "api/images" web/src`. Expected hits: the scene URL `` `${API_BASE}/api/images/${gameId}/scene/${nodeId}` `` (5× in `game-store.ts`, 1× in `useWebSocket.ts`) and portrait URLs in `api.ts`. Confirm each corresponds to a **router** route (`rg -n "@router.get" src/storygen_api/routers/images.py src/storygen_api/routers/tts.py`).
  3. If every frontend URL maps to a router route (expected): **delete the `app.mount(...)` call** and the now-unused `StaticFiles` import (and `games_root` import if unused elsewhere in `main.py`). Do not add a replacement.
  4. If any frontend URL has no router route (e.g. a raw static path for reference images): add a token-gated router endpoint for that specific asset type in `routers/images.py` following the existing pattern (`dependencies=[Depends(verify_token)]`, `safe_join` for path containment, correct media type) — never re-mount a directory that contains `game.json` or `llm/`.
  5. Check `tests/unit/` for tests that exercise the static mount (`rg -n "StaticFiles|/api/images" tests/`) and update/remove any that asserted unauthenticated static serving. Add a regression test: request `/api/images/<game_id>/game.json` (use the xdg_tmp fixture + a saved game) and assert 404 (mount gone) — not 200.
- **Method**: The routers already serve every asset the frontend needs, each behind `verify_token`; the mount is a redundant side-door whose directory root is the parent of all save data. Deleting it is the smallest correct fix. Pitfall: don't "fix" by adding `verify_token` to the mount via middleware — Starlette mounts bypass FastAPI dependencies, which is exactly how this bug happened; a sub-app wrapper is possible but unnecessary here. Pitfall 2: the scene/portrait routes in `game-store.ts` look like static paths but are router routes — verify before assuming the frontend breaks.
- **Verify**: `make checkall` && `uv run pytest tests/unit/test_api_images.py tests/unit/test_api_security.py -q` (adjust names to what exists: `ls tests/unit/ | grep api`). Manual check: start `make api-dev`, create/load a game, confirm `curl -s http://127.0.0.1:8101/api/images/<game_id>/game.json` returns 404, while the scene route still serves with a valid token.

### [SEC-102] Web client bearer-token plumbing (opt-in)
- **Files**: `web/src/lib/config.ts`, `web/src/lib/api.ts:255-293`, `web/src/hooks/useWebSocket.ts:26`; read-only reference: `src/storygen_api/routers/ws.py:55-70` (subprotocol format), `src/storygen_api/security.py`
- **Steps**:
  1. Read `src/storygen_api/routers/ws.py` lines ~55-70 and confirm the exact accepted subprotocol format (audit found `Sec-WebSocket-Protocol: bearer.<token>`). Read `security.py:verify_token` to confirm the REST header form (`Authorization: Bearer <token>`).
  2. In `web/src/lib/config.ts`, add alongside the existing `API_BASE` export:
     `export const API_TOKEN: string = process.env.NEXT_PUBLIC_API_TOKEN ?? "";`
     with a comment that it is optional and only needed when the server sets `STORYGEN_API_TOKEN`.
  3. In `web/src/lib/api.ts`, find the shared fetch wrappers (~lines 255-293). Add a helper `function authHeaders(): Record<string, string> { return API_TOKEN ? { Authorization: \`Bearer ${API_TOKEN}\` } : {}; }` and spread it into the headers of **every** wrapper (GET/POST/PUT/DELETE — enumerate them all; do not miss the ones that only set `Content-Type`).
  4. In `web/src/hooks/useWebSocket.ts` (~line 26), change `new WebSocket(url)` to pass the subprotocol when a token exists: `new WebSocket(url, API_TOKEN ? [\`bearer.${API_TOKEN}\`] : [])` — check whether the browser accepts an empty array; if not, use a conditional: `API_TOKEN ? new WebSocket(url, [\`bearer.${API_TOKEN}\`]) : new WebSocket(url)`.
  5. Update `web/.env.example` (create if missing) documenting `NEXT_PUBLIC_API_BASE` and `NEXT_PUBLIC_API_TOKEN`. Do NOT put a real token anywhere; placeholder only.
  6. Add a vitest for `authHeaders()`/config behavior (token set vs unset) following `web/src/lib/config.test.ts` patterns.
  7. Note in the commit/report: **flag for manual security review** — `NEXT_PUBLIC_*` vars are embedded in the client bundle; this is acceptable for a self-hosted single-user deployment but must be called out.
- **Method**: The server contract already exists (SEC-001 built both header and subprotocol paths); this is pure client plumbing. Token absent ⇒ behavior identical to today (loopback-trust mode) — the change is strictly opt-in, satisfying the security policy. Pitfall: browsers cannot set arbitrary headers on WebSocket handshakes — the subprotocol vehicle is mandatory for WS, don't try `Authorization` there. Pitfall 2: when the server accepts the `bearer.<token>` subprotocol it echoes the selected subprotocol; the client `WebSocket` will fail if the server doesn't select one it offered — hence only offering the subprotocol when a token is configured.
- **Verify**: `cd web && npm run lint && npm run test && npx tsc --noEmit`. Manual: run `STORYGEN_API_TOKEN=testtok make api-dev` + `NEXT_PUBLIC_API_TOKEN=testtok make web-dev`, load a game page, confirm REST 200s and the WS connects (server log shows accepted handshake); then unset both and confirm loopback dev still works.

---

## Phase 2 — Critical Architecture (sequential, after Phase 1)

> ARC-101, ARC-102, and ARC-106 are **one designed change**: the session manager becomes the single
> owner of the live `GameSave`, with a per-game async lock. Implement them together in the order below.
> ARC-103 rides along (same file, `deps.py`). ARC-105 and ARC-111 are independent mechanical sweeps
> promoted into this phase because later phases conflict with them.

### [ARC-101] Fix stale-save closure aliasing (usage/cost loss) — via single-owner save
- **Files**: `src/storygen_api/session.py`, `src/storygen_api/deps.py:38-88`, `src/storygen_api/routers/games.py:180-226`, `src/storygen_api/routers/ws.py:133-214`, `src/storygen_api/routers/images.py` (save-loading call sites), `src/storygen_api/routers/tts.py` + `characters.py` if they `load_game` for a session-active game
- **Steps**:
  1. **session.py — make the manager the save owner.** Add to `PipelineSessionManager`:
     - `import asyncio` at top.
     - `self._advance_locks: dict[str, asyncio.Lock] = {}` in `__init__`.
     - Method `advance_lock(self, game_id: str) -> asyncio.Lock`: under `self._lock`, `setdefault(game_id, asyncio.Lock())` and return it.
     - Method `get_or_load_save(self, game_id: str) -> GameSave`: under `self._lock`, return `self._saves[game_id]` if present; otherwise call `storygen.storage.save.load_game(game_id)` (import at top; it may raise `FileNotFoundError` — let it propagate), store it in `self._saves`, and return it. This is now the **only** sanctioned way routers obtain a save for a session-active game.
     - Keep `update_save` (it becomes a no-op re-registration in most paths but harmless); `cleanup` must also pop `self._advance_locks`.
  2. **games.py `advance_game`** (~lines 180-226): replace the `load_game(game_id)` call with `save = mgr.get_or_load_save(game_id)` (map `FileNotFoundError` → 404 as today). Wrap the pipeline-resolution + `pipeline.advance(save, ...)` + response construction in `async with mgr.advance_lock(game_id):`. Delete the post-advance `save = load_game(game_id)` reload (~line 219) — compute `new_char_ids` from the same in-memory `save` (the pipeline mutated it). Delete the now-redundant `mgr.update_save(game_id, save)` calls (lines ~199, 216) or keep the first as registration — prefer deleting both since `get_or_load_save` registers.
  3. **ws.py advance branch** (~lines 146-200): same substitution — `save = mgr.get_or_load_save(game_id)` instead of `load_game`, wrap validate+advance in `async with mgr.advance_lock(game_id):`, drop `mgr.update_save` calls.
  4. **Why this fixes ARC-101**: `build_pipeline`'s `_on_usage` closure (deps.py:54-56) captures the save passed at construction. With `get_or_load_save`, the save passed at construction and the save passed to every subsequent `pipeline.advance` are **the same object**, so `record_usage_on_save(save, ...)` + `save_game(save)` mutate/persist current state. No adapter signature change needed.
  5. **Other routers**: `rg -n "load_game\(" src/storygen_api/routers/`. For each mutating route on a possibly-session-active game (scene edit/retry in `images.py`, character import in `characters.py`, etc.): replace `load_game` with `mgr.get_or_load_save(game_id)` (add the `mgr: PipelineSessionManager = Depends(get_session_manager)` dependency where missing) so their mutations land on the owned object, and keep their existing `save_game(...)` persistence. Read-only routes (`get_game`, `list_games`) may keep `load_game` — fresh disk reads are safe (though `get_game` on a session-active game ideally also uses the owned save for consistency; do it if low-effort).
  6. Update the `session.py` module docstring to state the new ownership contract: "the manager owns the single in-memory GameSave per active game; routers must use get_or_load_save".
- **Method**: The root cause is two `GameSave` instances aliasing one game. Making the manager the single owner is the fix the architecture audit recommends because it simultaneously kills ARC-101 (aliasing), gives ARC-102 a natural lock home, and makes `_saves` real (ARC-106). Pitfalls: (a) `asyncio.Lock` must be created lazily under the thread lock — creating it in a route handler without the registry risks two locks for one game; (b) do NOT hold the `threading.Lock` across `await` — the thread lock guards dict access only, the asyncio lock guards the advance critical section; (c) the pipeline `advance` already persists via `save_game` internally — do not add extra `save_game` calls in the router; (d) tests that monkeypatch `load_game` in router modules may need the patch target moved to `session.py`.
- **Verify**: `make checkall`. Targeted: `uv run pytest tests/unit -k "api" -q`. Add a regression test: build a pipeline via `deps.build_pipeline`, advance twice through the API path (Fake agents per `test_pipeline.py` patterns), and assert `save.text_total_requests` reflects **both** advances in the persisted `game.json`.

### [ARC-102] Per-game serialization of advance (REST + WS)
- **Files**: same as ARC-101 (implemented by ARC-101 steps 1–3: `advance_lock` + `async with` in both paths)
- **Steps**: Covered by ARC-101. Additionally: add a concurrency regression test — `asyncio.gather` two `pipeline.advance`-via-route calls for the same game (httpx `AsyncClient` + Fake agents with an `asyncio.sleep` inside the beat agent to force overlap) and assert both children exist in the final save tree and the second call waited (no lost node).
- **Method**: The lock must span load→advance→persist, which is why it lives in the manager and not inside `BeatPipeline` (the TUI serializes via UI state and must not pay for a lock it doesn't need). Pitfall: don't use `threading.Lock` for this — the handlers are async and would deadlock the event loop.
- **Verify**: `make checkall`; the new concurrency test passes.

### [ARC-106] Session registry: make `_saves` real, add idle eviction
- **Files**: `src/storygen_api/session.py`; `src/storygen_api/main.py` (lifespan, only if adding the eviction task)
- **Steps**:
  1. Steps 1 and 5 of ARC-101 already make `_saves` the source of truth. Confirm `get_save` now has consumers (`get_or_load_save` internally); if the separate public `get_save` remains unused after the router sweep, delete it.
  2. Idle eviction (bounded scope): add `self._last_used: dict[str, float] = {}` stamped (`time.monotonic()`) in `get_or_load_save`/`get_pipeline`; add method `async def evict_idle(self, max_idle_seconds: float = 1800.0) -> list[str]` that collects idle game_ids under the thread lock, then `await self.cleanup(gid)` for each (cleanup persists nothing — saves are already write-through via `save_game`; it cancels prefetches). Wire a background task in `main.py`'s lifespan: `asyncio.create_task` of a loop calling `evict_idle()` every 5 minutes; cancel it on shutdown. If the lifespan wiring feels risky, ship the method + a unit test and leave the loop wiring as a documented TODO in the lifespan with the method ready — the memory leak is slow.
  3. Docstring: note eviction semantics (an evicted game transparently re-opens via `get_or_load_save` on next request).
- **Method**: Eviction must go through `cleanup` so prefetch tasks are cancelled — plain dict-pops leak running tasks. Pitfall: don't evict while an advance lock is held; check `self._advance_locks[gid].locked()` and skip those games.
- **Verify**: `make checkall`; unit test: register a game, advance `_last_used` into the past, call `evict_idle`, assert pipeline/save/lock maps are empty and a subsequent `get_or_load_save` reloads from disk.

### [ARC-103] Invalidate `get_app_config` cache on settings update
- **Files**: `src/storygen_api/routers/settings.py` (`update_settings`, ~line 104+), `src/storygen_api/deps.py:121-124` (read-only)
- **Steps**:
  1. Read `update_settings` fully. After the state is persisted (the final write / before constructing the response), add:
     `from storygen_api.deps import get_app_config` (module-level import) and `get_app_config.cache_clear()`.
  2. Mirror the comment style used in `security.py` for its `_expected_token.cache_clear()` (cite ARC-103).
  3. Add a regression test: call the settings update route (or `update_settings` directly with a stubbed request) after seeding config, then assert `get_app_config()` returns the new values (monkeypatch `load_config` to count calls / return sentinel values).
- **Method**: Smallest correct fix; the alternative (dropping the cache) changes per-request cost for every route and isn't needed. Pitfall: import at module level, not inside the function (repo convention; QA-012 flags in-function imports as a smell).
- **Verify**: `make checkall`; `uv run pytest tests/unit -k "settings and api" -q`.

### [ARC-105] Retire the `llm/models.py` shim — sweep 23 importers to `core.models`
- **Files**: all modules matching `rg -l "from storygen.llm.models import|from storygen.llm import models|import storygen.llm.models" src/ tests/` (audit counted 23 under `src/`, incl. `src/storygen/storage/tree.py:7`, `src/storygen/config.py:19`, API routers); `src/storygen/llm/models.py` (the shim)
- **Steps**:
  1. Read `src/storygen/llm/models.py` to confirm it is a pure re-export of `storygen.core.models` and note the exact re-exported names.
  2. Enumerate importers with the rg above **and** with par-mem: `get_symbol_context` on the shim module / `find_symbol` for each re-exported name to catch aliased imports. Also check string references: `rg -n "llm\.models" src/ tests/ docs/`.
  3. Mechanical rewrite: change each `from storygen.llm.models import X` to `from storygen.core.models import X` (preserve import ordering — ruff's isort will enforce).
  4. Delete `src/storygen/llm/models.py`. If anything external could import it (it's a published package), instead reduce it to a 3-line deprecation stub re-exporting from core with a module docstring saying "deprecated shim; import from storygen.core.models". Prefer deletion — the package's public API is the CLI, not the module tree; check `rg -n "llm.models" README.md docs/` first.
  5. Run the gate; pyright strict will catch any missed name.
- **Method**: Import-line-only change; zero behavior. This runs early because later entries (QA-012, ARC-109) edit the same files and would conflict with a bulk import sweep. Pitfall: don't "improve" other imports while in each file — the diff must stay mechanical (per repo §3 surgical-changes rule).
- **Verify**: `make checkall` (pyright is the real check); `rg -n "llm\.models" src/ tests/` returns nothing (or only the stub).

### [ARC-111] Makefile: fresh-checkout build must install API extra + dev deps
- **Files**: `Makefile:20-24`
- **Steps**:
  1. Change both `build:` and `setup:` recipes from `uv sync` to `uv sync --extra api --dev`.
  2. Compare against CI (`rg -n "uv sync" .github/workflows/`) and match its flags exactly.
- **Method**: `uv sync` prunes extras, and `tests/unit/test_api_*.py` hard-import fastapi — so a fresh `make build && make checkall` fails at collection. Aligning the Makefile with CI is smaller and safer than adding `importorskip` guards to every API test (which would silently skip real coverage). QA-004 (web gate) builds on this and lands separately, last.
- **Verify**: `uv sync` (prune to bare), then `make build && make checkall` — must pass from the pruned state.

---

## Phase 3a — Security (remaining)

### [SEC-103] Rate-limit the WebSocket `advance` path — after ARC-101/102
- **Files**: `src/storygen_api/routers/ws.py` (advance branch, post-ARC-101 line numbers will have shifted — re-read), `src/storygen_api/rate_limit.py` (read-only)
- **Steps**:
  1. Read `rate_limit.py` and identify the module-level limiter instance and its check API (audit: `_limiter.check(...)` keyed by client host; confirm the actual name/signature).
  2. In the WS advance branch, before acquiring the advance lock / calling `pipeline.advance`, call the limiter with `ws.client.host` (guard `ws.client is None` → treat as unknown, use `"unknown"`). On over-quota, `await ws.send_json({"type": "error", "code": "rate_limited", "message": "rate limit exceeded"})` and `continue` (do not close the socket).
  3. If the limiter's check is only exposed as a FastAPI dependency, refactor `rate_limit.py` minimally: extract the core check into a plain function/method the dependency wraps, so WS can call it without HTTP machinery.
  4. Add the `rate_limited` error code to `web/src/lib/ws-types.ts` if error codes are enumerated there, and to the WS contract test (`tests/unit/test_api_ws.py`) + a unit test that the Nth advance frame gets `rate_limited`.
- **Method**: The limiter exists and is sized for LLM/image cost (SEC-007); this closes the socket-shaped hole. Pitfall: run the check per `advance` **frame**, not per connection; and don't count `ping` frames.
- **Verify**: `make checkall`; `uv run pytest tests/unit/test_api_ws.py tests/unit -k "rate" -q`.

### [SEC-104] Gate `/api/presets` behind `verify_token`
- **Files**: `src/storygen_api/routers/presets.py:11`
- **Steps**: Read the file; add `dependencies=[Depends(verify_token)]` to the `APIRouter(...)` constructor, matching the exact idiom used in `routers/games.py`. Add/extend the auth test to cover a presets route (copy the pattern in the existing security tests).
- **Method**: Parity fix; presets can contain personal theme text. Pitfall: import `verify_token` from the same module the other routers use (`storygen_api.security`), and `Depends` from fastapi.
- **Verify**: `make checkall`; auth test asserts 401 with bad token when token configured, 200 on loopback when unset.

### [SEC-105] Sanitize the preset-name slug in `save_custom_preset`
- **Files**: `src/storygen/core/presets.py` (~line 75), `src/storygen/storage/paths.py` (read-only — copy its pattern)
- **Steps**:
  1. Read both files. In `save_custom_preset`, replace `slug = preset.name.lower().replace(" ", "_")[:48]` with a sanitizer that keeps only `[a-z0-9_.-]`: e.g. `slug = re.sub(r"[^a-z0-9_.-]", "_", preset.name.lower().replace(" ", "_"))[:48]`, then reject/replace empty or dot-only results (fallback `"preset"`), and strip leading `-`/`.` (match `paths.py`'s rules).
  2. Confirm load/delete round-trips still work if they look files up by slug (read the rest of the module; if delete recomputes the slug from the name, both sides now agree).
  3. Unit test: a preset named `../evil` saves inside the presets dir with a sanitized filename.
- **Method**: TUI-local hardening; reuse the existing character-class convention rather than inventing a new one. Pitfall: don't reuse `paths._validate_*` (they reject rather than sanitize; here we want sanitize-and-accept since the name is user-facing display text).
- **Verify**: `make checkall`; the new unit test passes.

### [SEC-106] Document the rate limiter's direct-binding assumption
- **Files**: `src/storygen_api/rate_limit.py:162-165` (module docstring), `docs/ARCHITECTURE.md` (deploy notes), `README.md` Web API section
- **Steps**: Add 2–3 sentences to the `rate_limit.py` module docstring and the ARCHITECTURE deploy section: the limiter keys on the direct peer address and deliberately ignores `X-Forwarded-For` (spoofable); behind a reverse proxy all clients share one bucket — bind directly or accept a global limit. Do not implement trusted-proxy parsing.
- **Method**: Documentation-only by design; parsing forwarded headers safely needs a trusted-proxy config that this deployment model doesn't warrant.
- **Verify**: `make checkall` (docs don't break it); prose review.

### [SEC-107] Set CORS `allow_credentials=False`
- **Files**: `src/storygen_api/main.py:99-105`
- **Steps**: Read the CORS middleware block; change `allow_credentials=True` → `False`. Confirm nothing uses cookies: `rg -n "cookie|withCredentials|credentials:" src/storygen_api web/src` (the WS token rides the subprotocol; REST rides the Authorization header, which is an allowed header not a credential in the cookie sense — confirm `allow_headers` still includes `Authorization` or `*`).
- **Method**: Header-based auth doesn't need credentialed CORS; narrowing is free. Pitfall: `Authorization` must remain in `allow_headers` after SEC-102, or preflights will fail — test with the token configured.
- **Verify**: `make checkall`; manual: with token set, web dev server calls succeed (preflight OK).

---

## Phase 3b — Architecture (remaining)

### [ARC-107] TTS: per-request player (or configure-and-generate lock)
- **Files**: `src/storygen_api/routers/tts.py:22-31` and the routes that call `_configure_player`
- **Steps**:
  1. Read the whole router + `storygen.tts.player.TTSPlayer`'s constructor cost (it wraps `par_tts`; check whether construction is cheap — no network at init).
  2. Preferred: replace the module-level `_player` + `_configure_player()` with a factory `def _build_player(prefs) -> TTSPlayer` called inside each request handler; delete the module global.
  3. If construction is provably expensive (lazy client caching inside providers), instead add `_player_lock = asyncio.Lock()` and hold it across configure+generate in every route that touches the shared player.
  4. Check for state the player caches per game (audio file paths) — caching is on disk per the docstring, so per-request players don't lose the cache.
- **Method**: The 4-state machine assumes one consumer; per-request instances eliminate the race class instead of managing it. Pitfall: if any route exposes stop/status semantics tied to the shared instance (streaming playback), those routes need the singleton — read all routes first; only `generate`-style routes get per-request players.
- **Verify**: `make checkall`; `uv run pytest tests/unit -k "tts" -q`.

### [ARC-108] REST contract drift guard (OpenAPI snapshot)
- **Files**: new `tests/unit/test_api_openapi_snapshot.py`, new committed snapshot `tests/unit/data/openapi.json` (or similar existing data dir), `web/src/lib/api.ts` (no change this entry)
- **Steps**:
  1. Minimal-footprint option (do this one): write a pytest that builds the app (`from storygen_api.main import app`), computes `app.openapi()`, normalizes (sort keys, drop volatile fields like `info.version` if it tracks package version), and diffs against the committed JSON snapshot; on mismatch, fail with instructions: "REST contract changed — regenerate the snapshot (`uv run python -m tests.unit.regen_openapi` or documented one-liner) and update `web/src/lib/api.ts` to match."
  2. Provide the regeneration path: a tiny script or `pytest --snapshot-update`-style env check (`STORYGEN_UPDATE_OPENAPI=1 uv run pytest ...` writing the file). Keep it dependency-free.
  3. Generate the initial snapshot and commit it with the test.
- **Method**: This is the ARC-001 (WS mirror test) approach extended to REST — it doesn't force an `openapi-typescript` toolchain into the build, but makes drift fail CI loudly. Full codegen can be a later enhancement (see ENH backlog). Pitfall: normalize the snapshot deterministically (json.dumps sort_keys, stable route ordering) or the test flakes on dict ordering.
- **Verify**: `make checkall`; deliberately rename a schema field locally → test fails → revert.

### [ARC-109] Move game-listing schema knowledge into the storage layer
- **Files**: `src/storygen/storage/save.py` (new function), `src/storygen_api/routers/games.py:74-143`
- **Steps**:
  1. Read `games.py:list_games` fully; inventory the summary fields it extracts (id, title, node count, updated_at, etc.).
  2. In `storage/save.py`, add `def load_game_summary(game_id: str) -> GameSummaryData | None` (a small dataclass/TypedDict in `save.py`, NOT a pydantic API schema) — implement by full `load_game` (correct, migration-aware) unless profiling shows listing is hot; note in the docstring that partial parsing is a permitted future optimization.
  3. Add `def list_game_summaries() -> list[GameSummaryData]` iterating `games_root()` dirs, skipping unparseable saves with a `logger.warning` (not silent `continue`).
  4. Rewrite the router's `list_games` to map `list_game_summaries()` → API `GameSummary` schema; delete the hand-parsing block.
  5. Check the TUI load screen (`src/storygen/screens/load.py`) for its own listing logic; if it duplicates the same extraction, migrate it to the new function too (it's the second consumer that justifies the placement).
- **Method**: Single source of schema knowledge, migrations always applied. Pitfall: the router previously tolerated corrupt saves by skipping — keep that behavior but logged; don't let one bad save 500 the listing. Runs after Phase 2 because `games.py` is rewritten there.
- **Verify**: `make checkall`; `uv run pytest tests/unit -k "list_games or load" -q`; manual: `curl http://127.0.0.1:8101/api/games` lists an existing save.

### [ARC-110] Decompose `BeatPipeline.advance` (fold in ARC-112 + QA-019)
- **Files**: `src/storygen/pipeline.py:188-393` (advance), `:707+` (`_render_scene`, for QA-019 context), `:859-861` (bottom import, ARC-112)
- **Steps**:
  1. Re-read the whole file first. Extract two private methods from `advance`, preserving the existing docstring's stage narrative:
     - `_merge_new_characters(self, save, beat, new_node_id) -> None` (block ~297-309: character introduction + relationship merge).
     - `_maybe_generate_summary(self, save, beat, new_node_id) -> None` (block ~356-392: summary trigger + persistence). Keep it `async` if the block awaits.
  2. Keep the prefetch fast-path and cache-hit returns inline (they carry the concurrency contract; the docstring says so).
  3. ARC-112: move the bottom-of-file `import ... pipeline_prompts  # noqa: E402` (~859-861) to the top import block; delete the noqa; run ruff to confirm no cycle (there is none — `pipeline_prompts` imports only core/storage).
  4. QA-019: in `_render_scene` (~lines 750, 760 pre-edit), the `except ValueError` blocks that skip reference images silently — add `logger.debug("skipping scene reference %s: %s", <path/char>, exc)` inside each (find the module's existing logger; add one if absent following repo style).
  5. Do NOT change the `skip_image`/`suppress_side_effects` flags to an enum in this pass (noted as optional in the audit; it changes call sites in prefetch + tests — out of scope for a mechanical decomposition).
- **Method**: Pure extract-method; behavior-identical. The 111-assertion `test_pipeline.py` suite is the safety net — if any assertion fails, the extraction changed behavior; fix the extraction, never the test. Pitfall: the extracted blocks reference many locals — pass them as parameters rather than promoting to attributes; keep `save` first-positional to match repo idiom.
- **Verify**: `make checkall`; specifically `uv run pytest tests/unit/test_pipeline.py -q` must stay 100% green with zero test edits.

### [ARC-113] Remove `deps.py` back-compat cruft
- **Files**: `src/storygen_api/deps.py:104-113` (post-Phase-2 line numbers shift — re-read), `src/storygen_api/routers/images.py` (call sites)
- **Steps**: `rg -n "build_split_image_provider" src/` — update every call site to `build_split_provider_for_save(save)` (imported from `storygen.runtime.adapters`), then delete the alias function. Also delete the `_ = config` back-compat parameter in `build_pipeline` **if** Phase 2 didn't already: check every `build_pipeline(` call site and drop the `config` argument from the signature and calls.
- **Method**: Single-repo YAGNI cleanup. Runs after Phase 2 (same file). Pitfall: pyright will catch missed call sites; trust the gate.
- **Verify**: `make checkall`.

### [ARC-115] Add `supports_reference_images` to the `ImageProvider` protocol
- **Files**: `src/storygen/images/base.py`, all providers (`openai_provider.py`, `gemini_provider.py`, `zai_provider.py`, `ollama_provider.py`, `routed_provider.py`, `split_provider.py`), call sites that currently special-case ref support (`rg -n "ref_loss|on_ref_loss|reference_portraits" src/`)
- **Steps**:
  1. Add `supports_reference_images: bool` as a class attribute to the protocol/ABC in `base.py` (default not set — force each provider to declare).
  2. Set `True` on OpenAI + Gemini, `False` on Z.AI + Ollama (per CLAUDE.md provider notes — verify against each provider's docstring). `RoutedImageProvider`/`SplitImageProvider` delegate to their active/primary provider (property).
  3. Where callers currently rely on per-provider knowledge or the `on_ref_loss` toast to detect capability loss, consult the flag where it simplifies logic — but keep the toast (runtime fallback can still change the effective provider).
- **Method**: Static capability declaration; small and additive. Pitfall: pyright strict — declare the attribute on the protocol with a type annotation, and as `ClassVar[bool]` if providers set it at class level.
- **Verify**: `make checkall`; image-provider unit tests stay green.

### [ARC-116] Makefile cosmetics
- **Files**: `Makefile:45` (`Checkall: checkall`), `.PHONY` line
- **Steps**: Delete the `Checkall:` alias target and remove `Checkall` from `.PHONY`. Leave `build` semantics alone (documented choice).
- **Verify**: `make checkall` still runs; `make Checkall` now errors (expected).

---

## Phase 3c — Code Quality

> Internal order: QA-001 → QA-002 (decompositions, folding in QA-006/007/013/014/015/016) → QA-003 (tests) → remaining small items → QA-004 (gate wiring, dead last).
> QA-013 additionally requires SEC-101 to be done (URL shape confirmed).

### [QA-001] Decompose PlayPage (fold in QA-006, QA-007, QA-014, QA-015, QA-016)
- **Files**: `web/src/app/play/[gameId]/page.tsx` (1,218 lines) → new files under `web/src/components/play/` and `web/src/hooks/`; `web/src/hooks/useWebSocket.ts`; `web/src/stores/game-store.ts`
- **Steps**:
  1. Read the page fully (2 reads: it exceeds one screenful — check `wc -l`). Inventory the `useState` clusters and modals. The in-file `RelationshipsModal` is the extraction template.
  2. Extract, one commit-sized move at a time, verifying `npx tsc --noEmit` between moves:
     a. Each modal → `web/src/components/play/<Name>Modal.tsx` (props: open/onClose + the narrow data it renders; state that only the modal uses moves with it).
     b. Feature hooks → `web/src/hooks/`: `usePlayTts.ts` (TTS + auto-read state), `useSceneImage.ts` (image status/URL), `usePortraitActions.ts` (regen/edit/export), `useReplay.ts`. Each hook owns its `useState`s and returns a minimal interface.
     c. The page shell keeps routing params, the store subscription, layout, and hook wiring. Target <300 lines.
  3. While `useWebSocket.ts` is open, apply the folded fixes:
     - **QA-006**: choose implement (preferred): in `game-store.ts`, make `setImageStatus(nodeId, status)` actually update `nodes[nodeId].image_status`; in the WS hook's `image_status` case, call it. If the server never emits the event (check `src/storygen_api/runtime.py` / callback wiring), delete both instead — verify with `rg -n "image_status" src/storygen_api/`.
     - **QA-007**: in the `image_failed` case, call the store's `setError(...)` (or set node `image_status: "failed"`) so `ImagePanel` shows a failure state instead of an infinite spinner.
     - **QA-014**: replace the 17-field hand-reconstruction in `beat_committed` with a defaults-spread merge: `{...NODE_DEFAULTS, ...existingNode, id, narration, choices, is_ending, ...}` so unknown/new fields pass through; define `NODE_DEFAULTS` once next to the `StoryNode` type.
     - **QA-015**: reconnect with exponential backoff (e.g. base 1 s, ×2, cap 30 s, reset on successful open) and **stop** on close codes 4403/4404.
     - **QA-016**: wrap the `console.log` calls (lines ~30, 95 pre-edit) in `if (process.env.NODE_ENV !== "production")` or a tiny `debugLog` helper. Keep `console.error`.
  4. No behavior changes beyond the folded fixes; visual/UX identical.
- **Method**: Modal-first extraction is lowest-risk (self-contained JSX + state); hooks second; shell last. Verify types between every move — TypeScript is the extraction safety net given near-zero tests (QA-003 comes after for exactly that reason). Pitfall: preserve `use client` directives on every new component/hook file that needs them; keep Zustand selectors narrow so extraction actually reduces re-renders.
- **Verify**: `cd web && npx tsc --noEmit && npm run lint && npm run test`; `npm run build` (Next build catches RSC/client-boundary mistakes); manual smoke via `make web-dev` + `make api-dev`: load a game, advance, open each modal, trigger TTS.

### [QA-002] Decompose CharactersPage
- **Files**: `web/src/app/characters/page.tsx` (1,226 lines) → `web/src/components/characters/`, `web/src/hooks/`
- **Steps**: Same recipe as QA-001: read fully; extract create/edit/import modals to components; extract per-character action hooks (`useCharacterActions`: regen/edit/export/delete); page shell <300 lines; `npx tsc --noEmit` between moves.
- **Method/Verify**: identical to QA-001.

### [QA-003] Web test coverage for the core correctness surface — after QA-001/002
- **Files**: new `web/src/stores/game-store.test.ts`, `web/src/lib/api.test.ts`, smoke tests for extracted components; existing patterns: `web/src/hooks/useWebSocket.test.ts`, `web/vitest.config.ts`, `web/vitest.setup.ts`
- **Steps**:
  1. `game-store.test.ts` (the priority): seed the store explicitly (per the repo's "explicit singleton seeding" pattern in the existing tests), then cover: `loadGame` populates nodes; `advanceChoice` optimistic state; `setBeatCommitted` merges a node and preserves unknown fields (regression for QA-014); `jumpToNode`; `setImageStatus` (post-QA-006); error paths via `setError`.
  2. `api.test.ts`: mock `fetch`; assert auth header presence with/without token (SEC-102 regression), error propagation on non-2xx, and `sceneImageUrl` (post-QA-013) null-vs-URL behavior.
  3. Component smoke tests for 2–3 extracted modals: render with minimal props, assert key content, fire the close handler.
  4. Do not chase coverage numbers — cover the store exhaustively (it's the correctness core), the rest smoke-level.
- **Method**: Store-first because WS→store dispatch is where silent regressions live. Pitfall: jsdom lacks `WebSocket` niceties — the existing `vitest.setup.ts` already stubs what `useWebSocket.test.ts` needed; reuse it.
- **Verify**: `cd web && npm run test` — all new tests pass; `npm run lint`.

### [QA-009] SettingsScreen: extract a `ProviderSection` helper
- **Files**: `src/storygen/screens/settings.py` (1,477 lines), new `src/storygen/screens/controllers/settings_providers.py` (or extend the existing `settings_image.py` controller pattern — read `src/storygen/screens/controllers/` first and match it)
- **Steps**:
  1. Read the three method families: `_refresh_api_key_status`/`_refresh_image_api_key_status`/`_refresh_character_image_api_key_status`, `_refresh_suggested` ×3, `_sync_*_model_select` ×2, `*_model_options` ×2, plus `compose` (412-575), `_populate_from_state` (707-860), `_save_settings` (1219-1385).
  2. Define a `ProviderSection` class parameterized by widget-id prefix (`"text"`, `"image"`, `"char_image"`) and the config accessor, exposing `refresh_key_status(screen)`, `refresh_suggested(screen)`, `sync_model_select(screen)`, `populate(screen, state)`, `collect(screen) -> <prefs fragment>`.
  3. Replace each triplicated family by delegation to three `ProviderSection` instances; `compose` keeps layout but can loop the three sections for their repeated widget groups where markup is identical.
  4. Move in small steps, running the settings tests between each family.
- **Method**: This is the repo's established controller-extraction pattern applied to its largest file. Pitfall: Textual widget IDs are load-bearing (`query_one("#...")`) — the prefix parameterization must reproduce the exact existing IDs, or CSS/queries break silently; grep the TCSS files for the IDs before renaming anything (`rg -n "#text_|#image_|#char" src/storygen/**/*.tcss src/storygen/screens/settings.py`). Do not rename IDs in this pass.
- **Verify**: `make checkall`; `uv run pytest tests/unit -k "settings" -q` (51 pyright-ignores in the settings tests are expected/documented).

### [QA-012] Dedupe `import_from_story` asset copying + log failures
- **Files**: `src/storygen_api/routers/characters.py:462-486` (post-ARC-105 numbers shift — re-read)
- **Steps**:
  1. Hoist `from storygen.storage import paths as save_paths` to module level.
  2. Extract `def _read_save_asset(save_id: str, rel_path: str) -> bytes | None` performing the safe_join + read with `except (ValueError, OSError) as exc: _logger.debug("asset copy skipped for %s/%s: %s", save_id, rel_path, exc); return None`.
  3. Replace both duplicate blocks (portrait bytes, reference bytes) with calls.
- **Method**: Behavior-identical except the debug log. Pitfall: keep the placeholder-portrait fallback behavior exactly as-is when the read returns None.
- **Verify**: `make checkall`; `uv run pytest tests/unit -k "import_from_story or characters" -q`.

### [QA-013] Single `sceneImageUrl` helper — after SEC-101
- **Files**: `web/src/lib/api.ts`, `web/src/stores/game-store.ts` (5 sites), `web/src/hooks/useWebSocket.ts` (1 site)
- **Steps**:
  1. Confirm the post-SEC-101 scene URL shape by reading `src/storygen_api/routers/images.py` (route path unchanged if SEC-101 only deleted the mount).
  2. In `api.ts`, add `export function sceneImageUrl(gameId: string, node: Pick<StoryNode, "id" | "image_status">): string | null` returning the URL only when `image_status === "done"`, else null.
  3. Replace all six duplicated constructions (`rg -n "scene/" web/src`).
- **Method**: Pure DRY. Pitfall: one or two sites may build the URL for a node object not yet in the store (WS hook) — the `Pick<>` parameter type keeps that flexible.
- **Verify**: `cd web && npx tsc --noEmit && npm run test && npm run lint`.

### [QA-010] Shared `_is_retryable` for image providers
- **Files**: `src/storygen/images/ollama_provider.py:44-56`, `src/storygen/images/zai_provider.py:58-69`, new shared home (check for an existing `src/storygen/images/_retry.py` or constants module first — `ls src/storygen/images/`)
- **Steps**: Create `src/storygen/images/_retry.py` with the shared `_RETRYABLE_EXCEPTIONS` tuple + `is_retryable(exc) -> bool`; import in both providers; delete the local copies. Keep the public name each provider's tenacity decorator references.
- **Verify**: `make checkall`; `uv run pytest tests/unit -k "ollama or zai" -q`.

### [QA-011] Extract duplicated portraits `on_mount` image block
- **Files**: `src/storygen/screens/portraits.py:172-180, 205-213`
- **Steps**: Read both widget classes; extract a module-level helper `def _mount_terminal_image(widget, path) -> None` (or a small mixin) containing the shared body; replace `except Exception: pass` with `except Exception: _logger.debug("terminal image mount failed for %s", path, exc_info=True)`.
- **Verify**: `make checkall`; `uv run pytest tests/unit -k "portraits" -q`.

### [QA-017] Prune source-side pyright-ignores
- **Files**: `src/storygen/app.py` (18), `src/storygen/screens/play.py` (15), `src/storygen/screens/menu.py` (14), `src/storygen/screens/preset_picker.py` (13)
- **Steps**: For each file: `rg -n "pyright: ignore|type: ignore" <file>`; for each hit, remove the comment and run `uv run pyright <file>` — if it now passes, the ignore was stale, keep the removal; if it errors, restore the comment exactly. Do NOT restructure code to eliminate a legitimately needed ignore (the loose-typed adapter convention in CLAUDE.md stays).
- **Method**: Purely subtractive; the type-checker is the oracle. Pitfall: `# type: ignore[no-untyped-def]` on pydantic-ai adapters is a documented convention — leave those.
- **Verify**: `make checkall`.

### [QA-018] Timeouts on read-only fetch helpers
- **Files**: `web/src/lib/api.ts` (GET wrappers)
- **Steps**: Add `signal: AbortSignal.timeout(15_000)` to the read-only GET wrappers only. Explicitly exclude POST/advance/wizard/image-generation calls (60–120 s legitimate). Map the resulting `TimeoutError`/`AbortError` to the wrapper's existing error type with a clear message.
- **Verify**: `cd web && npx tsc --noEmit && npm run test`.

### [QA-004] Wire web checks into the verification gate — LAST
- **Files**: `Makefile` (post-ARC-111/116 state)
- **Steps**:
  1. Add:
     ```make
     web-check:           ## Web gate: eslint + vitest + tsc
     	cd web && npm run lint && npm run test && npx tsc --noEmit
     ```
  2. Add `web-check` to `checkall`'s prerequisites (`checkall: lint typecheck test web-check`) — matching the audit's recommendation that the documented gate cover all surfaces. If `node_modules` may be absent, make `web-check` fail with a clear message (`test -d web/node_modules || (echo "run make web-install" && exit 1)`).
  3. Update `.PHONY` and the CLAUDE.md/README command lists that document `checkall` (coordinate with 3d docs agents — mention it in your report rather than editing docs they own).
- **Method**: Lands after every other web entry so the newly wired gate starts green. Pitfall: `npm run test` is `vitest run` (non-watch) — correct as-is; don't use bare `vitest` (watch mode hangs CI).
- **Verify**: fresh `make web-install && make checkall` passes end-to-end; breaking a web test makes `make checkall` fail.

---

## Phase 3d — Documentation

> One agent should own each file to avoid conflicting edits (see the Conflict Map).
> DOC-001 + DOC-002 are one sweep. Fix docs to describe **post-fix** behavior for anything
> Phases 1–3c changed (notably SEC-101 image serving and QA-004 checkall).

### [DOC-001] Auth-semantics sweep (five documents)
- **Files**: `README.md` (~478), `docs/ARCHITECTURE.md` (auth + WS sections), `CLAUDE.md` ("Optional web surface"), `.env.example` (~59), `web/README.md` (~48)
- **Steps**:
  1. Read `src/storygen_api/security.py` docstrings and the CHANGELOG [Unreleased] Security entry — that wording is ground truth: token **unset** → loopback peers trusted, off-box requests fail closed (HTTP 503, WS 4403); token **set** → bearer required for all clients including loopback.
  2. In each of the five files, find the stale claim (search for "503", "fail-closed", "fails closed", "STORYGEN_API_TOKEN") and replace with the two-mode description. Keep each edit local — don't rewrite surrounding sections.
  3. Fix README's "As of v0.5.x" framing → the behavior is unreleased (or phrase version-neutrally).
- **Method**: Copy semantics from code/CHANGELOG, never from memory. Pitfall: `.env.example`'s comment must stay accurate for BOTH modes and keep the token-generation one-liner.
- **Verify**: `rg -n "fail.?closed|503" README.md docs/ARCHITECTURE.md CLAUDE.md .env.example web/README.md` — every remaining hit describes the two-mode behavior correctly (manual read).

### [DOC-002] Repoint the deleted-AUDIT.md references
- **Files**: `web/README.md:88`, `AGENTS.md:11`, `CLAUDE.md` (the "See `AUDIT.md` (SEC-001/SEC-006)" sentence)
- **Steps**:
  1. Note: this audit run has re-created `AUDIT.md` with **new** IDs. Repoint all three references to durable homes anyway (README/ARCHITECTURE security sections), since AUDIT.md is a point-in-time artifact: e.g. CLAUDE.md → "see the Security section of `docs/ARCHITECTURE.md` before exposing it beyond loopback".
  2. Add a short "finding-ID glossary" note to `docs/ARCHITECTURE.md`: historical SEC-XXX/ARC-XXX IDs cited in code comments refer to the 2026-07 audit cycles; the CHANGELOG [Unreleased] Security/Changed entries describe the shipped fixes.
  3. Verify no other dangling references: `rg -n "AUDIT.md|AUDIT-REMEDIATION" --glob '!AUDIT*' --glob '!*.py' .` and fix any stragglers similarly.
- **Verify**: `rg -n "AUDIT" web/README.md AGENTS.md CLAUDE.md` shows only intentional mentions; par-mem `find_broken_doc_links` (repo_id `par-storygen`, after reindex) no longer reports `../AUDIT.md`.

### [DOC-003] CHANGELOG link refs
- **Files**: `CHANGELOG.md` (bottom link-reference block)
- **Steps**: Add `[0.4.0]` and `[0.5.0]` compare-link definitions following the existing pattern; repoint `[Unreleased]` to `v0.5.0...HEAD`. Do NOT push tags (outward-facing; owner decision) — add an HTML comment `<!-- NOTE: tags v0.2.0–v0.5.0 not yet pushed; compare links 404 until then -->`.
- **Verify**: markdown link refs resolve syntactically (each `[x.y.z]:` line present for each `## [x.y.z]` heading).

### [DOC-004] Fix spec-archive filenames in ARCHITECTURE.md
- **Files**: `docs/ARCHITECTURE.md` ("Design docs archive" section)
- **Steps**: `ls docs/superpowers/specs/ docs/superpowers/plans/ docs/*.md`; correct the three `2026-05-03-*-design.md` citations to the actual plan filenames; add `docs/2026-05-01-book-export-design.md` to the archive list (leave the file where it is unless trivially movable — moving files breaks external links; prefer listing).
- **Verify**: every path named in the section exists (`ls` each).

### [DOC-005] ARCHITECTURE.md keybindings + runtime layer (incl. ARC-114)
- **Files**: `docs/ARCHITECTURE.md` (five keybinding mentions + mermaid diagram + adapters heading)
- **Steps**:
  1. Ground truth: read `src/storygen/screens/play.py` BINDINGS (~lines 125-151) and the README Keyboard Shortcuts tables. Fix: library `l` → `ctrl+l`; graph `g` → `i` (info picker) → Graph; endings `e` → `i` → Endings; "retry image `i`" → `r` regen picker.
  2. Mermaid diagram: add the `runtime/` layer between llm+images and the composition roots; fix the "LLM call adapters (`src/storygen/app.py`)" heading → `src/storygen/runtime/adapters.py`.
- **Verify**: every binding claim in the doc matches a BINDINGS entry (manual cross-check); mermaid renders (paste into a mermaid previewer or trust syntax).

### [DOC-006] README Roadmap relationships key
- **Files**: `README.md` (~538)
- **Steps**: Change "viewable via `f`" → "viewable via `i` → Relationships".
- **Verify**: `rg -n "via \`f\`" README.md` → no hits.

### [DOC-007] Document the missing API/web env vars
- **Files**: `.env.example`, `README.md` (env section), `web/README.md`
- **Steps**:
  1. Ground truth: `rg -n "STORYGEN_API_ALLOWED_ORIGINS|STORYGEN_WS_ALLOWED_ORIGINS|STORYGEN_API_RATE_LIMIT" src/storygen_api/` — read each consumption site for default + format.
  2. Add all three to the FastAPI block of `.env.example` (commented-out, with defaults and a format example, e.g. comma-separated origins). Mention them in README's Web API section.
  3. Add `NEXT_PUBLIC_API_BASE` (and, post-SEC-102, `NEXT_PUBLIC_API_TOKEN`) to `web/README.md`'s run section.
- **Verify**: every `STORYGEN_*`/`NEXT_PUBLIC_*` env var read in `src/storygen_api/` + `web/src/lib/config.ts` appears in `.env.example` or `web/README.md` (`rg -n "getenv|process.env" src/storygen_api web/src/lib` cross-check).

### [DOC-008] web/README.md data-flow staleness
- **Files**: `web/README.md` (~50, ~70), `README.md` (~490)
- **Steps**: Replace "hard-codes `API_BASE` in api.ts" with the `config.ts`/`NEXT_PUBLIC_API_BASE` description (match `web/AGENTS.md`, which is already correct); replace root README's "edit the CORS allowlist in main.py" with `STORYGEN_API_ALLOWED_ORIGINS`; complete the WS event list with `new_characters` and `error` (ground truth: the switch in `web/src/hooks/useWebSocket.ts`).
- **Verify**: claims match `web/src/lib/config.ts` and the WS hook's actual cases.

### [DOC-009] Document the API schemas
- **Files**: `src/storygen_api/schemas.py`
- **Steps**: Add a one-line docstring to every public model class (30 of 31 lack one) and `Field(description=...)` to non-obvious fields (ids, status enums, cost/token counters, timestamps). Keep descriptions factual and short; they render into `/docs`.
- **Verify**: `make checkall`; spot-check `uv run python -c "from storygen_api.main import app; import json; print(len(json.dumps(app.openapi())))"` runs clean; open `/docs` if a server is running. **Coordinate**: if ARC-108 landed, regenerate its OpenAPI snapshot (descriptions change it).

### [DOC-010] `storygen-api serve` port default → 8101
- **Files**: `src/storygen_api/main.py` (`serve` command), `README.md`, `AGENTS.md`
- **Steps**: Change the `serve` port default from 8000 → 8101 (matches all docs, the Makefile, and the CORS pairing with :8100; both ports are already recorded in `~/.claude/used_ports.md` conventions for this project — do not pick new ones). Add a 3-line `storygen-api serve` flag reference (`--host/--port/--reload`) to README's Web API section. Update any test asserting the default port.
- **Verify**: `make checkall`; `uv run storygen-api serve --help` shows 8101.

### [DOC-011] Docstring gaps (screens/widgets/modules)
- **Files**: `src/storygen/screens/_recap_modal.py`, `src/storygen/screens/style_gallery.py`, `src/storygen/core/presets.py`, `src/storygen/images/__init__.py` (module docstrings); `src/storygen/widgets/choice_list.py:format_choice_line`, `src/storygen/widgets/character_sheet.py:format_character_entry`, `src/storygen/images/base.py` protocol methods (member docstrings)
- **Steps**: Add module docstrings to the four modules (one paragraph: what the module is, who uses it). Add docstrings to the named non-obvious public helpers and the `ImageProvider.generate_portrait`/`generate_scene` protocol methods (args/returns/side effects). Do NOT blanket-docstring Textual boilerplate (`compose`, `on_mount`, `action_*`).
- **Verify**: `make checkall` (ruff pydocstyle rules if enabled; otherwise manual).

### [DOC-012] README badges
- **Files**: `README.md:43`
- **Steps**: Fix the license badge slug `pypi/l/mit` → `pypi/l/par-storygen`; add a version badge `https://img.shields.io/pypi/v/par-storygen` next to it, matching the existing badge markup style.
- **Verify**: badge URLs return an SVG (`curl -sI https://img.shields.io/pypi/l/par-storygen | head -1`).

### [DOC-013] Troubleshooting guide
- **Files**: new `docs/TROUBLESHOOTING.md`, `README.md` (link from a short Troubleshooting section)
- **Steps**: Follow the template in `docs/DOCUMENTATION_STYLE_GUIDE.md`. Cover at minimum: missing/invalid API key (per provider); Ollama not running / wrong base URL; image provider 4xx (content policy, model name); blank image panel (art disabled, terminal protocol); TTS produces no audio; web UI can't reach the API (port/CORS/token — post-DOC-001 semantics). Symptom → cause → fix format. Link from README.
- **Verify**: style-guide compliance (language-fenced blocks, TOC if long); all referenced env vars/commands exist.

### [DOC-014] CONTRIBUTING.md
- **Files**: new `CONTRIBUTING.md`, `README.md` (point the Contributing section at it)
- **Steps**: Short and factual, derived from observed practice: setup (`make build` post-ARC-111 flags, `make web-install`), the gate (`make checkall` incl. web post-QA-004), pre-commit install, conventional-commit style (evidence: `git log --oneline -30`), branch/PR flow (trunk-ish with feature branches), where design docs live (`docs/superpowers/`).
- **Verify**: every command in it works from a fresh clone (spot-run the setup + gate).

### [DOC-015] Complete the CLI reference
- **Files**: `README.md` ("Command line arguments" block)
- **Steps**: Ground truth via `uv run storygen --help` and `uv run storygen-api --help`. Add the top-level `--version` flag and a short `storygen-api` subsection (serve + flags; note the console script requires `--extra api`).
- **Verify**: documented flags match `--help` output verbatim.

---

## Phase 4 — Final Verification (after all phases)

1. `make build && make checkall` from a pruned env (`uv sync` first to prune, then build) — Python + (post-QA-004) web gates green.
2. `cd web && npm run build` — production build clean.
3. Reindex par-mem (`index_directory`) and re-run `find_broken_doc_links` — zero broken links.
4. Manual smoke: `make api-dev` + `make web-dev`, create a game via wizard, advance twice, confirm usage totals accumulate across both advances in `game.json` (ARC-101 regression), confirm `/api/images/<id>/game.json` is 404 (SEC-101).
5. `git status` review — every changed file traces to an entry above.
