# Autoplay TTS Wait and Split Image Models Design

## Goal

Fix autoplay so it does not choose the next story option until the current beat's image is ready and text-to-speech auto-read has finished generating and playing. Add separate image-generation configuration for character portraits and scene/cover art, defaulting characters to OpenAI `gpt-image-1.5` for transparency support and art to OpenAI `gpt-image-2`.

## Current Behavior and Root Cause

`PlayScreen._pick()` renders a newly generated beat and starts auto-read by scheduling `_maybe_auto_read()` as an independent Textual worker. `_auto_select_next()` then schedules the next autoplay cycle immediately after `_pick()` returns. The next cycle checks `TTSPlayer.state`, but the auto-read worker may not have started yet, leaving the player in `IDLE`; autoplay can therefore select a new option before TTS generation/playback begins or finishes.

Autoplay also only applies the image viewing delay when `_image_displayed_at` is already set. If the autoplay loop reaches its wait step before the current node's image callback fires, it does not explicitly wait for the node's image generation to finish or fail.

## Autoplay Design

Autoplay will coordinate explicit foreground work instead of inferring state from a background worker race.

- `PlayScreen._pick()` will accept an internal `auto_read_inline: bool = False` flag.
- Manual picks keep the existing UX: after the beat renders, auto-read is scheduled as a background worker.
- Autoplay calls `_pick(..., auto_read_inline=True)`, causing `_pick()` to await `_maybe_auto_read()` before returning.
- `_auto_select_next()` will wait for the current node's image to reach a terminal state before applying the post-image viewing delay:
  - If art is disabled, skip image waiting.
  - If the current node has `image_status == "done"` and `_image_displayed_at` is set, wait until the configured viewing delay has elapsed.
  - If the current node has `image_status == "generating"`, poll the current `GameSave` node until status is no longer `generating`, autoplay is toggled off, or the node changes.
  - If the image fails or is not planned, continue without blocking indefinitely.
- Existing TTS controls remain available while autoplay is active.
- Turning autoplay off should stop future choices; it should not forcibly stop TTS unless the user presses Stop TTS.

## Split Image Configuration Design

Add a second per-save image config while preserving existing saves.

- Existing `GameSave.image_config` remains the scene/cover art config.
- Add `GameSave.character_image_config: ImageProviderConfig` with a default factory returning OpenAI `gpt-image-1.5`.
- Change the default `ImageProviderConfig.model` / `DEFAULT_IMAGE_MODEL` to `gpt-image-2` for art.
- Add `DEFAULT_CHARACTER_IMAGE_PROVIDER = "openai"` and `DEFAULT_CHARACTER_IMAGE_MODEL = "gpt-image-1.5"`.
- App state will persist character image prefs separately from art image prefs.
- Environment override behavior:
  - Existing `STORYGEN_IMAGE_PROVIDER`, `STORYGEN_IMAGE_MODEL`, `STORYGEN_IMAGE_BASE_URL`, and `STORYGEN_IMAGE_API_KEY` continue to configure scene/cover art.
  - New optional `STORYGEN_CHARACTER_IMAGE_PROVIDER`, `STORYGEN_CHARACTER_IMAGE_MODEL`, `STORYGEN_CHARACTER_IMAGE_BASE_URL`, and `STORYGEN_CHARACTER_IMAGE_API_KEY` configure character portraits.
  - If character-specific env vars are absent, character config comes from character image prefs or defaults, not from the art config.

## Provider Wiring Design

Introduce a small `SplitImageProvider` implementing the existing `ImageProvider` protocol:

- `generate_portrait()` delegates to the character provider/router.
- `generate_scene()` delegates to the art provider/router.

This avoids changing all existing call sites that expect one image provider while still routing portrait and scene work differently.

Provider construction rules:

- New stories use a split provider built from current art config plus current character config.
- Loaded saves use a split provider pinned to `save.image_config` and `save.character_image_config`.
- Fallback behavior remains app-level and is applied independently to both art and character routers.
- Reference-loss warnings still apply to scene generation because scene refs are where visual consistency degrades. Character generation may use any configured provider, but default OpenAI `gpt-image-1.5` preserves transparent-background support.

## Cost Accounting

Portrait costs must use `save.character_image_config`; scene and cover costs must use `save.image_config`.

Update cost call sites:

- Wizard initial portraits and user reference portrait processing: character config.
- Mid-story new character portraits: character config.
- Portrait regeneration, reference image style-transfer, and outfit creation: character config.
- Scene images, cover art, and cover backfill: art config.

## Settings UI Design

The Settings screen will expose separate controls while keeping existing patterns:

- Rename the current Image provider section to “Scene/cover art provider”.
- Add a “Character portrait provider” section with provider, curated model select, custom model input, base URL, API key status, and suggestions.
- Save writes both art image prefs and character image prefs atomically.
- Reset restores art to `openai / gpt-image-2` and characters to `openai / gpt-image-1.5`.
- Existing fallback controls remain shared app-level fallback controls for image generation.

## Backward Compatibility

- Existing saves without `character_image_config` load successfully because the new field has a default factory.
- Existing `state.json` without character image prefs defaults to OpenAI `gpt-image-1.5`.
- Existing art env vars and Settings values keep their current meaning for scene/cover art.
- Existing tests constructing `GameSave` without the new field should continue to pass via the model default.

## Testing

Use TDD for each behavior:

1. Autoplay waits for inline auto-read:
   - Create a PlayScreen test with auto-read enabled and a recording TTS player whose `speak()` blocks until released.
   - Trigger autoplay pick flow and verify no second pick occurs until TTS completes.
2. Autoplay waits for image terminal state:
   - Use a current node with `image_status="generating"` and verify `_auto_select_next()` does not pick until an image callback/status change occurs.
3. Config defaults and env override tests:
   - `load_config()` returns art `gpt-image-2` and character `gpt-image-1.5` by default.
   - Character-specific env vars affect only character config.
4. Split provider tests:
   - `generate_portrait()` calls the character provider.
   - `generate_scene()` calls the art provider.
5. Pipeline/wizard/portrait cost tests:
   - Portrait cost uses `character_image_config`.
   - Scene/cover cost uses `image_config`.
6. Settings/app-state tests:
   - Character image prefs round-trip.
   - Settings save/reset populate and persist the new section.

## Verification

Run targeted tests during implementation, then run:

```bash
make checkall
```
