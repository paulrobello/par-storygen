"""Cross-game character library storage.

Persists characters exported from finished saves under
``$XDG_DATA_HOME/storygen/library/`` so they can be imported into new stories
in later sessions.

Layout::

    $XDG_DATA_HOME/storygen/library/<library-id>/
        |-- character.json   # LibraryCharacter model
        +-- portrait.png     # latest portrait snapshot

``library-id`` is a fresh ``uuid4().hex`` generated at export, independent from
the save-local ``Character.id``. Re-exporting the same save character creates a
new library entry (no dedup) -- the CharacterCatalogScreen is responsible for any
cleanup UX.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from storygen.storage import paths

_logger = logging.getLogger(__name__)

PLACEHOLDER_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x01\x01\x00\xf5\xfe\x7f\xc0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

_LIBRARY_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _validate_library_id(library_id: str) -> None:
    """Reject anything that isn't a uuid4 hex.

    Guards against path traversal via ``../`` and coerces callers to the
    documented format (``uuid4().hex``, 32 lowercase hex chars).

    Raises:
        ValueError: If ``library_id`` does not match the uuid4-hex shape.
    """
    if not _LIBRARY_ID_PATTERN.fullmatch(library_id):
        raise ValueError(
            f"invalid library_id: must be 32 hex chars (uuid4 hex), got {library_id!r}"
        )


class LibrarySource(BaseModel):
    """Provenance tag: which save a library character was exported from.

    Attributes:
        save_id: UUID of the originating GameSave.
        save_title: ``theme.title`` at export time, kept for humans browsing
            the library after the source save is gone.
        character_id: Optional ``Character.id`` from the originating save,
            linking the library entry back to its source character.
    """

    save_id: str
    save_title: str
    character_id: str | None = None


class LibraryCharacter(BaseModel):
    """A character persisted in the cross-game library.

    Attributes:
        id: Library-unique ``uuid4().hex`` generated at export. Independent
            from the save-local ``Character.id``.
        name: Display name.
        backstory: Free-form backstory text.
        personality: One-line personality description.
        physical_description: Prompt-ready physical description used for
            portrait generation.
        portrait_prompt: The exact prompt used to generate the portrait PNG
            (resolved via :func:`library_portrait_path`). Kept so later imports
            can regenerate the portrait with consistent visual intent.
        exported_at: UTC timestamp of when the character entered the library.
            Intentionally required: callers must pass an explicit
            ``datetime.now(UTC)`` so provenance is never implicit.
        exported_from: Optional source save provenance.
        source: How the character entered the library -- ``"export"`` (from a
            finished save), ``"created"`` (manually created), or
            ``"story_import"`` (imported from another story).
        reference_image_path: Optional reference image filename.
    """

    id: str
    name: str
    backstory: str
    personality: str
    physical_description: str
    portrait_prompt: str
    exported_at: datetime
    exported_from: LibrarySource | None = None
    source: Literal["export", "created", "story_import"] = "export"
    reference_image_path: str | None = None


def _character_dir(library_id: str) -> Path:
    """Return the subdirectory that holds one library character's files."""
    return paths.library_root() / library_id


def _character_json_path(library_id: str) -> Path:
    """Return the absolute path to a library character's ``character.json``."""
    return _character_dir(library_id) / "character.json"


def library_portrait_path(library_id: str) -> Path:
    """Return the absolute path to the portrait PNG for ``library_id``.

    Pure path math -- does not touch the filesystem and does not require the
    file to exist. ``library_id`` must be a uuid4 hex; other values raise
    :class:`ValueError` to prevent path traversal.
    """
    _validate_library_id(library_id)
    return _character_dir(library_id) / "portrait.png"


def library_reference_path(library_id: str) -> Path:
    """Return the absolute path to the reference image PNG for ``library_id``."""
    _validate_library_id(library_id)
    return _character_dir(library_id) / "reference.png"


