"""Unit tests for the extracted outfit-bookkeeping helpers (ARC-012/QA-006).

These exercise the pure save-mutation logic directly, without a Textual
Screen/App — the point of the extraction. The screen-side wrappers
(save_game / notify / _rebuild) are covered by ``test_portraits_screen.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from storygen.core.models import Character, CharacterOutfit
from storygen.llm.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.screens.controllers.portraits_outfits import (
    append_outfit,
    delete_outfit,
    revert_to_base,
    set_outfit_current,
)
from storygen.storage.save import GameSave


def _outfit(*, oid: str, name: str = "gown", description: str = "a red gown") -> CharacterOutfit:
    return CharacterOutfit(
        id=oid,
        name=name,
        description=description,
        portrait_path=f"characters/alyx/outfits/{oid}.png",
        portrait_prompt=f"base. Outfit: {description}.",
        created_at=datetime.now(UTC),
    )


def _char(*, outfits: list[CharacterOutfit] | None = None, current: str | None = None) -> Character:
    return Character(
        id="alyx",
        name="Alyx",
        backstory="A brave explorer.",
        personality="bold",
        physical_description="A tall figure with auburn hair.",
        portrait_path="characters/alyx-v1.png",
        portrait_prompt="A tall figure with auburn hair.",
        introduced_at_node_id="root",
        outfits=outfits or [],
        current_outfit_id=current,
    )


def _save(char: Character) -> GameSave:
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="Once upon a time.",
        choices=[StoredChoice(id="c1", text="Go")],
        is_major=False,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    return GameSave(
        version=4,
        id=uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[char],
        nodes={"root": root},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# --- append_outfit ---


def test_append_outfit_adds_to_matching_character(xdg_tmp: object) -> None:
    save = _save(_char())
    outfit = _outfit(oid="o1")
    assert append_outfit(save, "alyx", outfit) is True
    assert save.characters[0].outfits == [outfit]


def test_append_outfit_unknown_char_is_noop(xdg_tmp: object) -> None:
    save = _save(_char())
    assert append_outfit(save, "nobody", _outfit(oid="o1")) is False
    assert save.characters[0].outfits == []


def test_append_outfit_preserves_existing_outfits(xdg_tmp: object) -> None:
    first = _outfit(oid="o1")
    save = _save(_char(outfits=[first]))
    second = _outfit(oid="o2")
    assert append_outfit(save, "alyx", second) is True
    assert save.characters[0].outfits == [first, second]


# --- set_outfit_current ---


def test_set_outfit_current_copies_path_and_prompt(xdg_tmp: object) -> None:
    o1, o2 = _outfit(oid="o1"), _outfit(oid="o2", name="armor")
    save = _save(_char(outfits=[o1, o2], current="o1"))
    assert set_outfit_current(save, save.characters[0], o2) is True
    char = save.characters[0]
    assert char.current_outfit_id == "o2"
    assert char.portrait_path == o2.portrait_path
    assert char.portrait_prompt == o2.portrait_prompt


# --- delete_outfit ---


def test_delete_outfit_removes_outfit(xdg_tmp: object) -> None:
    o1, o2 = _outfit(oid="o1"), _outfit(oid="o2")
    save = _save(_char(outfits=[o1, o2], current="o1"))
    assert delete_outfit(save, save.characters[0], o2) is True
    char = save.characters[0]
    assert [o.id for o in char.outfits] == ["o1"]
    # Deleting a non-current outfit leaves the active one in place.
    assert char.current_outfit_id == "o1"
    assert char.portrait_path == "characters/alyx-v1.png"


def test_delete_outfit_reverts_to_base_when_current(xdg_tmp: object) -> None:
    o1 = _outfit(oid="o1")
    save = _save(_char(outfits=[o1], current="o1"))
    assert delete_outfit(save, save.characters[0], o1) is True
    char = save.characters[0]
    assert char.outfits == []
    assert char.current_outfit_id is None
    # Reverted to the base portrait path/prompt, not the outfit's.
    assert char.portrait_path != o1.portrait_path
    assert char.portrait_prompt == "A tall figure with auburn hair."


# --- revert_to_base ---


def test_revert_to_base_clears_active_outfit(xdg_tmp: object) -> None:
    o1 = _outfit(oid="o1")
    save = _save(_char(outfits=[o1], current="o1"))
    assert revert_to_base(save, save.characters[0]) is True
    char = save.characters[0]
    assert char.current_outfit_id is None
    assert char.portrait_prompt == "A tall figure with auburn hair."
    # The outfit itself is retained (revert only clears the *active* pointer).
    assert [o.id for o in char.outfits] == ["o1"]
