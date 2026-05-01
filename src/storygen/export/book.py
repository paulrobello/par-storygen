"""Export a story path as a self-contained HTML book."""

from __future__ import annotations

import os
import re
import shutil
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from storygen.core.models import NodeId, StoryNode
from storygen.storage import paths
from storygen.storage.save import GameSave
from storygen.storage.tree import path_from_root


@dataclass
class BookPage:
    """One page in the exported book, corresponding to a single story beat."""

    chapter: int
    narration: str
    choice_text: str | None
    image_url: str | None
    audio_url: str | None
    is_ending: bool
    is_major: bool


def sanitize_title(title: str) -> str:
    """Return a filesystem-safe version of a story title with underscores."""
    safe = re.sub(r"[^A-Za-z0-9_ \-]+", "", title).strip()
    return safe.replace(" ", "_")


def unique_output_dir(base: Path) -> Path:
    """Return ``base`` or ``base (N)`` if base already exists."""
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = Path(f"{base} ({n})")
        if not candidate.exists():
            return candidate
        n += 1


def _resolve_choice_text(save: GameSave, node: StoryNode) -> str | None:
    """Look up the display text of the choice that led to this node."""
    if node.chosen_choice_id is None or node.parent_id is None:
        return None
    parent = save.nodes.get(node.parent_id)
    if parent is None:
        return None
    for choice in parent.choices:
        if choice.id == node.chosen_choice_id:
            return choice.text
    return None


def export_book(
    save: GameSave,
    ending_node_id: NodeId,
    *,
    output_dir: Path | None = None,
    open_browser: bool = True,
) -> Path:
    """Export a story path ending at *ending_node_id* as a self-contained HTML book.

    Args:
        save: The game save containing all story nodes.
        ending_node_id: The terminal node (typically an ending) to build the path to.
        output_dir: Where to write the book. Defaults to
            ``~/Desktop/<sanitized_title>_Book/``.
        open_browser: Whether to open the exported book in a web browser.

    Returns:
        The path to the output directory containing ``index.html`` and assets.
    """
    # 1. Determine output directory
    if output_dir is None:
        sanitized = sanitize_title(save.theme.title)
        base = Path.home() / "Desktop" / f"{sanitized}_Book"
        output_dir = unique_output_dir(base)

    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    audio_dir = output_dir / "audio"
    images_dir.mkdir(exist_ok=True)
    audio_dir.mkdir(exist_ok=True)

    # 2. Walk path from root to ending
    story_path = path_from_root(save, ending_node_id)
    game_base = paths.game_dir(str(save.id))

    # 3. Build BookPage list and copy assets
    pages: list[BookPage] = []
    has_any_audio = False

    for idx, node in enumerate(story_path):
        choice_text = _resolve_choice_text(save, node)

        # Copy scene image
        image_url: str | None = None
        if node.image_path and node.image_status == "done":
            src = paths.safe_join(game_base, node.image_path)
            if src.exists():
                dest = images_dir / f"{node.id}.png"
                shutil.copy2(src, dest)
                os.chmod(dest, 0o644)
                image_url = f"images/{node.id}.png"

        # Copy TTS audio
        audio_url: str | None = None
        if node.tts_audio_path:
            src = paths.safe_join(game_base, node.tts_audio_path)
            if src.exists():
                dest = audio_dir / src.name
                shutil.copy2(src, dest)
                os.chmod(dest, 0o644)
                audio_url = f"audio/{src.name}"
                has_any_audio = True

        pages.append(
            BookPage(
                chapter=idx + 1,
                narration=node.narration,
                choice_text=choice_text,
                image_url=image_url,
                audio_url=audio_url,
                is_ending=node.is_ending,
                is_major=node.is_major,
            )
        )

    # 4. Render HTML template
    template_dir = Path(__file__).resolve().parent
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("template.html")

    html = template.render(
        title=save.theme.title,
        pages=[vars(p) for p in pages],
        has_any_audio=has_any_audio,
        auto_read_delay=3,
        total=len(pages),
    )

    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    # 5. Open in browser
    if open_browser:
        webbrowser.open(index_path.as_uri())

    return output_dir
