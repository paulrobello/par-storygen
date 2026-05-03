# Story Book Export — Design Spec

**Date:** 2026-05-01
**Status:** Implemented

## Summary

Add an "Export Book" feature that, when the player reaches a story ending, generates a standalone HTML book reader. The reader traces the player's path from root to the ending node, presenting each beat as a chapter in a paginated, interactive reader with light/dark themes, TTS audio playback, auto-read mode, and 3D page-turn animations.

## Trigger

- An "Export Book" binding appears on `PlayScreen` only when `current_node.is_ending == True`
- Keybinding: `x` (Export Book)
- Visible alongside the existing "The End" pyfiglet banner

## Export Flow

1. Walk `path_from_root(save, ending_node_id)` to collect all `StoryNode` objects in order (root first)
2. Use default save directory `~/Desktop/<sanitized_title>_Book/` (auto-created if missing; appends ` (N)` suffix if already exists)
3. Create output directory with `images/` and `audio/` subdirectories
4. Copy scene images (`images/nodes/<id>.png`) → `images/<id>.png` for nodes that have them
5. Copy TTS audio files (resolved via `node.tts_audio_path`) → `audio/<basename>` for nodes that have them
6. Render Jinja2 template with collected data, write `index.html`
7. Open in default browser via `webbrowser.open()`
8. Show toast notification with export path

## Output Structure

```
~/Desktop/<Story_Title>_Book/
├── index.html
├── images/
│   ├── node-abc123.png        # Scene illustrations
│   └── ...
└── audio/
    ├── node-abc123-ollama-a1b2c3.mp3
    └── ...
```

## HTML Book Reader

### Navigation

- Previous / Next buttons in a fixed bottom bar
- Left/Right arrow key support
- Chapter counter: "Chapter N of M" in top bar
- Linear progress bar (position indicator)

### 3D Page-Turn Animation

- CSS 3D perspective transform on page transitions
- Forward navigation: current page flips/rotates out to the left, new page rotates in from the right
- Backward navigation: reverse direction
- Use `transform: rotateY()` with `perspective` and `transform-style: preserve-3d`
- Duration: ~400ms with ease-in-out timing
- Reduced-motion preference: falls back to a simple fade

### Auto-Read Mode

- Play/pause toggle button in bottom bar
- When active:
  - If current page has audio: autoplay TTS, advance on audio `ended` event
  - If current page has no audio: wait `auto_read_delay` seconds (default 3s), then advance
  - Stops automatically at the last page
- Speed control: configurable delay for non-audio pages

### Theme

- Dark mode (default): deep navy backgrounds (`#1a1a2e`, `#16213e`, `#0f3460`) with warm red accent (`#e94560`), light text
- Light mode: warm white/cream backgrounds, navy text, same accent color
- Toggle in top bar, persisted via `localStorage`
- CSS custom properties for all theme colors — single swap point

### Audio Playback

- Per-page audio player (visible only when `audio_url` is not null)
- Custom player: play/pause button, seek bar, current/total time display
- When auto-read is on: audio autoplays on page entry
- Audio element hidden from page when no audio exists — no disabled controls shown

### Content Per Page

- Chapter heading ("Chapter N"), subheading for major beats
- The choice text that led to this beat, shown as italic label above narration (None for root)
- Scene illustration (if `image_url` exists), centered, max-width constrained
- Narration text in serif font (Georgia), comfortable reading width (~680px), generous line-height
- "The End" marker on the final page

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `src/storygen/export/__init__.py` | Package init, re-exports `export_book` |
| `src/storygen/export/book.py` | `export_book(save, ending_node_id) -> Path` main function |
| `src/storygen/export/template.html` | Jinja2 HTML template for the book reader |

### Modified Files

| File | Change |
|------|--------|
| `src/storygen/screens/play.py` | Add "Export Book" binding (key `x`), action method, `check_action` gating on `is_ending` |
| `pyproject.toml` | Add `jinja2` dependency |

### Template Data Contract

```python
@dataclass
class BookPage:
    chapter: int              # 1-based index
    narration: str            # HTML-escaped narration text
    choice_text: str | None   # choice that led here (None for root)
    image_url: str | None     # relative path "images/node-abc.png"
    audio_url: str | None     # relative path "audio/node-abc-xxx.mp3"
    is_ending: bool
    is_major: bool

# Template context:
{
    "title": str,
    "pages": list[BookPage],
    "has_any_audio": bool,
    "auto_read_delay": int,    # default 3
    "total": int,              # total number of pages
}
```

### Key Implementation Details

- `export_book()` is a synchronous function; PlayScreen calls it via `asyncio.to_thread()` inside a `@work(exit_on_error=False)` handler
- Use `tree.path_from_root()` from `storage/tree.py` to collect the path
- Resolve image/audio paths via `paths.py` helpers against the save directory
- Sanitize story title for directory name (replace special chars and spaces with underscores)
- Jinja2 template loaded via `FileSystemLoader` from `Path(__file__).parent / "template.html"`
- The template is a single self-contained HTML file — all CSS and JS inline

### Dependencies

- `jinja2` (new — add to pyproject.toml)
- `webbrowser` (stdlib)
- `shutil` (stdlib)
- `pathlib` (stdlib)

## Out of Scope

- Multiple endings in one export (single path only)
- PDF or other format export
- Re-importing or editing the exported book
- Cross-game character library integration
- Character portrait export (portraits are not included in the book output)
- Table of contents or chapter titles (chapters are numbered only)
