"""Unit tests for XDG path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from storygen.storage import paths

# Valid canonical UUIDs (hyphenated and hex) used by tests that previously
# passed short strings like "abc" — paths.game_dir now requires UUID shape
# to prevent path traversal (SEC-003).
_GAME_ID = "12345678-1234-1234-1234-123456789012"
_GAME_ID_HEX = "123456781234123412341234567890123deadbeef"[: 32 - 4]  # any 32 hex


def test_games_root_uses_xdg_data_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    root = paths.games_root()
    assert root == tmp_path / "storygen" / "games"


def test_config_root_uses_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.config_root() == tmp_path / "storygen"


def test_game_dir_composes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    gd = paths.game_dir(_GAME_ID)
    assert gd == tmp_path / "storygen" / "games" / _GAME_ID


def test_character_portrait_path_default_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = paths.character_portrait_path(_GAME_ID, "alyx")
    assert p == tmp_path / "storygen" / "games" / _GAME_ID / "images" / "characters" / "alyx-v1.png"


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
    p = paths.character_portrait_path(_GAME_ID, "alyx", version=3)
    assert p == (
        tmp_path / "storygen" / "games" / _GAME_ID / "images" / "characters" / "alyx-v3.png"
    )


def test_next_portrait_version_no_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.next_portrait_version(_GAME_ID, "alyx") == 1


def test_next_portrait_version_empty_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    paths.ensure_game_dirs(_GAME_ID)
    assert paths.next_portrait_version(_GAME_ID, "alyx") == 1


def test_next_portrait_version_increments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    paths.ensure_game_dirs(_GAME_ID)
    chars = tmp_path / "storygen" / "games" / _GAME_ID / "images" / "characters"
    (chars / "alyx-v1.png").write_bytes(b"a")
    (chars / "alyx-v2.png").write_bytes(b"b")
    (chars / "alyx-v5.png").write_bytes(b"e")
    # Other character files must be ignored.
    (chars / "bob-v9.png").write_bytes(b"x")
    assert paths.next_portrait_version(_GAME_ID, "alyx") == 6


def test_next_portrait_version_ignores_unrelated_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    paths.ensure_game_dirs(_GAME_ID)
    chars = tmp_path / "storygen" / "games" / _GAME_ID / "images" / "characters"
    (chars / "alyx.png").write_bytes(b"legacy")  # No -vN suffix
    (chars / "alyx-vbad.png").write_bytes(b"bad")  # Non-numeric version
    assert paths.next_portrait_version(_GAME_ID, "alyx") == 1


def test_character_outfit_path_format(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """character_outfit_path layed out as <save>/images/characters/<char>-outfit-<id>.png."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = paths.character_outfit_path(_GAME_ID, "alyx", "out123")
    assert p == (
        tmp_path
        / "storygen"
        / "games"
        / _GAME_ID
        / "images"
        / "characters"
        / "alyx-outfit-out123.png"
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
    p = paths.node_image_path(_GAME_ID, "node-1")
    assert p == tmp_path / "storygen" / "games" / _GAME_ID / "images" / "nodes" / "node-1.png"


def test_ensure_game_dirs_creates_subdirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    paths.ensure_game_dirs(_GAME_ID)
    assert (tmp_path / "storygen" / "games" / _GAME_ID).is_dir()
    assert (
        tmp_path / "storygen" / "games" / _GAME_ID / "images" / "characters"
    ).is_dir()
    assert (tmp_path / "storygen" / "games" / _GAME_ID / "images" / "nodes").is_dir()


def test_tts_audio_path_includes_provider_voice_and_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    p = paths.tts_audio_path(_GAME_ID, "node-1", provider="openai", voice="nova", ext="mp3")

    assert p.parent == tmp_path / "storygen" / "games" / _GAME_ID / "audio"
    assert p.name.startswith("node-1-openai-")
    assert p.suffix == ".mp3"


def test_tts_audio_path_changes_when_voice_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    first = paths.tts_audio_path(_GAME_ID, "node-1", provider="openai", voice="nova", ext="mp3")
    second = paths.tts_audio_path(_GAME_ID, "node-1", provider="openai", voice="alloy", ext="mp3")

    assert first != second


def test_tts_audio_path_changes_when_provider_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    first = paths.tts_audio_path(_GAME_ID, "node-1", provider="openai", voice="nova", ext="mp3")
    second = paths.tts_audio_path(_GAME_ID, "node-1", provider="gemini", voice="nova", ext="mp3")

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

    p = paths.tts_audio_path(_GAME_ID, "node-1", provider="custom/provider", voice="", ext=".wav")

    assert p.name.startswith("node-1-custom-provider-")
    assert p.suffix == ".wav"


# ---------------------------------------------------------------------------
# SEC-003: path-traversal validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "..",
        "../abc",
        "abc/..",
        "abc/../def",
        "a\\b",
        "abc.def",
        "",
        "abc!",
        "abc def",
        "-leading-dash",
        # not a UUID shape:
        "abc",
        "deadbeef",
        "g" * 32,
    ],
)
def test_game_id_rejects_non_uuid(bad_id: str) -> None:
    with pytest.raises(ValueError):
        paths.game_dir(bad_id)


def test_game_id_accepts_hyphenated_and_hex_forms() -> None:
    # Should not raise:
    assert paths.game_dir("12345678-1234-1234-1234-123456789012")
    assert paths.game_dir("deadbeef" * 4)


@pytest.mark.parametrize(
    "bad_id",
    ["", "..", ".", "../abc", "a/b", "a\\b", "-leading", "bad space", "glob*"],
)
def test_node_id_rejects_traversal(bad_id: str) -> None:
    with pytest.raises(ValueError):
        paths.node_image_path("12345678-1234-1234-1234-123456789012", bad_id)
    with pytest.raises(ValueError):
        paths.tts_audio_path("12345678-1234-1234-1234-123456789012", bad_id)
    with pytest.raises(ValueError):
        paths.node_audio_glob("12345678-1234-1234-1234-123456789012", bad_id)


@pytest.mark.parametrize(
    "bad_id",
    ["", "..", ".", "a/b", "a\\b", "-leading", "bad space", "glob*"],
)
def test_char_id_rejects_traversal(bad_id: str) -> None:
    gid = "12345678-1234-1234-1234-123456789012"
    with pytest.raises(ValueError):
        paths.character_portrait_path(gid, bad_id)
    with pytest.raises(ValueError):
        paths.character_reference_path(gid, bad_id)
    with pytest.raises(ValueError):
        paths.character_outfit_path(gid, bad_id, "out123")
    with pytest.raises(ValueError):
        paths.next_portrait_version(gid, bad_id)
    with pytest.raises(ValueError):
        paths.latest_portrait_version(gid, bad_id)


def test_node_id_accepts_short_ids() -> None:
    """Legacy short node/char IDs (e.g. 'root', 'a1', 'node-1') remain valid."""
    gid = "12345678-1234-1234-1234-123456789012"
    # No exception expected:
    paths.node_image_path(gid, "root")
    paths.node_image_path(gid, "a1")
    paths.character_portrait_path(gid, "alyx")
    paths.character_outfit_path(gid, "alyx", "out123")
