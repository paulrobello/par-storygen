# par-storygen

## Table of Contents

* [About](#about)
* [Features](#features)
   * [Core Capabilities](#core-capabilities)
   * [Advanced Features](#advanced-features)
   * [Technical Excellence](#technical-excellence)
* [Screenshots](#screenshots)
* [Prerequisites](#prerequisites)
* [Installing](#installing)
* [Command line arguments](#command-line-arguments)
* [Environment Variables](#environment-variables)
* [Data locations](#data-locations)
* [Running par-storygen](#running-par-storygen)
* [Choosing a text model](#choosing-a-text-model)
   * [OpenAI](#openai-text)
   * [OpenRouter](#openrouter)
   * [Ollama (local)](#ollama-text)
* [Choosing an image model](#choosing-an-image-model)
   * [OpenAI](#openai-image)
   * [Google Gemini](#google-gemini)
   * [Z.AI GLM-image](#zai-glm-image)
   * [Ollama (local)](#ollama-image)
   * [Fallback provider](#fallback-provider)
* [Character library](#character-library-exporting-and-importing)
* [Replay and endings](#replay-and-endings)
* [Branch prefetch](#branch-prefetch)
* [Character outfits](#character-outfits)
* [Text-to-speech](#text-to-speech)
* [Auto-play](#auto-play)
* [Export book](#export-book)
* [Contributing](#contributing)
* [Roadmap](#roadmap)

![PyPI - Python Version](https://img.shields.io/badge/python-3.13-blue)
![Runs on Linux | MacOS | Windows](https://img.shields.io/badge/runs%20on-Linux%20%7C%20MacOS%20%7C%20Windows-blue)
![Arch x86-64 | ARM | AppleSilicon](https://img.shields.io/badge/arch-x86--64%20%7C%20ARM%20%7C%20AppleSilicon-blue)
![PyPI - License](https://img.shields.io/pypi/l/mit)

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/probello3)

## About
par-storygen is a TUI (Text UI) choose-your-own-adventure powered by configurable LLMs. The application was built with [Textual](https://textual.textualize.io/) and [Rich](https://github.com/Textualize/rich).
A configurable LLM (via pydantic-ai) drives theme, characters, narration, and choices; image providers render portraits and scene illustrations using per-character reference portraits for visual consistency. Game state is a content-addressed tree persisted as JSON — walk the same choices twice and the game replays byte-for-byte. It runs on all major OS's including Windows, macOS, and Linux.

## Features

### Core Capabilities
- **Multi-Provider Text**: OpenAI, OpenRouter, and Ollama (all OpenAI-compatible) with per-save provider pinning
- **Multi-Provider Images**: OpenAI (ref-aware), Gemini (ref-aware), Z.AI (text-to-image), and Ollama (local) with automatic fallback
- **Interactive Wizard**: 8-step story setup — theme, tone, narration style, art style, length, reader level, characters, and confirmation
- **Half-Block Inline Art**: Scene illustrations rendered directly in the terminal using reference portraits for character consistency
- **Content-Addressed Tree**: Every choice is cached; replaying the same path returns byte-for-byte identical results
- **Save/Resume**: Full game state persistence with `--resume` flag to pick up where you left off

### Advanced Features
- **Branch Prefetch**: Background-generates pending choices while you read, for instant picks
- **Text-to-Speech**: Read narration aloud via OpenAI, ElevenLabs, Deepgram, Gemini, or Kokoro with provider/voice-aware audio caching
- **Auto-Play**: Press `a` to auto-advance with random choices, waiting for images and TTS before continuing
- **Character Library**: Export characters from finished stories and re-import with optional AI-powered backstory adaptation
- **Character Outfits**: Define multiple looks per character and switch between them mid-story
- **Endings Gallery**: Card-based view of every ending reached, with jump-to-node navigation
- **Branch Replay**: Read-only slideshow of any path from root to an explored node
- **Story Graph**: Full tree view with marker legend, current-node arrow, and unexplored-choice leaves
- **Reference Images**: Supply your own character images as portrait anchors for ref-aware providers
- **Reader Levels**: Vocabulary and complexity controls for ages 0-5, 6-10, 11-15, or 15+
- **Settings Persistence**: In-app Settings screen for provider defaults, art toggle, streaming, prefetch, TTS, and auto-play options
- **Export Book**: Export any story path as a standalone HTML book reader with 3D page turns, audio player, and auto-read

### Technical Excellence
- **Async Architecture**: Non-blocking pipeline with concurrent illustration and portrait generation
- **Type Safety**: Fully typed Python 3.13 codebase with strict pyright mode
- **XDG-Compliant Paths**: Config and data stored per platform conventions
- **Atomic Persistence**: All file writes use `.tmp` + `os.replace` for crash safety
- **Cost Tracking**: Per-save image cost and token usage with per-model call counts
- **Prompt Caching**: Static system prompt content for optimal API cache hit rates

## Screenshots

**Splash & Main Menu**

![Splash screen](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_splash.png)
![Main menu](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_main_menu.png)

**Settings** — Configure text and image providers, art toggles, streaming, and prefetch options. Preferences persist across sessions.

![Settings screen](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_settings.png)

**New Story Wizard** — An 8-step guided setup for theme, tone, narration style, art style, length, reader level, and characters (with library import). See the [full wizard walkthrough](docs/NEW_STORY_WIZARD.md).

![Wizard theme step](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_wizard_1_theme.png)

**Load Story** — Browse and resume existing saves.

![Load story screen](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_load_story.png)

**Gameplay** — The main play screen shows the scene illustration (half-block inline art) on the left, narrative text in the center, and the character roster on the right. Numbered choices appear at the bottom.

![Story play screen](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_story_panel.png)
![Beat generation](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_story_generate.png)

**Character Portraits** — Press `p` to view full portraits for every character in the current scene. High-res zoom available for ref-aware providers.

![Character roster](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_story_roster.png)


**Story Graph** — Press `g` for a full tree view with marker legend, current-node arrow, and unexplored-choice leaves. Press `r` on any node for branch replay.

![Story graph](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_story_graph.png)

**Character Catalog** — A scrollable grid of exported characters from across all your stories. Each card shows the portrait thumbnail, name, and source story. Import any character into a new story (keep as-is or adapt backstory to the new theme).

![Character catalog](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_char_catalog.png)

**High-res** versions of images are available

![High-res portrait](https://raw.githubusercontent.com/paulrobello/par-storygen/main/screenshots/sc_char_highres.png)

## Prerequisites

### For running
* Install Python 3.13 or newer
  * [https://www.python.org/downloads/](https://www.python.org/downloads/) has installers for all versions
  * On Windows the [Scoop](https://scoop.sh/) tool makes it easy to install and manage things like python
    * Install Scoop then do `scoop install python`

### For development
* Install [uv](https://docs.astral.sh/uv/)
* Install GNU Compatible Make command
  * On Windows if you have scoop installed you can install make with `scoop install make`

## Installing

### Installing uv
If you don't have uv installed you can run the following:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Install from PyPI with uv
```bash
uv tool install par-storygen
storygen
```

### Install from PyPI with pip
```bash
pip install par-storygen
storygen
```

### Source install from GitHub
```bash
git clone https://github.com/paulrobello/par-storygen
cd par-storygen
make setup
```

## Command line arguments
```
usage: storygen run [--resume]

par-storygen -- AI-driven TUI choose-your-own-adventure.

options:
  -r, --resume   Re-open last-played save
```

## Environment Variables

### Variables are loaded in the following order, last one to set a var wins
* HOST Environment
* `.env` file in project root
* par-storygen Settings Screen

### Text provider variables
* `OPENAI_API_KEY` — OpenAI API key
* `OPENROUTER_API_KEY` — OpenRouter API key
* `STORYGEN_TEXT_PROVIDER` — `openai` (default), `openrouter`, or `ollama`
* `STORYGEN_TEXT_MODEL` — Model identifier (default: `gpt-4o-mini`)
* `STORYGEN_TEXT_BASE_URL` — Override base URL for the text provider

### Image provider variables
* `GEMINI_API_KEY` — Google Gemini API key
* `ZAI_API_KEY` — Z.AI API key
* `STORYGEN_IMAGE_PROVIDER` — Scene/cover art provider: `openai` (default), `gemini`, `zai`, or `ollama`
* `STORYGEN_IMAGE_MODEL` — Scene/cover art model identifier (default: `gpt-image-2`)
* `STORYGEN_IMAGE_BASE_URL` — Override base URL for the scene/cover art provider
* `STORYGEN_IMAGE_API_KEY` — Override API key for the scene/cover art provider
* `STORYGEN_CHARACTER_IMAGE_PROVIDER` — Character portrait provider: `openai` (default), `gemini`, `zai`, or `ollama`
* `STORYGEN_CHARACTER_IMAGE_MODEL` — Character portrait model identifier (default: `gpt-image-1.5` for transparent-background support)
* `STORYGEN_CHARACTER_IMAGE_BASE_URL` — Override base URL for the character portrait provider
* `STORYGEN_CHARACTER_IMAGE_API_KEY` — Override API key for the character portrait provider

See [`.env.example`](./.env.example) for the full list.

## Data locations

par-storygen uses the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/) via the `xdg-base-dirs` library. Override the defaults by setting `XDG_DATA_HOME` or `XDG_CONFIG_HOME`.

**Default data directory** (`$XDG_DATA_HOME/storygen/`):

| Platform | Default path |
|----------|-------------|
| macOS | `~/.local/share/storygen/` |
| Linux | `~/.local/share/storygen/` |
| Windows | `%APPDATA%\storygen\` |

Within the data directory:

- `games/<uuid>/` — one subdirectory per save, containing `game.json` and portrait/scene images
- `library/<uuid>/` — one subdirectory per exported character, containing `character.json` and `portrait.png`

**Config state file** (`$XDG_CONFIG_HOME/storygen/state.json`) stores provider preferences, art settings, and wizard defaults:

| Platform | Default path |
|----------|-------------|
| macOS | `~/.config/storygen/state.json` |
| Linux | `~/.config/storygen/state.json` |
| Windows | `%APPDATA%\storygen\state.json` |

## Running par-storygen

```bash
make run
```

Or directly:
```bash
uv run storygen
```

Resume last game:
```bash
make resume
# or
uv run storygen run --resume
```

## Choosing a text model

par-storygen supports three text-LLM providers, all routed through pydantic-ai's OpenAI-compatible `OpenAIChatModel`.

There are two ways to select the provider and model:

1. **Environment variables** (best for one-off runs, CI, or temporary overrides) — `STORYGEN_TEXT_PROVIDER`, `STORYGEN_TEXT_MODEL`, and optionally `STORYGEN_TEXT_BASE_URL`. See [`.env.example`](./.env.example) for the full list.
2. **Settings screen** (persisted across sessions) — open the app, hit `Settings` from the main menu, and edit the "Text provider" block. Saved prefs live in `$XDG_CONFIG_HOME/storygen/state.json`.

**Priority order:** real environment variables > `.env` file > Settings-saved prefs > hardcoded default (`openai` / `gpt-4o-mini`).

### OpenAI
Set `OPENAI_API_KEY`. Known-good models: **`gpt-4o-mini`** (default — fast, cheap, reliable structured output), **`gpt-4o`** (higher-quality prose), **`gpt-4.1-mini`** (newer, balanced). Billing runs through api.openai.com.

### OpenRouter
Set `OPENROUTER_API_KEY` and `STORYGEN_TEXT_PROVIDER=openrouter`. OpenRouter routes to dozens of frontier models under a single key. Known-good models: **`anthropic/claude-3.5-sonnet`** (excellent structured output), **`meta-llama/llama-3.3-70b-instruct`** (open-weight, very cheap). Full catalog at [openrouter.ai/models](https://openrouter.ai/models). Keep the `<vendor>/<model>` slash form.

### Ollama
Set `STORYGEN_TEXT_PROVIDER=ollama` and run `ollama serve` locally (default: `http://localhost:11434`). No API key required. Known-good models: **`llama3.3:70b`** (good narration if you have the VRAM), **`qwen2.5:32b-instruct`** (lighter, faster). The model string must match the Ollama tag exactly. For remote Ollama, set `STORYGEN_TEXT_BASE_URL=http://<host>:11434/v1`.

**Note:** Each save pins its own `text_config`. Changing the provider in Settings only affects new stories — existing saves keep what they were created with.

## Choosing an image model

par-storygen supports four image-gen providers. Only OpenAI and Gemini support *reference images* — the pattern used to keep characters visually consistent across scenes. Z.AI and Ollama are text-to-image only, so character consistency will drift.

Scene/cover art and character portraits are configured separately:

- **Scene/cover art** uses `STORYGEN_IMAGE_PROVIDER`, `STORYGEN_IMAGE_MODEL`, `STORYGEN_IMAGE_BASE_URL`, and `STORYGEN_IMAGE_API_KEY`. The hardcoded default is OpenAI **`gpt-image-2`**.
- **Character portraits** use `STORYGEN_CHARACTER_IMAGE_PROVIDER`, `STORYGEN_CHARACTER_IMAGE_MODEL`, `STORYGEN_CHARACTER_IMAGE_BASE_URL`, and `STORYGEN_CHARACTER_IMAGE_API_KEY`. The hardcoded default is OpenAI **`gpt-image-1.5`**, chosen because portrait generation requests transparent backgrounds.

There are two ways to select image providers and models:

1. **Environment variables** — use the scene/cover `STORYGEN_IMAGE_*` variables and/or the portrait-specific `STORYGEN_CHARACTER_IMAGE_*` variables. See [`.env.example`](./.env.example).
2. **Settings screen** (persisted across sessions) — edit the "Image provider" block for scene/cover art and the "Character portrait provider" block for portraits.

**Priority order for each image config:** real environment variables > `.env` file > Settings-saved prefs > hardcoded defaults (`openai` / `gpt-image-2` for scene/cover art, `openai` / `gpt-image-1.5` for character portraits).

### OpenAI
Set `OPENAI_API_KEY`. Supports reference images natively via `images.edit` — each scene folds in the featured characters' portraits so faces stay consistent. Known-good models: **`gpt-image-2`** (default for scene/cover art), **`gpt-image-1.5`** (default for transparent-background character portraits), **`gpt-image-1`** (older, cheaper — untested with current `gpt-image-2`-tuned scene prompts). Docs: [platform.openai.com/docs/guides/images](https://platform.openai.com/docs/guides/images).

### Google Gemini
Set `GEMINI_API_KEY` and `STORYGEN_IMAGE_PROVIDER=gemini`. Supports up to 14 reference images per call. Known-good models: **`gemini-3.1-flash-image-preview`** (Nano Banana 2, $0.067/1K image tokens), **`gemini-3-pro-image-preview`** (Nano Banana Pro, $0.134/image). Leave `STORYGEN_IMAGE_BASE_URL` blank for Gemini. Docs: [ai.google.dev/gemini-api/docs/image-generation](https://ai.google.dev/gemini-api/docs/image-generation).

### Z.AI GLM-image
Set `ZAI_API_KEY` and `STORYGEN_IMAGE_PROVIDER=zai`. Text-to-image only — no reference-image support. Price: $0.015/image. Known-good model: **`glm-image`**. Docs: [docs.z.ai](https://docs.z.ai).

### Ollama
Set `STORYGEN_IMAGE_PROVIDER=ollama` and run `ollama serve` locally. No API key required. macOS-only as of 2026-04, requires server **≥ 0.13.3**. No reference-image support. Known-good models: **`x/z-image-turbo`** (fastest), **`x/flux2-klein:4b`**, **`x/flux2-klein:9b`** (higher quality, more VRAM). For remote Ollama, set `STORYGEN_IMAGE_BASE_URL=http://<host>:11434/v1/`.

### Fallback provider
Settings lets you pick a secondary image provider that kicks in when the primary fails. Each fallback trip fires a toast. Useful combos: OpenAI primary + Gemini fallback (both ref-supporting). Same-provider fallbacks are ignored.

**Note:** Each save pins both `image_config` (scene/cover art) and `character_image_config` (portraits). Changing either image provider in Settings only affects new stories.

## Character library: exporting and importing

par-storygen keeps a cross-game character library at `$XDG_DATA_HOME/storygen/library/` — one subdirectory per exported character holding metadata plus its portrait. Characters from finished (or in-progress) stories can be re-used in new stories without regenerating the portrait, saving both token cost and wall time.

### Export
From a game's **Portraits** screen, press the **Export** button next to any character. The character's name, backstory, personality, physical description, portrait, and the exact portrait prompt are copied into the library. Re-exporting the same character creates a separate library entry — use the Library Browser to clean up.

### Import
During the wizard's **CHARACTERS** step, press `l` to open the Library Browser. Pick a character, then choose:

- **Keep as-is** — added to your new story unchanged. Portrait PNG is *copied* (no image-provider API calls).
- **Adapt to theme** — an LLM rewrites **only** the backstory to fit your new story's theme. Name, personality, and physical description are preserved so the existing portrait still matches.

### Delete + sort
The Library Browser has per-entry **Delete** buttons with confirmation. Press `s` to toggle sort between **newest-first** (default) and **alphabetical**.

## Replay and endings

Once you've played through to one or more endings, two read-only views let you revisit the journey.

### Endings gallery (`e` from PlayScreen)
Press `e` to open a card per ending you've reached. Each card shows the scene image, a narration excerpt, and the path of choices you took. Press **Jump** on any ending to set the playhead to that node.

The `e` binding is hidden when no endings have been reached yet.

### Branch replay (`r` from GraphScreen)
Open the graph (`g` from PlayScreen), highlight any explored node, and press `r` to walk through every beat from root to that node. Use `space`/`right`/`n` to advance, `left`/`p` to go back, `j` to jump to live play at the current step, and `escape` to exit.

Replay is read-only — no regeneration, no LLM calls.

## Branch prefetch

While you're reading a beat, par-storygen can background-generate the next beats for each pending choice. When you pick, the next beat appears instantly (no LLM call) — assuming the prefetch finished in time.

### Enabling
Open Settings and toggle:
- **Enable branch prefetch** — turns on background generation. Off by default (spends tokens up-front for paths you may never pick).
- **Prefetch scene images too** — also runs scene-image generation for each prefetched beat. Off by default and disabled unless prefetch + global art are both on.

### What gets generated
For each pending choice from the current beat:
- Beat text (always, when prefetch is on).
- Illustration plan (always — cheap, lets you press `i` later).
- Scene image (only when "Prefetch scene images too" is on).

### Behavior notes
- **Sibling prefetches keep running after you pick.** They populate `save.nodes`, so alternate branches are free cache hits.
- **Failures are silent.** If a provider is down, you only see an error if you pick a choice whose prefetch failed (then live generation retries).
- **Settings take effect on the next beat.** Toggle any time; in-flight prefetches finish, future ones honor the new state.

## Character outfits

Define multiple looks for a single character and switch between them at will. Each outfit is its own portrait, used as the reference image for scene generation so your character appears in the picked outfit across subsequent beats.

### Creating an outfit
From PlayScreen, press `p` to open Portraits. For any character:
1. Click **Add outfit**.
2. Give it a short name (e.g. "ballroom gown", "armored", "swimwear").
3. Write a one-sentence description (e.g. "wearing a flowing red gown with gold trim").
4. Press **Generate**. The new outfit is generated using the character's existing physical description PLUS your outfit description.

Outfit thumbnails appear in a row under the character's main portrait.

### Switching and deleting
Click any outfit thumbnail for a Set as current / Delete / Cancel menu. Setting an outfit updates the character's active portrait and makes scene generation use that outfit as the reference from now on.

The main (base) portrait is preserved. Press **Revert to base** (visible only when an outfit is active) to switch back. Deleting the currently-active outfit auto-reverts to base first.

### Notes
- Outfit generation uses the character portrait image provider + model + cost, same as a regular portrait.
- Image streaming is intentionally OFF for outfit generation (portraits are 5-10s — too fast for streaming to pay off).
- Library export captures only the currently-active outfit. Imported characters start with an empty `outfits` list.

## Text-to-speech

par-storygen can read narration aloud using the [par-cli-tts](https://github.com/paulrobello/par-cli-tts) library, which supports five providers: OpenAI, ElevenLabs, Deepgram, Google Gemini, and Kokoro (local).

### Setup
1. Open **Settings** from the main menu.
2. Scroll to the **Text-to-speech** section.
3. Select a provider and enter your API key.
4. Press **Refresh voices** to populate the voice dropdown, then pick a voice.
5. Optionally toggle **Auto-read** to have narration read aloud automatically after each beat.

### Playback controls (PlayScreen)

| Key | Action |
|-----|--------|
| `t` | Read aloud / pause / resume (context-dependent) |
| `T` | Restart narration from the beginning |
| `s` | Stop playback immediately |

Audio files are cached per node, provider, and voice in the save's `audio/` directory. The cache file extension follows the active TTS provider's preferred output format, so changing provider or voice generates a separate cache entry instead of replaying stale narration.

## Auto-play

Press `a` from the play screen to auto-advance the story with random choices. Auto-play:

- **Waits for the scene image** — waits until the current scene image reaches a terminal state (`done` or `failed`), then applies a 5 second viewing delay after the image is displayed (if art is enabled).
- **Waits for TTS** — if auto-read is on, waits for narration playback to finish (including through pauses) before advancing to the next random choice.
- **Stops at endings** — auto-play halts when an ending node is reached.
- **Toggle off** — press `a` again to stop at any time.

During auto-play, only `menu`, `a` (stop auto), and TTS controls (`t`/`T`/`s`) are available.

## Export book

Press `x` from the play screen when viewing an ending to export the entire story path as a self-contained HTML book. The exported book opens in your browser and includes:

- **Chapter-by-chapter navigation** with arrow keys and on-screen buttons
- **3D page-turn animation** (CSS `rotateY`) with `prefers-reduced-motion` fallback
- **Light/dark mode toggle** persisted via `localStorage`
- **Inline audio player** for chapters with TTS narration, with seek bar and time display
- **Auto-read mode** — plays each chapter's audio and advances automatically
- **Open Graph / Twitter Card meta tags** for social sharing previews
- **Scene images** copied alongside `index.html` into `~/Desktop/<Title>_Book/`

No server required — the entire book is a single HTML file with inline CSS/JS plus local image and audio assets.

## Contributing

Clone the repo and run the setup make target. Note `uv` is required.
```bash
git clone https://github.com/paulrobello/par-storygen
cd par-storygen
make setup
```

Please ensure that all pull requests are formatted with ruff, pass ruff lint and pyright.
You can run the make target **checkall** to ensure the pipeline will pass with your changes.

```bash
make checkall    # ruff format + lint + pyright + pytest
```

The easiest way to setup your environment for smooth pull requests:

With uv installed:
```bash
uv tool install pre-commit
```

From repo root:
```bash
pre-commit install
pre-commit run --all-files
```

## Roadmap

As of v0.3.0. See [CHANGELOG.md](./CHANGELOG.md) for the full release history.

### Where we are
* **Core Gameplay** — Theme wizard, beat pipeline, choice tree, caching, save/resume
* **Multi-Provider** — OpenAI, OpenRouter, Ollama for text; OpenAI, Gemini, Z.AI, Ollama for images
* **Visual Consistency** — Reference portraits, half-block inline art, character outfits
* **Cross-Game Library** — Export/import characters with optional AI backstory adaptation
* **Navigation** — Story graph, endings gallery, branch replay
* **Branch Prefetch** — Background beat generation for instant picks
* **Reader Levels** — Vocabulary and complexity controls for different age ranges
* **Text-to-Speech** — Multi-provider narration with provider/voice-aware audio caching and auto-read
* **Auto-Play** — Random-choice auto-advance with image and TTS wait gating
* **Export Book** — Standalone HTML book reader with 3D page turns, inline audio, and auto-read

### Where we're going
* Sound effects and music per scene
* Multiplayer (shared story tree)
* More image providers and art styles
* Story templates and presets
* Export stories as PDF
