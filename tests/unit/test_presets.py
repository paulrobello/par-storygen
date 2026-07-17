from __future__ import annotations

from typing import Any

import pytest

from storygen.core.presets import StoryPreset


def test_preset_defaults() -> None:
    p = StoryPreset(name="Test", description="A test", theme="A theme")
    assert p.tone_preset == "serious"
    assert p.narration_style == "third_person"
    assert p.art_style == "children's story book"
    assert p.target_major_beats == 5
    assert p.reader_level == "ages_11_15"
    assert p.pacing == "moderate"
    assert p.characters == ""


def test_preset_round_trip(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from storygen.core import presets
    from storygen.storage import paths

    monkeypatch.setattr(paths, "presets_dir", lambda: tmp_path)

    p = StoryPreset(
        name="My Preset",
        description="Desc",
        theme="Spooky",
        tone_preset="dark",
        art_style="oil painting",
        target_major_beats=10,
        characters="A witch and a cat",
    )
    path = presets.save_custom_preset(p)
    assert path.exists()

    loaded = presets.load_custom_presets()
    assert len(loaded) == 1
    assert loaded[0].name == "My Preset"
    assert loaded[0].theme == "Spooky"
    assert loaded[0].characters == "A witch and a cat"


def test_load_all_includes_curated() -> None:
    from storygen.core.presets import load_all_presets

    all_presets = load_all_presets()
    # Curated presets won't exist yet (Task 2 creates them), so just verify no crash
    assert isinstance(all_presets, list)


def test_save_custom_preset_sanitizes_traversal_name(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-105: a preset named ``../evil`` saves inside the presets dir with a
    sanitized filename — the user-supplied name is display text only and must
    never flow into the on-disk path as a traversal.
    """
    from storygen.core import presets
    from storygen.storage import paths

    monkeypatch.setattr(paths, "presets_dir", lambda: tmp_path)

    p = StoryPreset(name="../evil", description="Desc", theme="T")
    path = presets.save_custom_preset(p)
    # The file must live INSIDE the configured presets dir, not escape it.
    assert path.parent == tmp_path
    assert ".." not in path.name
    assert "/" not in path.name
    # Round-trip: load_custom_presets reads the TOML back. The display ``name``
    # is preserved verbatim; only the filename was sanitized.
    loaded = presets.load_custom_presets()
    assert len(loaded) == 1
    assert loaded[0].name == "../evil"
    assert loaded[0].theme == "T"
