"""Unit tests for cross-game character library storage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from storygen.storage import paths
from storygen.storage.library import (
    LibraryCharacter,
    LibrarySource,
    delete_library_character,
    library_portrait_path,
    list_library_characters,
    load_library_character,
    save_library_character,
)


def _make_char(
    *,
    library_id: str | None = None,
    name: str = "Alyx",
    exported_at: datetime | None = None,
    exported_from: LibrarySource | None = None,
) -> LibraryCharacter:
    return LibraryCharacter(
        id=library_id or uuid4().hex,
        name=name,
        backstory="A wandering scholar.",
        personality="Curious and cautious.",
        physical_description="Tall, brown hair, green cloak.",
        portrait_prompt="A tall figure in a green cloak, neutral pose.",
        exported_at=exported_at or datetime.now(UTC),
        exported_from=exported_from,
    )


def test_save_and_load_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_char()
    portrait_bytes = b"\x89PNG\r\n\x1a\nfakeportraitdata"

    subdir = save_library_character(char, portrait_bytes)

    assert subdir.is_dir()
    assert (subdir / "character.json").exists()
    assert (subdir / "portrait.png").read_bytes() == portrait_bytes

    restored = load_library_character(char.id)
    assert restored == char


def test_save_pretty_prints_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_char()
    save_library_character(char, b"abc")
    raw = (paths.library_root() / char.id / "character.json").read_text(encoding="utf-8")
    # indent=2 emits newlines between fields.
    assert "\n  " in raw


def test_list_returns_empty_when_no_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert list_library_characters() == []


def test_list_sorted_by_exported_at_descending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    base = datetime.now(UTC)
    older = _make_char(name="Old", exported_at=base - timedelta(days=2))
    newer = _make_char(name="New", exported_at=base - timedelta(hours=1))
    middle = _make_char(name="Mid", exported_at=base - timedelta(days=1))

    for c in (older, newer, middle):
        save_library_character(c, b"x")

    listed = list_library_characters()
    assert [c.name for c in listed] == ["New", "Mid", "Old"]


def test_list_skips_corrupt_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    good = _make_char(name="Good")
    save_library_character(good, b"x")

    # Corrupt entry: valid subdir, invalid JSON.
    bad_dir = paths.library_root() / "corrupt-id"
    bad_dir.mkdir(parents=True)
    (bad_dir / "character.json").write_text("{not-json}", encoding="utf-8")

    listed = list_library_characters()
    assert [c.name for c in listed] == ["Good"]


def test_list_skips_missing_required_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    good = _make_char(name="Good")
    save_library_character(good, b"x")

    bad_dir = paths.library_root() / "missing-fields"
    bad_dir.mkdir(parents=True)
    (bad_dir / "character.json").write_text(
        json.dumps({"id": "missing-fields", "name": "Incomplete"}),
        encoding="utf-8",
    )

    listed = list_library_characters()
    assert [c.name for c in listed] == ["Good"]


def test_load_missing_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        load_library_character(uuid4().hex)


def test_delete_removes_subdir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_char()
    subdir = save_library_character(char, b"x")
    assert subdir.exists()

    delete_library_character(char.id)
    assert not subdir.exists()


def test_delete_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Never existed — must not raise.
    delete_library_character(uuid4().hex)

    # Second delete after a real delete also must not raise.
    char = _make_char()
    save_library_character(char, b"x")
    delete_library_character(char.id)
    delete_library_character(char.id)


def test_library_portrait_path_pure_math(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    lib_id = uuid4().hex
    path = library_portrait_path(lib_id)
    assert path == paths.library_root() / lib_id / "portrait.png"
    # Path returned even though file does not exist yet.
    assert not path.exists()


def test_save_is_atomic_survives_stale_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_char()
    subdir = paths.library_root() / char.id
    subdir.mkdir(parents=True)
    # Simulate a crash mid-write leaving a stale .tmp file behind.
    stale_tmp = subdir / "character.json.tmp"
    stale_tmp.write_text("garbage-from-prior-crash", encoding="utf-8")

    # Next save should succeed and produce a valid final file.
    save_library_character(char, b"portrait-bytes")
    restored = load_library_character(char.id)
    assert restored == char


def test_exported_from_none_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_char(exported_from=None)
    save_library_character(char, b"x")
    restored = load_library_character(char.id)
    assert restored.exported_from is None


def test_exported_from_source_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    src = LibrarySource(save_id="save-uuid-1234", save_title="The Hollow Kingdom")
    char = _make_char(exported_from=src)
    save_library_character(char, b"x")
    restored = load_library_character(char.id)
    assert restored.exported_from == src


def test_save_is_atomic_survives_stale_portrait_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale ``portrait.png.tmp`` from a prior crash must be overwritten cleanly."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_char()
    subdir = paths.library_root() / char.id
    subdir.mkdir(parents=True)
    stale_tmp = subdir / "portrait.png.tmp"
    stale_tmp.write_bytes(b"garbage-portrait-from-prior-crash")

    save_library_character(char, b"real-portrait-bytes")

    final = subdir / "portrait.png"
    assert final.read_bytes() == b"real-portrait-bytes"
    # os.replace atomically moved the new tmp over the final path; the old
    # stale tmp was overwritten by the new write. No stragglers.
    assert not stale_tmp.exists()


def test_library_portrait_path_rejects_traversal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="invalid library_id"):
        library_portrait_path("../../etc/passwd")


def test_delete_rejects_traversal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="invalid library_id"):
        delete_library_character("foo/bar")


def test_load_rejects_traversal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="invalid library_id"):
        load_library_character("../something")


def test_save_rejects_bad_id_without_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Bad ``char.id`` must raise ValueError BEFORE any filesystem mutation."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    bad = _make_char(library_id="not-a-uuid")
    with pytest.raises(ValueError, match="invalid library_id"):
        save_library_character(bad, b"PNG")

    # No subdirectory, no stray tmp files — filesystem untouched.
    root = paths.library_root()
    if root.exists():
        assert list(root.iterdir()) == []


def test_save_rejects_uppercase_hex_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Validator is strict lowercase hex (uuid4().hex contract)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    bad = _make_char(library_id=uuid4().hex.upper())
    with pytest.raises(ValueError, match="invalid library_id"):
        save_library_character(bad, b"PNG")


def test_unknown_extra_fields_tolerated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pydantic default: unknown fields in JSON are ignored on load."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_char()
    save_library_character(char, b"x")
    file = paths.library_root() / char.id / "character.json"
    data = json.loads(file.read_text(encoding="utf-8"))
    data["future_field_from_v1_3"] = "some-value"
    file.write_text(json.dumps(data), encoding="utf-8")

    restored = load_library_character(char.id)
    assert restored.name == char.name
