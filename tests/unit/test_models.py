"""Unit tests for Pydantic IO models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from storygen.llm.models import (
    Character,
    CharacterOutfit,
    Choice,
    IllustrationPlan,
    ImageProviderConfig,
    Relationship,
    RelationshipType,
    StoredChoice,
    StoryBeat,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.storage.library import LibraryCharacter, LibrarySource


def test_theme_requires_all_fields() -> None:
    theme = Theme(
        title="Neon Rain",
        setting="A cyberpunk Tokyo circa 2087.",
        premise="A courier discovers a shard that rewrites reality.",
        keywords=["cyberpunk", "noir", "heist"],
    )
    assert theme.title == "Neon Rain"
    assert len(theme.keywords) == 3


def test_tone_custom_requires_descriptor() -> None:
    Tone(preset="serious", custom_descriptor=None)
    Tone(preset="custom", custom_descriptor="darkly absurd")
    with pytest.raises(ValidationError):
        Tone(preset="custom", custom_descriptor=None)


def test_choice_has_no_child_node_id_field() -> None:
    """Choice (LLM-facing) is lean — no child_node_id."""
    choice = Choice(id="c1", text="Run")
    assert not hasattr(choice, "child_node_id")


def test_stored_choice_child_node_id_defaults_none() -> None:
    stored = StoredChoice(id="c1", text="Run")
    assert stored.child_node_id is None


def test_story_beat_ending_forbids_choices() -> None:
    StoryBeat(narration="The end.", choices=[], is_major=True, is_ending=True)
    with pytest.raises(ValidationError):
        StoryBeat(
            narration="Still going.",
            choices=[Choice(id="c1", text="Continue")],
            is_major=False,
            is_ending=True,
        )


def test_illustration_plan_defaults() -> None:
    plan = IllustrationPlan(
        should_illustrate=False,
        image_prompt="",
        featured_character_ids=[],
        reasoning="dialogue only",
    )
    assert plan.should_illustrate is False


def test_story_node_round_trip() -> None:
    node = StoryNode(
        id=uuid4().hex,
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You wake up in a data haze.",
        choices=[StoredChoice(id="c1", text="Stand up")],
        is_major=True,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    dumped = node.model_dump_json()
    restored = StoryNode.model_validate_json(dumped)
    assert restored == node


def test_text_provider_config_defaults() -> None:
    cfg = TextProviderConfig(provider="openai", model="gpt-4o-mini")
    assert cfg.base_url is None


def test_character_allows_optional_portrait() -> None:
    c = Character(
        id="alyx",
        name="Alyx",
        backstory="Ex-corporate fixer.",
        personality="Cynical but loyal.",
        physical_description="Tall, cropped silver hair, long black coat.",
        portrait_path=None,
        portrait_prompt=None,
        introduced_at_node_id="root",
    )
    assert c.portrait_path is None


def test_image_provider_config_literal() -> None:
    cfg = ImageProviderConfig(provider="openai", model="gpt-image-2")
    assert cfg.provider == "openai"


def test_character_outfit_round_trip() -> None:
    """A Character with two outfits + current_outfit_id round-trips losslessly."""
    now = datetime.now(UTC)
    outfit_a_id = uuid4().hex
    outfit_b_id = uuid4().hex
    outfits = [
        CharacterOutfit(
            id=outfit_a_id,
            name="casual",
            description="wearing a worn leather jacket and jeans",
            portrait_path=f"images/characters/alyx-outfit-{outfit_a_id}.png",
            portrait_prompt="Tall, cropped silver hair, worn leather jacket and jeans.",
            created_at=now,
        ),
        CharacterOutfit(
            id=outfit_b_id,
            name="ballroom gown",
            description="wearing a red gown with gold trim",
            portrait_path=f"images/characters/alyx-outfit-{outfit_b_id}.png",
            portrait_prompt="Tall, cropped silver hair, red gown with gold trim.",
            created_at=now,
        ),
    ]
    c = Character(
        id="alyx",
        name="Alyx",
        backstory="Ex-corporate fixer.",
        personality="Cynical but loyal.",
        physical_description="Tall, cropped silver hair, long black coat.",
        portrait_path="images/characters/alyx-v1.png",
        portrait_prompt="Tall, cropped silver hair, long black coat.",
        introduced_at_node_id="root",
        outfits=outfits,
        current_outfit_id=outfit_b_id,
    )
    restored = Character.model_validate_json(c.model_dump_json())
    assert restored == c
    assert len(restored.outfits) == 2
    assert restored.current_outfit_id == outfit_b_id
    assert restored.outfits[0].name == "casual"
    assert restored.outfits[1].description == "wearing a red gown with gold trim"


def test_character_legacy_save_loads_without_outfits_field() -> None:
    """A Character JSON missing ``outfits`` / ``current_outfit_id`` deserializes with defaults."""
    legacy_json = (
        '{"id": "alyx", "name": "Alyx", "backstory": "Ex-corporate fixer.",'
        ' "personality": "Cynical but loyal.",'
        ' "physical_description": "Tall, cropped silver hair, long black coat.",'
        ' "portrait_path": null, "portrait_prompt": null,'
        ' "introduced_at_node_id": "root"}'
    )
    c = Character.model_validate_json(legacy_json)
    assert c.outfits == []
    assert c.current_outfit_id is None


def test_character_outfit_required_fields() -> None:
    """Each required field on ``CharacterOutfit`` raises ValidationError when omitted."""
    base: dict[str, object] = {
        "id": uuid4().hex,
        "name": "casual",
        "description": "wearing a leather jacket",
        "portrait_path": "images/characters/alyx-outfit-x.png",
        "portrait_prompt": "Tall, cropped silver hair, leather jacket.",
        "created_at": datetime.now(UTC),
    }
    # Sanity: full payload is valid.
    CharacterOutfit.model_validate(base)
    for required in ("id", "name", "description", "portrait_path", "portrait_prompt", "created_at"):
        partial = {k: v for k, v in base.items() if k != required}
        with pytest.raises(ValidationError):
            CharacterOutfit.model_validate(partial)


# -- Library model tests ------------------------------------------------------


def test_library_source_has_optional_character_id() -> None:
    """LibrarySource.character_id defaults to None and accepts a string."""
    src = LibrarySource(save_id="abc123", save_title="My Save")
    assert src.character_id is None

    src_with = LibrarySource(save_id="abc123", save_title="My Save", character_id="char-42")
    assert src_with.character_id == "char-42"


def test_library_character_source_defaults_to_export() -> None:
    """LibraryCharacter.source defaults to 'export'."""
    now = datetime.now(UTC)
    char = LibraryCharacter(
        id=uuid4().hex,
        name="Alyx",
        backstory="Ex-corporate fixer.",
        personality="Cynical but loyal.",
        physical_description="Tall, cropped silver hair, long black coat.",
        portrait_prompt="Portrait of a tall woman with silver hair.",
        exported_at=now,
    )
    assert char.source == "export"


def test_library_character_source_roundtrip() -> None:
    """LibraryCharacter.source survives JSON roundtrip."""
    now = datetime.now(UTC)
    char = LibraryCharacter(
        id=uuid4().hex,
        name="Alyx",
        backstory="Ex-corporate fixer.",
        personality="Cynical but loyal.",
        physical_description="Tall, cropped silver hair, long black coat.",
        portrait_prompt="Portrait of a tall woman with silver hair.",
        exported_at=now,
        source="created",
    )
    dumped = char.model_dump_json()
    restored = LibraryCharacter.model_validate_json(dumped)
    assert restored.source == "created"
    assert restored == char


# -- Relationship model tests ---------------------------------------------------


def test_relationship_normalizes_char_order() -> None:
    """char_a_id is always lexicographically less than char_b_id."""
    r = Relationship(
        char_a_id="zzz",
        char_b_id="aaa",
        type=RelationshipType.ALLY,
        strength=3,
        context="test",
        updated_at_node_id="n1",
    )
    assert r.char_a_id == "aaa"
    assert r.char_b_id == "zzz"


def test_relationship_mentor_swaps_to_student_on_normalize() -> None:
    """When lex-swap reverses MENTOR, it becomes STUDENT."""
    r = Relationship(
        char_a_id="zzz",
        char_b_id="aaa",
        type=RelationshipType.MENTOR,
        strength=4,
        context="aaa mentors zzz",
        updated_at_node_id="n1",
    )
    assert r.char_a_id == "aaa"
    assert r.char_b_id == "zzz"
    assert r.type == RelationshipType.STUDENT


def test_relationship_student_swaps_to_mentor_on_normalize() -> None:
    r = Relationship(
        char_a_id="zzz",
        char_b_id="aaa",
        type=RelationshipType.STUDENT,
        strength=4,
        context="",
        updated_at_node_id="n1",
    )
    assert r.type == RelationshipType.MENTOR


def test_relationship_non_directional_type_unchanged_on_swap() -> None:
    """ALLY, RIVAL, NEUTRAL, ROMANTIC, FAMILY, STRANGER don't change on swap."""
    for rt in (
        RelationshipType.ALLY,
        RelationshipType.RIVAL,
        RelationshipType.NEUTRAL,
        RelationshipType.ROMANTIC,
        RelationshipType.FAMILY,
        RelationshipType.STRANGER,
    ):
        r = Relationship(
            char_a_id="zzz",
            char_b_id="aaa",
            type=rt,
            strength=2,
            context="",
            updated_at_node_id="n1",
        )
        assert r.type == rt


