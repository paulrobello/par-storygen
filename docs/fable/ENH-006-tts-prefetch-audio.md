# ENH-006 — Opt-in TTS audio pregeneration during prefetch

## Goal
When branch prefetch has already generated a pending choice's beat, optionally synthesize its narration
audio into the existing per-node cache so picking that choice plays TTS instantly. Strictly opt-in
(default off) because it spends TTS-provider credits speculatively.

## Current state
- `src/storygen/pipeline_prefetch.py` — `PrefetchCoordinator` background-generates pending choices' beats
  (+ images) with a semaphore; read it fully first.
- `src/storygen/tts/player.py` — `TTSPlayer` (4-state machine) caches audio at
  `$XDG_DATA_HOME/storygen/games/<game-id>/audio/<node-id>-<provider>-<voice-id>.mp3`; `speak` (~line 201,
  CC 18) synthesizes on miss. Identify the synth-to-file path separable from playback — there is likely a
  private "ensure audio file" section inside `speak`; if not separable, extracting
  `async def synthesize_to_cache(node_id, text) -> Path` is step one.
- TTS prefs: `TTSPrefs` in settings (`rg -n "class TTSPrefs" src/`); TTS can be disabled entirely.
- The TUI auto-read feature calls `speak` on node arrival (`rg -n "auto_read|auto-play" src/storygen/screens/play.py`).

## Steps
1. **Extract synthesis from playback** in `tts/player.py`: `synthesize_to_cache(node_id: str, text: str) -> Path | None`
   containing the cache-key computation + provider call + MP3 write that `speak` currently inlines;
   `speak` becomes check-cache → synthesize if missing → play. Zero behavior change; run
   `uv run pytest tests/unit -k tts -q` before proceeding.
2. **Add the pref**: `pregenerate_prefetch_audio: bool = False` on `TTSPrefs`; surface a checkbox in the
   TUI settings TTS section (follow the existing TTS pref widgets; coordinate with QA-009 if in flight)
   and in the API settings schema if TTS prefs are exposed there (`rg -n "tts" src/storygen_api/schemas.py`).
3. **Hook the coordinator**: in `PrefetchCoordinator`, after a prefetched node's beat is committed
   (locate the completion point where the node + narration exist), if TTS is enabled AND the new pref is
   on AND the player is idle-capable, call `synthesize_to_cache(node_id, narration)` inside the same
   task's try/except — failures log at debug and never fail the prefetch. Respect the existing prefetch
   semaphore (audio joins the task, not a new unbounded task).
4. **Concurrency guard**: `synthesize_to_cache` may be called for node X by prefetch while the user plays
   node Y. Ensure the synth path doesn't disturb the player state machine (it must not transition
   play/pause states — pure file production). Guard the same-node race (user picks the choice while its
   audio is synthesizing) with a per-node `asyncio.Lock` or "in-flight" set so `speak` awaits the
   in-flight synth instead of double-generating; the existing `_regen_busy`-style set convention
   (CLAUDE.md) is the pattern to follow.
5. **Cost surfacing**: TTS cost accounting — check whether TTS usage is tracked (`rg -n "cost" src/storygen/tts/`);
   if per-request cost is recorded, prefetch synths must record identically.
6. **Cache-key correctness**: the key embeds provider + voice — if the user changes voice after
   pregeneration, `speak` misses and regenerates (correct, slightly wasteful; acceptable — note it in
   the setting's help text: "uses current voice at prefetch time").
7. **Tests** (fake TTS provider per existing tts tests): pref off → coordinator never synthesizes;
   pref on → prefetched node has a cached MP3; in-flight race → exactly one provider call; synth failure
   → prefetch still succeeds.

## Files to touch
- Edit: `src/storygen/tts/player.py`, `src/storygen/pipeline_prefetch.py`, `TTSPrefs` model + settings
  screen section, possibly `src/storygen_api/schemas.py`
- New tests: extend `tests/unit` tts/prefetch modules
- Docs: README TTS section (one paragraph, note the cost tradeoff), `.env.example` untouched (it's a pref, not env)

## Verification
```sh
make checkall
uv run pytest tests/unit -k "tts or prefetch" -q
```
Manual: enable TTS (Kokoro local = free) + the new pref; play until prefetch fires (graph screen shows
pending children generated); pick the prefetched choice → audio starts instantly (no synth delay);
`ls` the game's `audio/` dir shows the MP3 predating the pick.

## Rollback
Feature-flagged by the pref (default off) — rollback = revert the commit; users who enabled it just lose
the toggle. Pregenerated MP3s are ordinary cache entries, valid either way.

## Pitfalls
- Never let audio synthesis extend the beat-generation critical path — it runs strictly after the
  prefetched node commits.
- Kokoro (local) vs cloud providers: synthesis latency varies hugely; the semaphore prevents pileups but
  test with the fake provider simulating slowness.
- Don't pregenerate for ALL pending choices' grandchildren — only the nodes the coordinator itself
  prefetched (same scope as images).
