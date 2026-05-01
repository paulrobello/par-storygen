"""Unit tests for GameSave load/save."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
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
from storygen.storage.save import GameSave, load_game, save_game


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


def test_save_and_load_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save()
    save_game(save)
    restored = load_game(str(save.id))
    assert restored == save


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
    assert restored.character_image_config.model == "gpt-image-1.5"


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
