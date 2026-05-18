"""Unit tests for GameSave load/save."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from storygen.llm.models import (
    Character,
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.storage import paths
from storygen.storage.save import (
    GameSave,
    list_existing_story_titles,
    load_game,
    prune_subtree,
    save_game,
)


def _make_save() -> GameSave:
    node = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You open your eyes.",
        choices=[StoredChoice(id="c1", text="Sit up")],
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
    return GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title="T", setting="S", premise="P", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[
            Character(
                id="alyx",
                name="Alyx",
                backstory="b",
                personality="p",
                physical_description="d",
                portrait_path=None,
                portrait_prompt=None,
                introduced_at_node_id="root",
            )
        ],
        nodes={"root": node},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_list_existing_story_titles_reads_newest_valid_saves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    old_save = _make_save()
    old_save.theme.title = "Ancient Mall Quest"
    old_save.updated_at = datetime(2024, 1, 1, tzinfo=UTC)
    save_game(old_save)
    new_save = _make_save()
    new_save.theme.title = "Dragon Bakery"
    new_save.updated_at = datetime(2025, 1, 1, tzinfo=UTC)
    save_game(new_save)
    orphan = paths.games_root() / "orphan"
    orphan.mkdir(parents=True)
    (orphan / "game.json").write_text("not json", encoding="utf-8")

    assert list_existing_story_titles() == ["Dragon Bakery", "Ancient Mall Quest"]


def test_save_and_load_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    restored = load_game(str(save.id))
    assert restored == save


def test_load_backfills_creation_prompts_from_wizard_debug_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    llm_dir = paths.game_dir(str(save.id)) / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / "wizard-theme.json").write_text(
        '[{"kind":"request","parts":[{"part_kind":"system-prompt","content":"sys"},'
        '{"part_kind":"user-prompt","content":"Theme from debug"}]}]',
        encoding="utf-8",
    )
    (llm_dir / "wizard-characters.json").write_text(
        '[{"kind":"request","parts":[{"part_kind":"user-prompt","content":"Generate cast\\n\\n'
        "User-specified character requirements:\\nA fox and a moon baker\\n\\n"
        'The following characters are already part of the cast:"}]}]',
        encoding="utf-8",
    )

    restored = load_game(str(save.id))

    assert restored.creation_prompts.theme_prompt == "Theme from debug"
    assert restored.creation_prompts.character_prompt == "A fox and a moon baker"
    persisted = json.loads(paths.game_save_file(str(save.id)).read_text(encoding="utf-8"))
    assert persisted["creation_prompts"]["theme_prompt"] == "Theme from debug"


def test_load_backfills_full_character_debug_prompt_when_no_requirements_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    llm_dir = paths.game_dir(str(save.id)) / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / "wizard-characters.json").write_text(
        '[{"kind":"request","parts":[{"part_kind":"user-prompt",'
        '"content":"Generate cast for theme: T"}]}]',
        encoding="utf-8",
    )

    restored = load_game(str(save.id))

    assert restored.creation_prompts.character_prompt == "Generate cast for theme: T"


def test_save_writes_to_expected_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    assert paths.game_save_file(str(save.id)).exists()


def test_save_is_atomic_no_tmp_left_behind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    tmp_file = paths.game_save_file(str(save.id)).with_suffix(".json.tmp")
    assert not tmp_file.exists()


def test_load_missing_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    try:
        load_game("does-not-exist")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


def test_total_image_cost_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The total_image_cost_usd field round-trips through save+load."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save.total_image_cost_usd = 0.123
    save_game(save)
    restored = load_game(str(save.id))
    assert restored.total_image_cost_usd == 0.123


def test_total_image_cost_defaults_to_zero_on_old_saves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A save JSON without total_image_cost_usd loads with 0.0 default."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    # Strip the field to simulate a save written before the field existed.
    file = paths.game_save_file(str(save.id))
    raw = file.read_text(encoding="utf-8")
    import json

    data = json.loads(raw)
    data.pop("total_image_cost_usd", None)
    file.write_text(json.dumps(data), encoding="utf-8")

    restored = load_game(str(save.id))
    assert restored.total_image_cost_usd == 0.0


def test_token_usage_fields_default_to_zero_and_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Newly-built saves start with zeroed token counters and empty model dict."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    assert save.text_total_input_tokens == 0
    assert save.text_total_output_tokens == 0
    assert save.text_total_requests == 0
    assert save.text_calls_by_model == {}


def test_token_usage_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Token totals + per-model call counts survive a save+load cycle."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save.text_total_input_tokens = 1234
    save.text_total_output_tokens = 567
    save.text_total_requests = 8
    save.text_calls_by_model = {"gpt-4o-mini": 5, "claude-sonnet": 3}
    save_game(save)
    restored = load_game(str(save.id))
    assert restored.text_total_input_tokens == 1234
    assert restored.text_total_output_tokens == 567
    assert restored.text_total_requests == 8
    assert restored.text_calls_by_model == {"gpt-4o-mini": 5, "claude-sonnet": 3}


def test_art_style_defaults_to_childrens_story_book(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Newly built saves default art_style to "children's story book"."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    assert save.art_style == "children's story book"


def test_character_image_config_defaults_to_openai_v15_on_legacy_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A raw save JSON without character_image_config gets the portrait default."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    file = paths.game_save_file(str(save.id))
    import json

    data = json.loads(file.read_text(encoding="utf-8"))
    data.pop("character_image_config", None)
    file.write_text(json.dumps(data), encoding="utf-8")

    restored = load_game(str(save.id))

    assert restored.character_image_config.provider == "openai"
    assert restored.character_image_config.model == "gpt-image-2"


def test_art_style_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save.art_style = "watercolor"
    save_game(save)
    restored = load_game(str(save.id))
    assert restored.art_style == "watercolor"


def test_target_major_beats_defaults_to_five(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    assert save.target_major_beats == 5


def test_target_major_beats_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save.target_major_beats = 15
    save_game(save)
    restored = load_game(str(save.id))
    assert restored.target_major_beats == 15


def test_art_style_default_on_legacy_save(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A save JSON without art_style loads with the default value."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    file = paths.game_save_file(str(save.id))
    import json

    data = json.loads(file.read_text(encoding="utf-8"))
    data.pop("art_style", None)
    file.write_text(json.dumps(data), encoding="utf-8")
    restored = load_game(str(save.id))
    assert restored.art_style == "children's story book"


def test_token_usage_defaults_on_legacy_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A save JSON without the new token fields loads with zero/empty defaults."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    file = paths.game_save_file(str(save.id))
    import json

    data = json.loads(file.read_text(encoding="utf-8"))
    for field in (
        "text_total_input_tokens",
        "text_total_output_tokens",
        "text_total_requests",
        "text_calls_by_model",
    ):
        data.pop(field, None)
    file.write_text(json.dumps(data), encoding="utf-8")

    restored = load_game(str(save.id))
    assert restored.text_total_input_tokens == 0
    assert restored.text_total_output_tokens == 0
    assert restored.text_total_requests == 0
    assert restored.text_calls_by_model == {}


def test_pacing_defaults_to_moderate_on_old_saves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A save JSON without the pacing field loads with 'moderate' default."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    import json

    path = paths.game_save_file(str(save.id))
    data = json.loads(path.read_text())
    del data["pacing"]
    path.write_text(json.dumps(data))
    restored = load_game(str(save.id))
    assert restored.pacing == "moderate"


def _save_with_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GameSave:
    """Build a save with root -> a -> a1, root -> b, save it to disk."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    nodes = {
        "root": StoryNode(
            id="root",
            parent_id=None,
            chosen_choice_id=None,
            chosen_at=None,
            narration="root beat",
            choices=[
                StoredChoice(id="c1", text="go a", child_node_id="a"),
                StoredChoice(id="c2", text="go b", child_node_id="b"),
            ],
            is_major=True,
            is_ending=False,
            image_prompt=None,
            image_path=None,
            image_status="not_planned",
            illustration_reasoning=None,
            featured_character_ids=[],
            summary_to_here=None,
            created_at=datetime.now(UTC),
        ),
        "a": StoryNode(
            id="a",
            parent_id="root",
            chosen_choice_id="c1",
            chosen_at=datetime.now(UTC),
            narration="beat a",
            choices=[StoredChoice(id="c3", text="go a1", child_node_id="a1")],
            is_major=False,
            is_ending=False,
            image_prompt=None,
            image_path="images/nodes/a.png",
            image_status="done",
            illustration_reasoning=None,
            featured_character_ids=[],
            summary_to_here=None,
            created_at=datetime.now(UTC),
        ),
        "a1": StoryNode(
            id="a1",
            parent_id="a",
            chosen_choice_id="c3",
            chosen_at=datetime.now(UTC),
            narration="beat a1",
            choices=[],
            is_major=False,
            is_ending=True,
            image_prompt=None,
            image_path=None,
            image_status="not_planned",
            illustration_reasoning=None,
            featured_character_ids=[],
            summary_to_here=None,
            tts_audio_path="audio/a1-legacy-abcd1234.mp3",
            created_at=datetime.now(UTC),
        ),
        "b": StoryNode(
            id="b",
            parent_id="root",
            chosen_choice_id="c2",
            chosen_at=datetime.now(UTC),
            narration="beat b",
            choices=[],
            is_major=False,
            is_ending=False,
            image_prompt=None,
            image_path=None,
            image_status="not_planned",
            illustration_reasoning=None,
            featured_character_ids=[],
            summary_to_here=None,
            created_at=datetime.now(UTC),
        ),
    }
    save = GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title="T", setting="S", premise="P", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[],
        nodes=nodes,
        root_node_id="root",
        current_node_id="a1",
        endings_reached=["a1"],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    save_game(save)
    return save


