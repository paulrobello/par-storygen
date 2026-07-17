# ENH-008 — API observability: request timing + provider-latency logging

## Goal
Make "why was that advance slow / what did it cost" answerable from logs: every API request logs method,
route template, status, and duration; every LLM/image provider call logs model, duration, and token/cost
figures at debug level. Structured `extra={}` fields, stdlib logging only, no new dependencies.

## Current state
- `src/storygen_api/main.py` builds the FastAPI app; logging exists for exceptions (SEC-004 pattern:
  `_logger.exception(...)`) but there is no request/latency logging. Check for an existing logging config
  (`rg -n "basicConfig|dictConfig|getLogger" src/storygen_api/ src/storygen/`).
- Usage data already flows through the `on_usage` callbacks (`src/storygen/runtime/adapters.py`) —
  post-ENH-004/ARC-101 read the current shape before wiring.
- The TUI must stay clean: Textual apps break if libraries print/log to stdout — any logging added to
  shared `storygen.*` modules must be logger-based (never print) and default-silent (debug level).

## Steps
1. **Request-timing middleware** in `src/storygen_api/main.py` (or a new `src/storygen_api/middleware.py`
   if `main.py` is crowded):
   ```python
   @app.middleware("http")
   async def _log_request_timing(request: Request, call_next):
       start = time.perf_counter()
       response = await call_next(request)
       duration_ms = (time.perf_counter() - start) * 1000.0
       route = request.scope.get("route")
       _logger.info(
           "request",
           extra={
               "method": request.method,
               "path": getattr(route, "path", request.url.path),  # route template, not raw path (no ids in logs)
               "status": response.status_code,
               "duration_ms": round(duration_ms, 1),
           },
       )
       return response
   ```
   - Use the route template so game UUIDs don't spray into logs (info-disclosure hygiene, consistent
     with SEC-004's spirit). Raw path only at debug level if needed.
   - Exempt nothing; WS connections don't pass through http middleware (that's fine — see step 3).
2. **Provider-latency logging** in `src/storygen/runtime/adapters.py`: each adapter's call path wraps the
   agent invocation; add `t0 = time.perf_counter()` and after completion
   `logger.debug("agent call", extra={"agent": "beat|illustration|summary", "model": ..., "duration_ms": ..., "input_tokens": ..., "output_tokens": ...})`
   pulling token figures from the same `result.usage` the adapters already read (mirror the existing
   `getattr` pattern; tokens may be absent — log None). Image providers: add the same debug timing in
   `SplitImageProvider`/`RoutedImageProvider` (`generate_portrait`/`generate_scene`) — one wrapper point,
   not per concrete provider.
3. **WS advance timing**: in the WS advance branch (post-SEC-103 state), log the same
   `duration_ms` around `pipeline.advance` at info with `extra={"game": "<hash>", ...}` — hash or truncate
   the game id (`game_id[:8]`) rather than logging it whole.
4. **Log config**: if the API has no logging setup, add a minimal one in the `serve` entrypoint only
   (uvicorn already configures root handlers; just set `storygen_api`/`storygen` logger levels from an
   env var, e.g. `STORYGEN_LOG_LEVEL`, default INFO for `storygen_api`, WARNING for `storygen`).
   Document the variable in `.env.example`.
5. **Tests**: middleware test via httpx client + `caplog` — one request produces one record with the
   expected extra fields and the route template (not the raw id path). Adapter test: Fake agent +
   `caplog(level=DEBUG)` asserts the timing record exists.

## Files to touch
- Edit: `src/storygen_api/main.py` (middleware + serve log config), `src/storygen/runtime/adapters.py`,
  `src/storygen/images/split_provider.py` (or routed — pick the single wrapper point),
  `src/storygen_api/routers/ws.py`, `.env.example`, tests
- Read-only: `src/storygen_api/rate_limit.py` (its logging conventions are the style reference)

## Verification
```sh
make checkall
uv run pytest tests/unit -k "middleware or timing or observ" -q
```
Manual: `STORYGEN_LOG_LEVEL=DEBUG make api-dev`, hit `/api/games` and run one advance — logs show one
request line per call and agent/image timing lines with token counts; confirm no raw game UUIDs at INFO;
run the TUI (`make run`) and confirm zero new console output.

## Rollback
Purely additive logging — revert the commit. No schema, storage, or API contract changes.

## Pitfalls
- `extra={}` keys must not collide with `LogRecord` attributes (`message`, `module`, `name`, …) —
  prefix with nothing but avoid reserved names (`duration_ms`, `status`, `method`, `path` are safe).
- Middleware must not swallow exceptions: let them propagate after timing (wrap `call_next` in
  try/finally if you want error timing too).
- Keep `storygen.*` (shared-layer) logs at DEBUG — the TUI shares those modules and INFO noise would
  land in Textual's devtools console.