def test_relationship_strength_clamped_1_to_5() -> None:
    Relationship(
        char_a_id="a",
        char_b_id="b",
        type=RelationshipType.ALLY,
        strength=1,
        context="",
        updated_at_node_id="n1",
    )
    Relationship(
        char_a_id="a",
        char_b_id="b",
        type=RelationshipType.ALLY,
        strength=5,
        context="",
        updated_at_node_id="n1",
    )
    with pytest.raises(ValidationError):
        Relationship(
            char_a_id="a",
            char_b_id="b",
            type=RelationshipType.ALLY,
            strength=0,
            context="",
            updated_at_node_id="n1",
        )
    with pytest.raises(ValidationError):
        Relationship(
            char_a_id="a",
            char_b_id="b",
            type=RelationshipType.ALLY,
            strength=6,
            context="",
            updated_at_node_id="n1",
        )


def test_relationship_round_trip() -> None:
    r = Relationship(
        char_a_id="a",
        char_b_id="b",
        type=RelationshipType.RIVAL,
        strength=3,
        context="sworn enemies",
        updated_at_node_id="n1",
    )
    restored = Relationship.model_validate_json(r.model_dump_json())
    assert restored == r


def test_relationship_directional_types_unchanged_when_already_ordered() -> None:
    """MENTOR and STUDENT are preserved when char_a_id < char_b_id."""
    r_mentor = Relationship(
        char_a_id="a",
        char_b_id="b",
        type=RelationshipType.MENTOR,
        strength=3,
        context="",
        updated_at_node_id="n1",
    )
    assert r_mentor.type == RelationshipType.MENTOR
    r_student = Relationship(
        char_a_id="a",
        char_b_id="b",
        type=RelationshipType.STUDENT,
        strength=3,
        context="",
        updated_at_node_id="n1",
    )
    assert r_student.type == RelationshipType.STUDENT


def test_relationship_rejects_self_relationship() -> None:
    with pytest.raises(ValidationError):
        Relationship(
            char_a_id="a",
            char_b_id="a",
            type=RelationshipType.ALLY,
            strength=3,
            context="",
            updated_at_node_id="n1",
        )


def test_story_beat_has_relationship_updates_default_empty() -> None:
    beat = StoryBeat(narration="x", choices=[], is_major=True, is_ending=True)
    assert beat.relationship_updates == []
