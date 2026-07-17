"""Story presets / templates — curated and user-saved.

Loads bundled TOML presets from package resources and custom presets from
``$XDG_CONFIG_HOME/storygen/presets/``. The wizard's "Load Preset" action
reads from this module; "Save as Preset" writes a custom preset via
:func:`save_preset`, which sanitizes the filename slug (SEC-105) so a
user-supplied name cannot escape the presets directory via path traversal.
"""

from __future__ import annotations

import re
import tomllib
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from storygen.core.models import NarrationStyle, Pacing, ReaderLevel
from storygen.storage import paths

# SEC-105: keep only filesystem-safe characters in a preset filename slug.
# Anything outside [a-z0-9_.-] is replaced with ``_`` so a user-facing name
# like ``../evil`` cannot escape the presets directory via path traversal.
_SLUG_INVALID = re.compile(r"[^a-z0-9_.-]")


class StoryPreset(BaseModel):
    name: str
    description: str
    theme: str
    tone_preset: str = "serious"
    tone_descriptor: str = ""
    narration_style: NarrationStyle = "third_person"
    art_style: str = "children's story book"
    target_major_beats: int = 5
    reader_level: ReaderLevel = "ages_11_15"
    pacing: Pacing = "moderate"
    characters: str = ""


def load_curated_presets() -> list[StoryPreset]:
    """Load presets bundled with the package."""
    presets_dir = pkg_files("storygen.presets")
    results: list[StoryPreset] = []
    try:
        items = presets_dir.iterdir()
    except (TypeError, FileNotFoundError, AttributeError):
        return results
    for item in items:
        name = item.name if hasattr(item, "name") else str(item)
        if not name.endswith(".toml"):
            continue
        try:
            data = tomllib.loads(
                item.read_text(encoding="utf-8")
                if hasattr(item, "read_text")
                else Path(str(item)).read_text(encoding="utf-8")
            )
            results.append(StoryPreset(**data))
        except Exception:
            continue
    results.sort(key=lambda p: p.name)
    return results


def load_custom_presets() -> list[StoryPreset]:
    """Load user-created presets from ``$XDG_CONFIG_HOME/storygen/presets/``."""
    d = paths.presets_dir()
    results: list[StoryPreset] = []
    for f in sorted(d.glob("*.toml")):
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
            results.append(StoryPreset(**data))
        except Exception:
            continue
    return results


def load_all_presets() -> list[StoryPreset]:
    """Return curated + custom presets, curated first."""
    return load_curated_presets() + load_custom_presets()


def _sanitize_slug(name: str) -> str:
    """Reduce ``name`` to a filesystem-safe slug for the preset filename.

    SEC-105: the preset name is user-facing display text and can contain any
    character. The on-disk filename must stay inside the presets directory, so
    we keep only ``[a-z0-9_.-]`` (matching the convention in
    :mod:`storygen.storage.paths`), strip leading ``-``/``.`` (CLI-flag / glob
    hygiene), and fall back to ``"preset"`` if nothing safe remains.
    """
    slug = _SLUG_INVALID.sub("_", name.lower().replace(" ", "_"))[:48]
    slug = slug.lstrip("-.")
    return slug or "preset"


def save_custom_preset(preset: StoryPreset) -> Path:
    """Write a preset as TOML to the custom presets directory."""
    d = paths.presets_dir()
    slug = _sanitize_slug(preset.name)
    path = d / f"{slug}.toml"
    data: dict[str, Any] = preset.model_dump()
    lines: list[str] = []
    for key, val in data.items():
        if isinstance(val, str):
            escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(val, bool):
            lines.append(f"{key} = {'true' if val else 'false'}")
        elif isinstance(val, (int, float)):
            lines.append(f"{key} = {val}")
        elif isinstance(val, list):
            lines.append(f"{key} = {val!r}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
