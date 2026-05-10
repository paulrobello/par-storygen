"""CharacterSheet: sidebar listing cast with portrait thumbnails and brief descriptions."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from rich.console import Group, RenderableType
from rich.text import Text
from textual.widgets import Static

from storygen.llm.models import Character
from storygen.widgets._image_util import pixels_from_image


def format_character_entry(c: Character) -> str:
    first_line_of_personality = c.personality.split(".", 1)[0]
    return f"{c.name} -- {first_line_of_personality}"


class CharacterSheet(Static):
    """Sidebar showing each character's portrait + a one-line description."""

    def __init__(self) -> None:
        super().__init__("Cast", markup=False)
        self._characters: list[Character] = []
        self._game_dir: Path | None = None

    @property
    def renderable(self) -> RenderableType:
        """Current content as a Rich renderable (for testing and inspection)."""
        return self.content  # type: ignore[return-value]

    def set_characters(self, characters: list[Character], game_dir: Path | None = None) -> None:
        self._characters = list(characters)
        self._game_dir = game_dir
        self._rebuild()

    def _rebuild(self) -> None:
        parts: list[RenderableType] = [Text("Cast", style="bold")]
        for c in self._characters:
            entry: list[RenderableType] = []
            portrait = self._load_portrait(c)
            if portrait is not None:
                entry.append(portrait)
            entry.append(Text(format_character_entry(c)))
            entry.append(Text(""))  # blank line spacer
            parts.append(Group(*entry))
        self.update(Group(*parts))

    def _load_portrait(self, c: Character) -> RenderableType | None:
        if self._game_dir is None or not c.portrait_path:
            return None
        abs_path = self._game_dir / c.portrait_path
        if not abs_path.exists():
            return None
        try:
            with Image.open(abs_path) as im:
                im = im.convert("RGBA")
                im.thumbnail((48, 24))
                return pixels_from_image(im)
        except Exception:
            return None
