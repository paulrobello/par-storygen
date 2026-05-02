# Enhancement Ideas for par-storygen

After completing each item remove it from this list and update CHANGELOG.md

## Gameplay & Narrative

### Story Templates / Presets
Pre-built story configurations (genre + tone + character archetypes) so users can skip the wizard and jump straight into popular setups like "Haunted Mansion Mystery" or "Space Opera Epic." Could ship 5-6 curated presets and allow user-created presets saved to `$XDG_CONFIG_HOME/storygen/presets/`.

 ### Per-Character TTS Voices
Assign distinct TTS voices to individual characters in the character library. When auto-read is enabled and dialogue appears, switch voices per speaker. Store voice assignments in `LibraryCharacter` and pass character tags to the TTS layer.

### Story Tags / Bookmarks
Let players tag nodes with custom labels ("plot twist," "favorite scene," "scary part") for quick navigation via the graph screen. Tags persist in the save file as a `dict[str, list[str]]` mapping node IDs to user labels.

### Narrative Recap / "Previously On..."
Generate a short summary of the last N beats when resuming a saved game (or on demand via keybinding). The `build_summary_agent` already exists for cover blurbs — extend it to produce "previously on" recaps weighted toward recent events.

### Character Relationship Tracking
Track relationships between characters (ally, rival, neutral, romantic) as the story progresses. The beat agent could maintain a relationship matrix and let the LLM evolve dynamics over time. Display relationships in the character sheet sidebar.

## Visual & Audio

### Ambient Sound / Music System
Layer background audio on top of TTS narration. Ship a few royalty-free ambient tracks (forest, dungeon, spaceship, city) or integrate with a free music API. Let the beat agent suggest mood tags that trigger audio transitions.

### Full-Color Image Rendering (kitty / iTerm2)
Detect terminal protocol support (kitty graphics, iTerm2 inline images, sixel) and render full-color images instead of half-block when available. Fall back to half-block for unsupported terminals. Rich-pixels already supports some of these protocols.

### Image Style Gallery
A settings preview screen showing the same character portrait rendered in each available image provider/style so users can compare quality and pick the best fit before committing to a full story.

### Animated Scene Transitions
Smooth fade or dissolve effect between scene images using terminal animation primitives. Could use a sequence of partial-image frames rendered in rapid succession on image swap.

## Cross-Game & Social

### Story Export to HTML / PDF
Export a completed story as a self-contained HTML file (or PDF) with inline images, narration text, and a clickable choice tree. Would make stories shareable outside the terminal. Use Jinja2 templates for HTML generation.

### Story Share Codes
Encode a compressed story tree (choices made + seed) as a short shareable code. Other users paste the code to reconstruct the same story path (regenerating images/text from the same LLM calls if cached, or re-generating if not). Uses the existing content-addressed tree as the foundation.

### Multiplayer "Round Robin" Mode
Two or more players take turns making choices, possibly with a timer per turn. Each player sees only the choices available on their turn. Could work locally (hot-seat) or via a simple file-sync mechanism.

### Community Character Library
Export/import library characters as portable JSON files that can be shared. Add a `library export --file` CLI command and `library import --file` counterpart. Extend to a future community hub if adoption grows.

## Technical & Quality of Life

### GitHub CI Pipeline
Add a GitHub Actions workflow running `make checkall` on PRs and pushes to `main`. Include pyright, ruff, pytest with coverage reporting. Current `release.yml` handles releases but there are no PR quality gates.

### Cross-Platform TTS Playback
Replace the macOS-only `afplay` subprocess with a cross-platform audio player. Options: `pygame.mixer`, `simpleaudio`, or a `ffplay` subprocess (available on all platforms via ffmpeg). Detect available backends at runtime.

### Undo Stack
Maintain an undo stack (last N choices) so users can go back without opening the full graph screen. Add a keybinding (`u`) that pops the stack and navigates to the parent node. Simple to implement given the existing tree structure.

### Keyboard Navigation Improvements
Add vim-style keybindings (j/k for up/down, Enter to select) and arrow-key navigation to all screens, not just the choice list. Especially useful for the library browser, load screen, and endings gallery.

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
Allow different LLM models for different agents — e.g., use a fast cheap model (gpt-4o-mini) for beat generation but a more capable model (gpt-4o) for character creation and illustration planning. Add per-agent model overrides in settings.

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

### Choice Timeout with Auto-Pick
Optional per-beat choice timer — if the user doesn't pick within N seconds, auto-select (random or "best" as determined by a lightweight LLM call). Adds urgency and immersion. Disabled by default.

## Data & Storage

### Save Compression
Compress save files (gzip or zstd) to reduce disk usage, especially for image-heavy stories. Transparently decompress on load. Could reduce save sizes by 60-80% for text-heavy stories.

### Save Migration Framework
The `save.py` migration stub is currently unused. Formalize a versioned migration system so future schema changes (new fields, renamed models) are handled gracefully across all existing saves.

### Cloud Sync / Backup
Optional sync of save files and character library to cloud storage (S3, GCS, or a simple REST endpoint). Would enable playing across multiple machines. Use the existing XDG paths as the sync root.

### Save Metadata Search
Add search/filter to the load screen — filter by theme, character names, date range, or completion status. Index save metadata on first load for fast filtering.

## Monetization & Distribution

### PyPI Package
Package for PyPI distribution (`pip install par-storygen`). Requires cleaning up the CLI entry point, adding proper metadata, and potentially vendoring or documenting optional dependencies (image providers, TTS).

### Homebrew Formula
Create a Homebrew formula for macOS users. Bundle Python + dependencies so users don't need to manage Python versions. Could use `pyinstaller` or `nix` for the binary build.

### Docker Image
Ship a Docker image with TUI access via `docker run -it`. Useful for running on servers or in cloud environments. Mount XDG dirs as volumes for persistence.

---

## Completed

### Dynamic Difficulty / Pacing Control
*Completed 2026-05-02.* Three-level pacing control (slow / moderate / fast) added to the wizard LENGTH step. Slow = 4-6 paragraph narration, 2 weighty choices. Fast = 1-3 paragraph narration, 3-5 frequent choices. Moderate = current defaults. Escalation thresholds scale per pacing level. Default configurable in Settings. Backward-compatible with existing saves.

---

*Ideas generated on 2026-04-26. Priority and feasibility vary — pick what excites you.*
