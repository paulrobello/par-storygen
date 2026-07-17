# ENH-003 — Fast game listing via summary sidecar

## Goal
Make game listing O(games) instead of O(total story size): the TUI load screen and `GET /api/games`
read a tiny per-game `summary.json` instead of parsing every full `game.json`. Success = listing a
library of large saves does constant small reads per game, with transparent fallback for legacy saves.

## Current state
- **Prerequisite**: AUDIT ARC-109 (storage-layer `list_game_summaries()`/`load_game_summary()`) must be
  done first — this plan optimizes that single choke point. If ARC-109 is not done, do it first per
  `AUDIT-REMEDIATION-PLAN.md`.
- `save_game` (`src/storygen/storage/save.py:131`) is the single write choke point (graph in-degree 121):
  every persistence goes through it, writing `game.json` atomically (`.tmp` + `os.replace`).
- Save schema is versioned (v4) with cumulative migrations in `storage/save.py`.
- Game dirs live under `paths.games_root()/<game-id>/`.

## Steps
1. **Define the sidecar model** in `src/storygen/storage/save.py`:
   ```python
   class GameSummaryFile(BaseModel):
       """Cheap listing sidecar (summary.json) — derived from GameSave, safe to regenerate."""
       schema_version: int = 1
       id: str
       title: str
       node_count: int
       endings_reached: int
       current_node_id: str
       created_at: <match GameSave's type>
       updated_at: <match GameSave's type>
       # plus whatever fields ARC-109's summary loader exposes (match exactly — read it first)
   ```
   Match field names/types to the ARC-109 summary structure so the lister is a drop-in.
2. **Write it in `save_game`**: after the existing atomic `game.json` write, derive `GameSummaryFile`
   from the save and write `<game_dir>/summary.json` with the same `.tmp` + `os.replace` pattern.
   Failure to write the sidecar must not fail the save: wrap in `try/except OSError` with
   `logger.warning("summary sidecar write failed", exc_info=True)` — `game.json` remains ground truth.
3. **Read it in the lister**: in ARC-109's `list_game_summaries()`, for each game dir:
   - `summary.json` exists and parses with a known `schema_version` → use it.
   - Missing/corrupt/older-schema → full `load_game(game_id)` fallback, then **backfill** the sidecar
     (write it) so the next listing is fast. Log at debug when falling back.
4. **Staleness guard**: `game.json` can be newer than the sidecar only if a crash hit between the two
   writes or an external tool edited the save. Compare `os.stat().st_mtime_ns` — if `game.json` is newer
   than `summary.json`, treat the sidecar as stale → fallback + backfill.
5. **Delete path**: confirm game deletion removes the whole dir (it does — verify in `storage/save.py`
   `delete_game`); no extra cleanup needed.
6. **Do not** add the sidecar to the save-schema migrations — it is derived data, versioned independently
   by its own `schema_version`, regenerable at will.
7. **Tests** (`tests/unit/test_save.py` or the ARC-109 test module, using the `xdg_tmp` fixture):
   - `save_game` produces a parseable `summary.json` matching the save.
   - Listing with sidecars present does not call full `load_game` (monkeypatch-count it).
   - Deleting `summary.json` → listing still correct and the sidecar is backfilled.
   - Touch `game.json` mtime forward → sidecar treated stale, listing correct.

## Files to touch
- Edit: `src/storygen/storage/save.py` (model + write + lister), tests
- Read-only: `src/storygen/storage/paths.py`, `src/storygen_api/routers/games.py` (should need zero changes — it consumes ARC-109's function)

## Verification
```sh
make checkall
uv run pytest tests/unit -k "save or summary or list" -q
```
Manual: create 2–3 games in the TUI, confirm `summary.json` appears in each game dir, load screen and
`curl http://127.0.0.1:8101/api/games` both list correctly; delete one sidecar and re-list.

## Rollback
Sidecars are derived + optional: revert the code and stale `summary.json` files are simply ignored dead
files (harmless; a cleanup note in the CHANGELOG suffices). No migration, no data risk.

## Pitfalls
- Keep sidecar derivation in ONE function reused by both the save-time write and the backfill, or they drift.
- mtime comparison must use the post-`os.replace` file, and beware coarse mtime resolution on some
  filesystems — use `st_mtime_ns` and treat equal timestamps as fresh.
- Don't let a corrupt `summary.json` raise out of the lister — any parse error is just "fallback".
