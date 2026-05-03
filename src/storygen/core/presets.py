from __future__ import annotations

import tomllib
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from storygen.core.models import NarrationStyle, Pacing, ReaderLevel
from storygen.storage import paths


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


def save_custom_preset(preset: StoryPreset) -> Path:
    """Write a preset as TOML to the custom presets directory."""
    d = paths.presets_dir()
    slug = preset.name.lower().replace(" ", "_")[:48]
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