def test_prune_subtree_removes_descendants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    count = prune_subtree(save, node_id="a")
    assert count == 2
    assert set(save.nodes.keys()) == {"root", "b"}
    assert save.nodes["root"].choices[0].child_node_id is None
    assert save.nodes["root"].choices[1].child_node_id == "b"


def test_prune_subtree_moves_current_to_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    assert save.current_node_id == "a1"
    prune_subtree(save, node_id="a")
    assert save.current_node_id == "root"


def test_prune_subtree_cleans_endings_reached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    assert "a1" in save.endings_reached
    prune_subtree(save, node_id="a")
    assert save.endings_reached == []


def test_prune_subtree_deletes_image_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    img = paths.node_image_path(str(save.id), "a")
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"fake-png")
    assert img.exists()
    prune_subtree(save, node_id="a")
    assert not img.exists()


def test_prune_subtree_deletes_audio_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    paths.ensure_game_dirs(str(save.id))
    audio = paths.game_dir(str(save.id)) / "audio" / "a1-legacy-abcd1234.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"fake-audio")
    assert audio.exists()
    prune_subtree(save, node_id="a")
    assert not audio.exists()


def test_prune_subtree_root_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        prune_subtree(save, node_id="root")


def test_migrate_v1_to_v2_adds_recap_text() -> None:
    from storygen.storage.save import _migrate  # pyright: ignore[reportPrivateUsage]

    data: dict[str, Any] = {
        "version": 1,
        "nodes": {
            "n1": {"id": "n1", "narration": "Hello"},
            "n2": {"id": "n2", "narration": "World"},
        },
    }
    result = _migrate(data, from_version=1)
    assert result["nodes"]["n1"]["recap_text"] is None
    assert result["nodes"]["n2"]["recap_text"] is None
    # v2 data passes through unchanged
    result2 = _migrate(
        {"version": 2, "nodes": {"n1": {"id": "n1", "recap_text": "Cached"}}},
        from_version=2,
    )
    assert result2["nodes"]["n1"]["recap_text"] == "Cached"


def test_migrate_v2_to_v3_adds_relationships() -> None:
    from storygen.storage.save import _migrate  # pyright: ignore[reportPrivateUsage]

    data: dict[str, Any] = {
        "version": 2,
        "characters": [{"id": "a"}, {"id": "b"}],
    }
    result = _migrate(data, from_version=2)
    assert result["relationships"] == []
    # v3 data passes through unchanged
    v3_data: dict[str, Any] = {
        "version": 3,
        "relationships": [
            {
                "char_a_id": "a",
                "char_b_id": "b",
                "type": "ally",
                "strength": 3,
                "context": "",
                "updated_at_node_id": "n1",
            }
        ],
    }
    result2 = _migrate(v3_data, from_version=3)
    assert len(result2["relationships"]) == 1


def test_relationships_default_empty_on_legacy_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A save JSON without relationships field loads with empty list."""
    import json

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    path = paths.game_save_file(str(save.id))
    data = json.loads(path.read_text())
    del data["relationships"]
    path.write_text(json.dumps(data))
    restored = load_game(str(save.id))
    assert restored.relationships == []
