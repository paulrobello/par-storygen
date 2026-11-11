# Migrate saved image models

Update Storygen's saved OpenAI image configurations to GPT Image 2.6 Flare without regenerating any images or making provider calls.

## What changes

New stories now default to `gpt-image-2.6-flare` for scenes, covers, and character portraits. Settings also offers `gpt-image-2.6-sunburst`. OpenAI recommends Flare as the starting point when an existing GPT Image 2 workflow already meets quality needs. Both support reference-image edits, transparent PNG portraits, and raster streaming previews. Existing sizes and quality settings remain unchanged.

The migration replaces exactly `gpt-image-2`, `gpt-image-2-2026-04-21`, and `gpt-image-1.5` in:

- `state.json`: scene and portrait provider preferences, including the scene fallback model.
- `games/*/game.json`: top-level `image_config.model` and `character_image_config.model`.

Only explicit OpenAI configurations with the default OpenAI endpoint are changed. Other providers, custom endpoints, models, environment variables, and `.env` files remain unchanged. The fallback provider uses its own default endpoint, independently of the primary endpoint. Story content, character data, cached media, timestamps, historical costs, and credentials are preserved. JSON whitespace is normalized. This command does not upgrade the story schema.

## Preview and apply

Stop every Storygen TUI and API process before applying. The migration's locks prevent concurrent migrations, not writes from a running app.

From the repository:

```bash
uv run python -m storygen.storage.migrate_image_models
uv run python -m storygen.storage.migrate_image_models --apply
```

The first command is a read-only dry run. The second writes the listed changes. Paths respect `XDG_CONFIG_HOME` and `XDG_DATA_HOME` in the command's environment. The command does not load `.env`; export any custom XDG variables first or supply `--state-file PATH --games-dir PATH` explicitly.

Each changed file gets a byte-exact, owner-only sibling backup named `.game.json.image-model-<random>.bak` or `.state.json.image-model-<random>.bak` before an atomic replacement. Backups may contain private story content or credentials, so do not share or commit them. The command prints backup paths but never file contents.

Files are checked for intervening changes before backup and again before replacement. Invalid or ambiguous JSON, linked files, existing migration locks, and changed files stop the operation. A failure can leave earlier files migrated: this is not a multi-file transaction. Keep every printed backup, inspect the failure, and rerun a dry run before retrying.

## Verify and restore

Run the dry run again after applying. It should report zero files to change. Load a saved story normally and inspect its image settings. Offline tests cover request construction and migration integrity; they do not verify account access or the visual quality of a paid generation.

To undo a migration, stop Storygen again, preserve any story progress made since migration, and restore the corresponding `.bak` file over its original JSON file. Restoring the entire backup also restores the story to its pre-migration state, so do not overwrite newer progress casually. The backup is a normal JSON file containing the original bytes.

The existing in-app cost counter is a coarse legacy estimate, not an exact GPT Image 2.6 bill. Actual charges depend on token usage and quality. This migration preserves historical totals.

## Sources

- [OpenAI model selection and parameters](https://developers.openai.com/api/docs/guides/image-prompting)
- [OpenAI image generation guide](https://developers.openai.com/api/docs/guides/image-generation)
- [OpenAI model deprecations](https://developers.openai.com/api/docs/deprecations)
