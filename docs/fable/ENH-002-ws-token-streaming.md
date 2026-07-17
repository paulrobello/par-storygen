# ENH-002 — Stream narration tokens to the web UI over WebSocket

## Goal
Render beat narration progressively in the web play page as the LLM generates it (the TUI already does
this), instead of a spinner until `beat_committed`. Success = tokens visibly stream in the story panel
during an advance; the committed node still replaces the streamed text verbatim.

## Current state
- `storygen.pipeline.PipelineCallbacks` (src/storygen/pipeline.py:144, in-degree 63 in the graph) carries
  the streaming callback the TUI uses; `tests/unit/test_pipeline.py`'s `FakeBeatAgent` streams tokens
  "through the real callback path" — read that test to learn the exact callback name/signature (likely
  `on_token`/`on_beat_token`).
- `src/storygen_api/runtime.py` (or wherever `ws_manager.make_callbacks` lives — `rg -n "make_callbacks" src/storygen_api/`)
  maps `PipelineCallbacks` → WS broadcast events; ARCHITECTURE.md documents 13 server→client events.
  The token callback is presumably NOT mapped today — verify with `rg -n "token" src/storygen_api/`.
- `web/src/lib/ws-types.ts` enumerates the event types; `tests/unit/test_api_ws.py` pins the contract.
- Do this AFTER audit QA-001 (PlayPage decomposition) — the render target is much cleaner there.

## Steps
1. **Read first**: `src/storygen/pipeline.py` (`PipelineCallbacks` fields), the API callback factory
   (`make_callbacks`), `docs/ARCHITECTURE.md` WS event table, `web/src/lib/ws-types.ts`.
2. **Server event.** In the callback factory, map the token callback to a broadcast:
   `{"type": "narration_token", "from_node_id": <parent>, "token": <str>}`.
   - **Throttle**: accumulate tokens and flush at most every ~100 ms or 20 tokens (a `list` + `loop.time()`
     check inside the callback; flush remainder in the beat-committed path). Raw per-token frames will
     flood the socket and the client render.
   - The broadcast helper already serializes under an `asyncio.Lock` (per prior remediation) — reuse it.
3. **Contract**: add `narration_token` to `web/src/lib/ws-types.ts` (payload: `from_node_id: string; token: string`)
   and to the pydantic mirror in `tests/unit/test_api_ws.py` following the existing per-event pattern.
   Update the ARCHITECTURE.md event table (now 14 events).
4. **Store**: in `web/src/stores/game-store.ts` add `streamingText: string` + `streamingFromNodeId: string | null`
   with actions `appendStreamToken(fromNodeId, token)` (concat) and `clearStream()`. `setBeatCommitted`
   must call `clearStream()`.
5. **WS hook**: add the `narration_token` case → `appendStreamToken(...)`.
6. **UI**: in the story panel component (post-QA-001 extraction), when `streamingText` is non-empty and the
   game is advancing, render it (typing-cursor styling optional) in place of the spinner; on
   `beat_committed` the committed node renders as today. Keep the spinner for the pre-first-token gap.
7. **Fallback**: if no `narration_token` arrives (older server), behavior is exactly today's — no client
   version gating needed.
8. **Tests**: store test (append/clear/committed-clears); WS-hook test dispatching a `narration_token`
   frame (follow `useWebSocket.test.ts` patterns); Python-side test that an advance through the API
   callback factory emits ≥1 `narration_token` broadcast (FakeBeatAgent streaming, capture broadcasts
   with a stub manager).

## Files to touch
- Edit: API callback factory module (locate via `rg -n "make_callbacks" src/storygen_api/`),
  `web/src/lib/ws-types.ts`, `web/src/stores/game-store.ts`, `web/src/hooks/useWebSocket.ts`,
  story-panel component (post-QA-001 path), `docs/ARCHITECTURE.md`, `tests/unit/test_api_ws.py`
- New tests: `web/src/stores/game-store.test.ts` cases (file may exist from QA-003)
- Untouched: `src/storygen/pipeline.py` (the callback already exists — if it does not, STOP and report;
  adding a new pipeline callback changes the TUI contract and needs owner input)

## Verification
```sh
make checkall
cd web && npm run test && npx tsc --noEmit && npm run lint
```
Manual: `make api-dev` + `make web-dev` with a real text provider; advance a story; narration appears
progressively; final text identical to the committed node; TUI behavior unchanged (`make run` smoke).

## Rollback
Additive event: remove the server mapping and the client case/actions; the `beat_committed` path was never
modified. Single revert commit restores status quo.

## Pitfalls
- Don't set `nodes[id].narration` from tokens — the streamed text goes in a separate scratch field;
  the committed node is the only source of truth (cache-replay byte-parity depends on it).
- Throttling lives server-side (protects socket + client); client just concatenates.
- Multiple tabs: broadcasts fan out to all sockets for the game — concatenation is per-store, already per-tab. Fine.
- WS frame size cap (64 KiB) is per client→server message — server→client tokens unaffected, but keep flush batches small anyway.
