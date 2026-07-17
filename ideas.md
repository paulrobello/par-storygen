# Enhancement Ideas for par-storygen

After completing each item remove it from this list and update CHANGELOG.md

## Gameplay & Narrative

### Per-Character TTS Voices
Assign distinct TTS voices to individual characters in the character library. When auto-read is enabled and dialogue appears, switch voices per speaker. Store voice assignments in `LibraryCharacter` and pass character tags to the TTS layer.

### Story Tags / Bookmarks
Let players tag nodes with custom labels ("plot twist," "favorite scene," "scary part") for quick navigation via the graph screen. Tags persist in the save file as a `dict[str, list[str]]` mapping node IDs to user labels.

## Visual & Audio

### Ambient Sound / Music System
Layer background audio on top of TTS narration. Ship a few royalty-free ambient tracks (forest, dungeon, spaceship, city) or integrate with a free music API. Let the beat agent suggest mood tags that trigger audio transitions.

### Animated Scene Transitions
Smooth fade or dissolve effect between scene images using terminal animation primitives. Could use a sequence of partial-image frames rendered in rapid succession on image swap.

## Cross-Game & Social

### Story Share Codes
Encode a compressed story tree (choices made + seed) as a short shareable code. Other users paste the code to reconstruct the same story path (regenerating images/text from the same LLM calls if cached, or re-generating if not). Uses the existing content-addressed tree as the foundation.

### Multiplayer "Round Robin" Mode
Two or more players take turns making choices, possibly with a timer per turn. Each player sees only the choices available on their turn. Could work locally (hot-seat) or via a simple file-sync mechanism.

## Technical & Quality of Life

### Undo Stack
Maintain an undo stack (last N choices) so users can go back without opening the full graph screen. Add a keybinding (`u`) that pops the stack and navigates to the parent node. Simple to implement given the existing tree structure.

### Offline / Air-Gap Mode
Detect when no network is available and gracefully degrade: use only Ollama providers, disable image generation if no local provider is configured, and show a clear "offline mode" banner. Store this state and skip network-dependent UI options.

### Story Statistics Dashboard
Add a stats screen showing: total words generated, play time, choices made, unique endings found, total images generated, total API cost, characters encountered, tree depth and breadth. Aggregate across all saves for an all-time view.

### Auto-Save Checkpoints
Periodically auto-save in-progress stories (every N beats or on a timer) in addition to the explicit save on ending. Protects against unexpected crashes. Store as `.autosave` alongside the main save and offer recovery on next launch.

### Search Within Story
Add a `/` keybinding during gameplay to search narration text across all visited nodes. Highlight matches and allow jumping to the matching beat. Useful for revisiting clues or favorite passages in longer stories.

### Configurable Keybindings
Allow users to remap keybindings via a config file (`$XDG_CONFIG_HOME/storygen/keybindings.toml`). Start with the play screen (choice keys, undo, graph, endings, etc.) and extend to all screens.

## LLM & AI Enhancements

### Multi-Model Pipeline
*Partially done (verified 2026-07-17).* Image generation supports per-task model selection: `STORYGEN_IMAGE_MODEL` for scenes and a separate `STORYGEN_CHARACTER_IMAGE_MODEL` for portraits. **Remaining:** per-agent overrides for the *text* LLM — e.g. a fast/cheap model for beat generation and a more capable model for character creation and illustration planning — all text agents currently share one `STORYGEN_TEXT_MODEL`.

### Prompt Customization
Expose the system prompts (or prompt templates) as user-editable files in `$XDG_CONFIG_HOME/storygen/prompts/`. Power users can tweak tone, style, or add constraints without modifying source code.

### Streaming Beat Text
Stream the narration text token-by-token as the LLM generates it (like ChatGPT), instead of waiting for the full beat to complete. The `StoryPanel` widget already supports `write()` — wire it to a streaming agent response.

### Story Consistency Checker
Run a background consistency pass every N beats that checks for contradictions (character traits, plot points, world rules) and either warns the user or feeds corrections back into the next beat prompt. Could use a separate LLM call with a "consistency audit" prompt.

### Reader Feedback Loop
After each beat, optionally prompt the reader to rate the narration (1-5 stars or thumbs up/down). Feed low-rated beats into a fine-tuning dataset or use ratings to adjust prompt parameters dynamically. Store ratings per node in the save file.

## Accessibility

### Screen Reader Support
Ensure all widgets provide proper accessibility labels via Textual's `COMPAT_CLASSES` and `tooltip` system. Test with VoiceOver / Orca. Add ARIA-like descriptions to image panels, choice lists, and the character sheet.

### High-Contrast / Colorblind Themes
Ship alternate TUI color themes optimized for colorblind users and high-contrast preferences. Let users switch themes from settings.

### Adjustable Text Speed
Add a configurable text-reveal speed for the narration panel (instant, slow, medium, fast typewriter effect). Some users prefer dramatic reveal; others want instant text. Persist preference in app state.

## Data & Storage

### Save Compression
Compress save files (gzip or zstd) to reduce disk usage, especially for image-heavy stories. Transparently decompress on load. Could reduce save sizes by 60-80% for text-heavy stories.

### Cloud Sync / Backup
Optional sync of save files and character library to cloud storage (S3, GCS, or a simple REST endpoint). Would enable playing across multiple machines. Use the existing XDG paths as the sync root.

### Save Metadata Search
Add search/filter to the load screen — filter by theme, character names, date range, or completion status. Index save metadata on first load for fast filtering.

## Monetization & Distribution

### Homebrew Formula
Create a Homebrew formula for macOS users. Bundle Python + dependencies so users don't need to manage Python versions. Could use `pyinstaller` or `nix` for the binary build.

### Docker Image
Ship a Docker image with TUI access via `docker run -it`. Useful for running on servers or in cloud environments. Mount XDG dirs as volumes for persistence.

---

*Ideas generated on 2026-04-26. Priority and feasibility vary — pick what excites you.*
