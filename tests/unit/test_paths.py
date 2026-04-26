"""Unit tests for XDG path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from storygen.storage import paths


def test_games_root_uses_xdg_data_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    root = paths.games_root()
    assert root == tmp_path / "storygen" / "games"


def test_config_root_uses_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.config_root() == tmp_path / "storygen"


def test_game_dir_composes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    gd = paths.game_dir("abc")
    assert gd == tmp_path / "storygen" / "games" / "abc"


def test_character_portrait_path_default_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = paths.character_portrait_path("abc", "alyx")
    assert p == tmp_path / "storygen" / "games" / "abc" / "images" / "characters" / "alyx-v1.png"


def test_relative_character_portrait_path_format() -> None:
    """Relative helper returns the path format stored on Character.portrait_path."""
    assert paths.relative_character_portrait_path("alyx") == "images/characters/alyx-v1.png"
    assert (
        paths.relative_character_portrait_path("alyx", version=3) == "images/characters/alyx-v3.png"
    )


def test_character_portrait_path_explicit_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = paths.character_portrait_path("abc", "alyx", version=3)
    assert p == tmp_path / "storygen" / "games" / "abc" / "images" / "characters" / "alyx-v3.png"


def test_next_portrait_version_no_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.next_portrait_version("abc", "alyx") == 1


def test_next_portrait_version_empty_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    paths.ensure_game_dirs("abc")
    assert paths.next_portrait_version("abc", "alyx") == 1


def test_next_portrait_version_increments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    paths.ensure_game_dirs("abc")
    chars = tmp_path / "storygen" / "games" / "abc" / "images" / "characters"
    (chars / "alyx-v1.png").write_bytes(b"a")
    (chars / "alyx-v2.png").write_bytes(b"b")
    (chars / "alyx-v5.png").write_bytes(b"e")
    # Other character files must be ignored.
    (chars / "bob-v9.png").write_bytes(b"x")
    assert paths.next_portrait_version("abc", "alyx") == 6


def test_next_portrait_version_ignores_unrelated_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    paths.ensure_game_dirs("abc")
    chars = tmp_path / "storygen" / "games" / "abc" / "images" / "characters"
    (chars / "alyx.png").write_bytes(b"legacy")  # No -vN suffix
    (chars / "alyx-vbad.png").write_bytes(b"bad")  # Non-numeric version
    assert paths.next_portrait_version("abc", "alyx") == 1


def test_character_outfit_path_format(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """character_outfit_path lays out as <save>/images/characters/<char>-outfit-<id>.png."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = paths.character_outfit_path("abc", "alyx", "out123")
    assert p == (
        tmp_path / "storygen" / "games" / "abc" / "images" / "characters" / "alyx-outfit-out123.png"
    )
    assert p.as_posix().endswith("images/characters/alyx-outfit-out123.png")


def test_relative_character_outfit_path_format() -> None:
    """Relative helper returns the path format stored on CharacterOutfit.portrait_path."""
    assert (
        paths.relative_character_outfit_path("alyx", "out123")
        == "images/characters/alyx-outfit-out123.png"
    )


def test_node_image_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = paths.node_image_path("abc", "node-1")
    assert p == tmp_path / "storygen" / "games" / "abc" / "images" / "nodes" / "node-1.png"


def test_ensure_game_dirs_creates_subdirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    paths.ensure_game_dirs("abc")
    assert (tmp_path / "storygen" / "games" / "abc").is_dir()
    assert (tmp_path / "storygen" / "games" / "abc" / "images" / "characters").is_dir()
    assert (tmp_path / "storygen" / "games" / "abc" / "images" / "nodes").is_dir()


def test_tts_audio_path_includes_provider_voice_and_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    p = paths.tts_audio_path("abc", "node-1", provider="openai", voice="nova", ext="mp3")

    assert p.parent == tmp_path / "storygen" / "games" / "abc" / "audio"
    assert p.name.startswith("node-1-openai-")
    assert p.suffix == ".mp3"


def test_tts_audio_path_changes_when_voice_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    first = paths.tts_audio_path("abc", "node-1", provider="openai", voice="nova", ext="mp3")
    second = paths.tts_audio_path("abc", "node-1", provider="openai", voice="alloy", ext="mp3")

    assert first != second


def test_tts_audio_path_changes_when_provider_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    first = paths.tts_audio_path("abc", "node-1", provider="openai", voice="nova", ext="mp3")
    second = paths.tts_audio_path("abc", "node-1", provider="gemini", voice="nova", ext="mp3")

    assert first != second
    assert first.suffix == second.suffix == ".mp3"


def test_relative_tts_audio_path_matches_absolute_filename() -> None:
    rel = paths.relative_tts_audio_path("node-1", provider="openai", voice="nova", ext="mp3")

    assert rel.startswith("audio/node-1-openai-")
    assert rel.endswith(".mp3")


def test_tts_audio_path_sanitizes_provider_and_extension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    p = paths.tts_audio_path("abc", "node-1", provider="custom/provider", voice="", ext=".wav")

    assert p.name.startswith("node-1-custom-provider-")
    assert p.suffix == ".wav"
