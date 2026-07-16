"""Pure outfit bookkeeping for :class:`~storygen.screens.portraits.PortraitsScreen`.

The save-mutation logic behind the outfits section, extracted from the screen
so it is unit-testable without a Textual ``App``. Each function performs the
in-place update on ``save.characters`` and returns whether the named character
was found. The screen owns the persistence (``save_game``), UI refresh
(``_rebuild``), notification, and on-disk file side effects — these functions
are the pure transformation only.
"""

from __future__ import annotations

from storygen.core.models import Character, CharacterOutfit
from storygen.storage import paths
from storygen.storage.save import GameSave


def _base_portrait_relpath(save_id: str, char_id: str) -> str:
    """Best available relative path for a character's base portrait.

    Uses :func:`paths.latest_portrait_version` to pick the most recent base
    portrait (v2, v3, ...) so reverting from an outfit doesn't lose a
    manually-regenerated base. Falls back to ``-v1.png`` when no base portrait
    has ever been written (art was disabled at wizard time); the path may not
    exist on disk, but downstream renderers handle missing files gracefully.
    """
    version = paths.latest_portrait_version(save_id, char_id) or 1
    return paths.relative_character_portrait_path(char_id, version=version)


def _replace_char(save: GameSave, char_id: str, update: dict[str, object]) -> bool:
    """Replace the in-place character matching ``char_id`` via ``model_copy(update)``.

    Returns ``False`` (no-op) when no character with that id is in
    ``save.characters``, so callers can short-circuit without a noisy error.
    """
    for idx, c in enumerate(save.characters):
        if c.id == char_id:
            save.characters[idx] = c.model_copy(update=update)
            return True
    return False


def append_outfit(save: GameSave, char_id: str, outfit: CharacterOutfit) -> bool:
    """Append ``outfit`` to the named character (in-place on the save)."""
    for idx, c in enumerate(save.characters):
        if c.id == char_id:
            save.characters[idx] = c.model_copy(update={"outfits": [*c.outfits, outfit]})
            return True
    return False


def set_outfit_current(save: GameSave, char: Character, outfit: CharacterOutfit) -> bool:
    """Make ``outfit`` ``char``'s active outfit (copies its path/prompt fields)."""
    return _replace_char(
        save,
        char.id,
        {
            "current_outfit_id": outfit.id,
            "portrait_path": outfit.portrait_path,
            "portrait_prompt": outfit.portrait_prompt,
        },
    )


def delete_outfit(save: GameSave, char: Character, outfit: CharacterOutfit) -> bool:
    """Remove ``outfit`` from ``char``; revert to base portrait if it was active.

    Only the in-memory mutation lives here — the caller unlinks the outfit's
    PNG and persists the save.
    """
    update: dict[str, object] = {
        "outfits": [o for o in char.outfits if o.id != outfit.id],
    }
    if outfit.id == char.current_outfit_id:
        update["current_outfit_id"] = None
        update["portrait_path"] = _base_portrait_relpath(str(save.id), char.id)
        update["portrait_prompt"] = char.physical_description
    return _replace_char(save, char.id, update)


def revert_to_base(save: GameSave, char: Character) -> bool:
    """Clear ``char``'s active outfit and restore its base portrait path/prompt."""
    return _replace_char(
        save,
        char.id,
        {
            "current_outfit_id": None,
            "portrait_path": _base_portrait_relpath(str(save.id), char.id),
            "portrait_prompt": char.physical_description,
        },
    )
