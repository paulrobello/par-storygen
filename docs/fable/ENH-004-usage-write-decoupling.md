# ENH-004 — Decouple usage accounting from full-save writes

## Goal
Stop rewriting the entire `game.json` on every LLM usage callback. One advance currently triggers up to
3+ full-file writes (beat, illustration, summary agents each fire `_on_usage` → `save_game`) on top of the
pipeline's own end-of-advance persistence. Success = usage totals still exact after every advance, with
exactly the pipeline's own save writes remaining (typically 1–2 per advance).

## Current state
- **Prerequisite**: AUDIT ARC-101/102/106 (single-owner save + per-game lock) must be done — this plan
  builds on the fixed ownership model. Read the post-remediation `src/storygen_api/deps.py` and
  `src/storygen/app.py:_start_game` first.
- Both composition roots build `on_usage` closures that call `record_usage_on_save(save, ...)` **and**
  `save_game(save)`:
  - TUI: `src/storygen/app.py` `_start_game._on_usage` (~line 419)
  - API: `src/storygen_api/deps.py` `build_pipeline._on_usage`
- The adapters (`src/storygen/runtime/adapters.py`: `BeatAgentAdapter`, `IllustrationAdapter`,
  `SummaryAdapter`) invoke `on_usage` after each agent call.
- `BeatPipeline.advance` persists the save itself at commit points (verify: `rg -n "save_game" src/storygen/pipeline.py`).
- Graph evidence: `save_game` in-degree 121, betweenness 0.076 — the hottest write hub in the repo.

## Steps
1. **Map every write**: `rg -n "save_game\(" src/storygen/ src/storygen_api/` and list which are
   (a) pipeline commit points, (b) usage-callback writes, (c) unrelated (settings, portraits, etc.).
   Only (b) changes.
2. **Make the callbacks mutate-only**: in both composition roots, delete the `save_game(save)` line from
   the `_on_usage` closures, leaving `record_usage_on_save(save, ...)`. Update the closure docstrings/comments.
3. **Guarantee a persist point**: confirm `BeatPipeline.advance` always ends with a `save_game` on every
   path that fired an agent — including the summary block and error paths:
   - Cache-hit/prefetch fast paths fire no agents → no usage to persist → fine.
   - Beat-generation path persists at commit → covers beat + illustration usage.
   - Summary block: verify a `save_game` happens after the summary agent runs (it must, to persist
     `recap_text`) — if the summary result is saved before `_on_usage` fires (ordering!), add one
     `save_game(save)` after the summary usage is recorded, or reorder so usage records before the write.
   - **Failure path**: if the illustration agent fires and the advance then raises, usage was recorded
     in memory but never persisted. Decide explicitly: wrap the agent-calling section so the `except`
     path does a best-effort `save_game(save)` before re-raising, or accept the loss and document it in
     the closure comment. Prefer the best-effort write — it's one line in the existing error handling.
4. **Wizard/character generation flows**: `rg -n "on_usage" src/` — any other consumers of the closures
   (wizard character gen, backstory adaptation) must have their own persist points; verify each flow
   ends in a `save_game`/state write and add one where missing.
5. **TUI header**: PlayScreen's sub_title reads in-memory totals (verify: `rg -n "sub_title|_apply_header" src/storygen/screens/play.py`)
   — unaffected by write timing. Confirm, don't assume.
6. **Tests**:
   - Update any test asserting a write-per-usage (search `tests/unit` for `save_game` call counting).
   - New test: advance once with Fake agents (beat + illustration + summary all firing); count
     `save_game` invocations via monkeypatch — assert it dropped to the pipeline's own writes; assert
     persisted totals still include all three agents' usage.
   - Crash-path test: illustration agent raises after usage fired → persisted save contains the beat
     usage (per the step-3 decision).

## Files to touch
- Edit: `src/storygen/app.py` (closure), `src/storygen_api/deps.py` (closure), possibly
  `src/storygen/pipeline.py` (persist-point ordering), tests
- Read-only: `src/storygen/runtime/adapters.py`, `src/storygen/llm/usage.py`

## Verification
```sh
make checkall
uv run pytest tests/unit/test_pipeline.py tests/unit -k "usage" -q
```
Manual: play two advances in the TUI; confirm the header cost/token counts tick after each agent and the
persisted `game.json` totals match after quit/resume.

## Rollback
Re-add the `save_game(save)` line to both closures — a two-line revert restores the old behavior exactly.

## Pitfalls
- The ordering bug to avoid: recording usage *after* the block that persists the save, which would leave
  the last agent's usage unpersisted until the *next* advance. Trace each agent's `_on_usage` firing
  point relative to the nearest `save_game` before changing anything.
- Do not batch/debounce with timers — the advance already has natural commit points; timers add
  crash-window complexity for nothing.
- Prefetch worker paths call the same adapters — verify prefetched-node commits also persist usage
  (they go through the same advance/commit machinery; confirm via `pipeline_prefetch.py`).