def save_library_character(
    char: LibraryCharacter,
    portrait_bytes: bytes,
    reference_bytes: bytes | None = None,
) -> Path:
    """Atomically persist a library character, its portrait, and optional reference image.

    Order: portrait → reference → JSON. A valid ``character.json`` always implies
    both ``portrait.png`` exists and, if ``reference_image_path`` is set,
    ``reference.png`` also exists.

    Args:
        char: The character to persist.
        portrait_bytes: Raw PNG bytes for ``portrait.png``.
        reference_bytes: Optional raw PNG bytes for ``reference.png``.
            When provided, sets ``char.reference_image_path = "reference.png"``.

    Returns:
        The absolute path to the character's subdirectory.
    """
    _validate_library_id(char.id)

    if reference_bytes is not None:
        # Use model_copy rather than mutating the caller's instance.
        char = char.model_copy(update={"reference_image_path": "reference.png"})

    subdir = _character_dir(char.id)
    subdir.mkdir(parents=True, exist_ok=True)
    # Restrict directory to owner-only: library portraits and JSON may contain
    # sensitive prompt text and provider details.
    os.chmod(subdir, 0o700)

    # Write portrait atomically FIRST.
    portrait_final = subdir / "portrait.png"
    portrait_tmp = portrait_final.with_suffix(".png.tmp")
    portrait_tmp.write_bytes(portrait_bytes)
    os.chmod(portrait_tmp, 0o600)
    os.replace(portrait_tmp, portrait_final)

    # Write reference image atomically SECOND (if provided).
    if reference_bytes is not None:
        ref_final = subdir / "reference.png"
        ref_tmp = ref_final.with_suffix(".png.tmp")
        ref_tmp.write_bytes(reference_bytes)
        os.chmod(ref_tmp, 0o600)
        os.replace(ref_tmp, ref_final)

    # THEN write character.json atomically (committed marker).
    json_final = _character_json_path(char.id)
    json_tmp = json_final.with_suffix(".json.tmp")
    json_tmp.write_text(char.model_dump_json(indent=2), encoding="utf-8")
    os.chmod(json_tmp, 0o600)
    os.replace(json_tmp, json_final)

    return subdir


def load_library_character(library_id: str) -> LibraryCharacter:
    """Load a single library character by id.

    Args:
        library_id: The library-unique id assigned at export. Must be a
            uuid4 hex; other values raise :class:`ValueError`.

    Returns:
        The deserialized ``LibraryCharacter``.

    Raises:
        FileNotFoundError: If no subdirectory exists for ``library_id``.
        ValueError: If ``library_id`` is not a uuid4 hex.
    """
    _validate_library_id(library_id)
    subdir = _character_dir(library_id)
    if not subdir.is_dir():
        raise FileNotFoundError(f"No library character at {subdir}")
    json_path = _character_json_path(library_id)
    if not json_path.exists():
        raise FileNotFoundError(f"No character.json at {json_path}")
    return LibraryCharacter.model_validate_json(json_path.read_text(encoding="utf-8"))


def list_library_characters() -> list[LibraryCharacter]:
    """Return every library character, sorted by ``exported_at`` descending.

    Corrupt or partially-written entries (invalid JSON, missing required
    fields, unreadable files) are logged at WARNING and skipped so one bad
    entry never takes down the whole list.
    """
    root = paths.library_root()
    if not root.is_dir():
        return []

    results: list[LibraryCharacter] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        json_path = entry / "character.json"
        if not json_path.exists():
            _logger.warning("Library entry missing character.json: %s", entry)
            continue
        try:
            raw = json_path.read_text(encoding="utf-8")
            char = LibraryCharacter.model_validate_json(raw)
        except (ValidationError, ValueError, OSError) as exc:
            _logger.warning("Skipping corrupt library entry %s: %s", entry.name, exc)
            continue
        results.append(char)

    results.sort(key=lambda c: c.exported_at, reverse=True)
    return results


def delete_library_character(library_id: str) -> None:
    """Remove a library character's subdirectory.

    Idempotent: if the subdirectory does not exist, the call is a no-op.
    ``library_id`` must be a uuid4 hex; other values raise :class:`ValueError`.
    """
    _validate_library_id(library_id)
    subdir = _character_dir(library_id)
    if subdir.exists():
        shutil.rmtree(subdir)
