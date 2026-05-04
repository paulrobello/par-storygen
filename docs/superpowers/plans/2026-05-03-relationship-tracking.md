# Character Relationship Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pairwise character relationship tracking that the beat agent extracts inline, feeds back into prompts for narrative consistency, and displays in a new modal screen.

**Architecture:** A `Relationship` edge model stored as a flat list on `GameSave`. The beat agent returns `relationship_updates` (deltas) in each `StoryBeat`. The pipeline merges these into the save. Current relationships are injected into beat prompts. A new `RelationshipsScreen` modal renders the full relationship view, accessible via `f` keybinding from PlayScreen.

**Tech Stack:** Python 3.13, Pydantic v2, Textual TUI, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/storygen/core/models.py` | `RelationshipType`, `Relationship`, updated `StoryBeat` with `relationship_updates` |
| `src/storygen/storage/save.py` | Migration v2→v3, `SAVE_VERSION` bump, `relationships` field on `GameSave` |
| `src/storygen/pipeline.py` | RELATIONSHIPS section in `_build_beat_prompt`, `_merge_relationships` helper, merge call in `advance()` |
| `src/storygen/llm/prompts.py` | Relationship tracking instruction added to `beat_system_prompt` |
| `src/storygen/screens/relationships.py` | `RelationshipsScreen` modal (new file) |
| `src/storygen/screens/play.py` | `f` keybinding to open relationship modal |
| `tests/unit/test_models.py` | Relationship model validation tests |
| `tests/unit/test_save.py` | Migration v2→v3 test |
| `tests/unit/test_pipeline.py` | Relationship prompt + merge tests |
| `tests/unit/test_relationships_screen.py` | Screen render test (new file) |

---

### Task 1: Data Model — RelationshipType, Relationship, StoryBeat update

**Files:**
- Modify: `src/storygen/core/models.py:151-165` (StoryBeat)
- Modify: `src/storygen/core/models.py:226-248` (__all__)
- Test: `tests/unit/test_models.py`

- [ ] **Step 1: Write failing tests for Relationship model**

Append to `tests/unit/test_models.py`:

```python
from storygen.core.models import Relationship, RelationshipType


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
    for rt in (RelationshipType.ALLY, RelationshipType.RIVAL, RelationshipType.NEUTRAL,
               RelationshipType.ROMANTIC, RelationshipType.FAMILY, RelationshipType.STRANGER):
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
    from pydantic import ValidationError
    Relationship(char_a_id="a", char_b_id="b", type=RelationshipType.ALLY, strength=1, context="", updated_at_node_id="n1")
    Relationship(char_a_id="a", char_b_id="b", type=RelationshipType.ALLY, strength=5, context="", updated_at_node_id="n1")
    with pytest.raises(ValidationError):
        Relationship(char_a_id="a", char_b_id="b", type=RelationshipType.ALLY, strength=0, context="", updated_at_node_id="n1")
    with pytest.raises(ValidationError):
        Relationship(char_a_id="a", char_b_id="b", type=RelationshipType.ALLY, strength=6, context="", updated_at_node_id="n1")


def test_relationship_round_trip() -> None:
    r = Relationship(
        char_a_id="a", char_b_id="b", type=RelationshipType.RIVAL,
        strength=3, context="sworn enemies", updated_at_node_id="n1",
    )
    restored = Relationship.model_validate_json(r.model_dump_json())
    assert restored == r


def test_story_beat_has_relationship_updates_default_empty() -> None:
    beat = StoryBeat(narration="x", choices=[], is_major=True, is_ending=True)
    assert beat.relationship_updates == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_models.py::test_relationship_normalizes_char_order tests/unit/test_models.py::test_story_beat_has_relationship_updates_default_empty -v`
Expected: FAIL — `ImportError` for `Relationship`, `RelationshipType`

- [ ] **Step 3: Implement RelationshipType, Relationship, update StoryBeat**

In `src/storygen/core/models.py`, add after the `CharacterOutfit` class (after line 115) and before the `Character` class:

```python
class RelationshipType(str, Enum):
    ALLY = "ally"
    RIVAL = "rival"
    NEUTRAL = "neutral"
    ROMANTIC = "romantic"
    MENTOR = "mentor"
    STUDENT = "student"
    FAMILY = "family"
    STRANGER = "stranger"


class Relationship(BaseModel):
    """A pairwise relationship between two characters."""

    char_a_id: CharacterId
    char_b_id: CharacterId
    type: RelationshipType
    strength: int = Field(ge=1, le=5)
    context: str = ""
    updated_at_node_id: NodeId

    @model_validator(mode="after")
    def _normalize_order(self) -> "Relationship":
        if self.char_a_id > self.char_b_id:
            self.char_a_id, self.char_b_id = self.char_b_id, self.char_a_id
            if self.type == RelationshipType.MENTOR:
                self.type = RelationshipType.STUDENT
            elif self.type == RelationshipType.STUDENT:
                self.type = RelationshipType.MENTOR
        return self
```

Add `from enum import Enum` to the imports at the top (after `from typing import Literal`).

Update `StoryBeat` to add `relationship_updates`:

```python
class StoryBeat(BaseModel):
    """Output of `beat_agent` — the narrative content of one beat."""

    narration: str
    choices: list[Choice]
    is_major: bool
    is_ending: bool
    new_characters: list[Character] = Field(default_factory=list[Character])
    relationship_updates: list[Relationship] = Field(default_factory=list[Relationship])
```

Add to `__all__`:

```python
    "Relationship",
    "RelationshipType",
```

Add `Enum` to the import block at top of file (after `from typing import Literal`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/core/models.py tests/unit/test_models.py
git commit -m "feat: add Relationship model and RelationshipType enum"
```

---

### Task 2: Save Migration v2→v3 + GameSave.relationships field

**Files:**
- Modify: `src/storygen/storage/save.py:29` (SAVE_VERSION), `:42-71` (GameSave), `:87-102` (_migrate)
- Test: `tests/unit/test_save.py`

- [ ] **Step 1: Write failing test for migration v2→v3**

Append to `tests/unit/test_save.py`:

```python
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
        "relationships": [{"char_a_id": "a", "char_b_id": "b", "type": "ally", "strength": 3, "context": "", "updated_at_node_id": "n1"}],
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_save.py::test_migrate_v2_to_v3_adds_relationships tests/unit/test_save.py::test_relationships_default_empty_on_legacy_save -v`
Expected: FAIL — migration doesn't add relationships yet

- [ ] **Step 3: Implement migration and GameSave field**

In `src/storygen/storage/save.py`:

Bump version:
```python
SAVE_VERSION: int = 3
```

Add `relationships` field to `GameSave` (after `characters: list[Character]`):
```python
    relationships: list[Relationship] = Field(default_factory=list[Relationship])
```

Add import at top:
```python
from storygen.core.models import (
    Character,
    ImageProviderConfig,
    NarrationStyle,
    NodeId,
    Pacing,
    ReaderLevel,
    Relationship,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
```

Update `_migrate` to handle v2→v3:
```python
def _migrate(data: dict[str, Any], *, from_version: int) -> dict[str, Any]:
    if from_version < 2:
        for node in data.get("nodes", {}).values():
            node.setdefault("recap_text", None)
    if from_version < 3:
        data.setdefault("relationships", [])
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_save.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/storage/save.py tests/unit/test_save.py
git commit -m "feat: add relationships field to GameSave with v2→v3 migration"
```

---

### Task 3: Beat Prompt Enhancement — RELATIONSHIPS section

**Files:**
- Modify: `src/storygen/pipeline.py:898-941` (`_build_beat_prompt`)
- Test: `tests/unit/test_pipeline_helpers.py`

- [ ] **Step 1: Write failing test for RELATIONSHIPS section in beat prompt**

Append to `tests/unit/test_pipeline_helpers.py`:

```python
def test_build_beat_prompt_includes_relationships_section() -> None:
    """When save has relationships, _build_beat_prompt includes a RELATIONSHIPS section."""
    from storygen.core.models import Character, Relationship, RelationshipType

    root = StoryNode(
        id="root", parent_id=None, chosen_choice_id=None, chosen_at=None,
        narration="Start.", choices=[StoredChoice(id="c1", text="go")],
        is_major=True, is_ending=False, image_prompt=None, image_path=None,
        image_status="not_planned", illustration_reasoning=None,
        featured_character_ids=[], summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save = GameSave(
        version=3, id=uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[
            Character(id="alyx", name="Alyx", backstory="b", personality="p",
                      physical_description="d", introduced_at_node_id="root"),
            Character(id="kael", name="Kael", backstory="b", personality="p",
                      physical_description="d", introduced_at_node_id="root"),
        ],
        relationships=[
            Relationship(char_a_id="alyx", char_b_id="kael", type=RelationshipType.ALLY,
                         strength=4, context="bonded during ambush", updated_at_node_id="root"),
        ],
        nodes={"root": root}, root_node_id="root", current_node_id="root",
        endings_reached=[], created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    prompt = _build_beat_prompt(save, "root", "go left")
    assert "RELATIONSHIPS:" in prompt
    assert "Alyx ↔ Kael" in prompt
    assert "ally" in prompt
    assert "bonded during ambush" in prompt


def test_build_beat_prompt_omits_relationships_when_empty() -> None:
    """When save has no relationships, no RELATIONSHIPS section appears."""
    root = StoryNode(
        id="root", parent_id=None, chosen_choice_id=None, chosen_at=None,
        narration="Start.", choices=[StoredChoice(id="c1", text="go")],
        is_major=True, is_ending=False, image_prompt=None, image_path=None,
        image_status="not_planned", illustration_reasoning=None,
        featured_character_ids=[], summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save = GameSave(
        version=3, id=uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[], relationships=[],
        nodes={"root": root}, root_node_id="root", current_node_id="root",
        endings_reached=[], created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    prompt = _build_beat_prompt(save, "root", "go left")
    assert "RELATIONSHIPS:" not in prompt
```

Add required imports at top of `test_pipeline_helpers.py`:

```python
from datetime import UTC, datetime
from uuid import uuid4
from storygen.llm.models import (
    StoredChoice, StoryNode, TextProviderConfig, ImageProviderConfig,
    Theme, Tone,
)
from storygen.storage.save import GameSave
from storygen.pipeline import _build_beat_prompt  # pyright: ignore[reportPrivateUsage]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_pipeline_helpers.py::test_build_beat_prompt_includes_relationships_section tests/unit/test_pipeline_helpers.py::test_build_beat_prompt_omits_relationships_when_empty -v`
Expected: FAIL — no RELATIONSHIPS section generated yet

- [ ] **Step 3: Implement RELATIONSHIPS section in _build_beat_prompt**

In `src/storygen/pipeline.py`, update `_build_beat_prompt` to add a RELATIONSHIPS section after the CAST section. Insert after the CAST block (after line 916, before `prev_summary, segment = ...`):

```python
    if save.relationships:
        char_names = {c.id: c.name for c in save.characters}
        rel_lines = [
            f"- {char_names.get(r.char_a_id, r.char_a_id)} ↔ {char_names.get(r.char_b_id, r.char_b_id)}: {r.type.value} (strength {r.strength}) — {r.context}"
            for r in save.relationships
            if r.char_a_id in char_names and r.char_b_id in char_names
        ]
        if rel_lines:
            sections.append("RELATIONSHIPS:\n" + "\n".join(rel_lines))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_pipeline_helpers.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/pipeline.py tests/unit/test_pipeline_helpers.py
git commit -m "feat: add RELATIONSHIPS section to beat prompt"
```

---

### Task 4: Relationship Merge Logic in Pipeline

**Files:**
- Modify: `src/storygen/pipeline.py:196-387` (`advance` method)
- Test: `tests/unit/test_pipeline.py`

- [ ] **Step 1: Write failing tests for relationship merge**

Append to `tests/unit/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_merges_relationship_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """advance() merges relationship_updates from beat into save.relationships."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from storygen.core.models import Relationship, RelationshipType

    beat = StoryBeat(
        narration="They fought side by side.",
        choices=[Choice(id="c1", text="onward")],
        is_major=False,
        is_ending=False,
        relationship_updates=[
            Relationship(
                char_a_id="a", char_b_id="b", type=RelationshipType.ALLY,
                strength=3, context="fought together", updated_at_node_id="pending",
            ),
        ],
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning="",
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )
    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert len(save.relationships) == 1
    assert save.relationships[0].type == RelationshipType.ALLY
    assert save.relationships[0].context == "fought together"


@pytest.mark.asyncio
async def test_pipeline_merges_relationship_update_existing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Updating an existing relationship replaces type/strength/context."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from storygen.core.models import Relationship, RelationshipType

    # Pre-existing relationship
    save.relationships.append(
        Relationship(
            char_a_id="a", char_b_id="b", type=RelationshipType.NEUTRAL,
            strength=1, context="strangers", updated_at_node_id="root",
        )
    )
    beat = StoryBeat(
        narration="They became friends.",
        choices=[Choice(id="c1", text="onward")],
        is_major=False,
        is_ending=False,
        relationship_updates=[
            Relationship(
                char_a_id="a", char_b_id="b", type=RelationshipType.ALLY,
                strength=3, context="became friends", updated_at_node_id="pending",
            ),
        ],
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning="",
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )
    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert len(save.relationships) == 1  # updated, not duplicated
    assert save.relationships[0].type == RelationshipType.ALLY
    assert save.relationships[0].strength == 3
    assert save.relationships[0].context == "became friends"


@pytest.mark.asyncio
async def test_pipeline_merges_relationship_no_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A beat with empty relationship_updates leaves existing relationships unchanged."""
    save = _bootstrap_save(tmp_path, monkeypatch)
    from storygen.core.models import Relationship, RelationshipType

    save.relationships.append(
        Relationship(
            char_a_id="a", char_b_id="b", type=RelationshipType.RIVAL,
            strength=2, context="tension", updated_at_node_id="root",
        )
    )
    beat = StoryBeat(
        narration="A quiet moment.",
        choices=[Choice(id="c1", text="onward")],
        is_major=False,
        is_ending=False,
        relationship_updates=[],
    )
    plan = IllustrationPlan(
        should_illustrate=False, image_prompt="", featured_character_ids=[], reasoning="",
    )
    pipeline = BeatPipeline(
        beat_agent=FakeBeatAgent(beat),
        illustration_agent=FakeIllustrationAgent(plan),
        summary_agent=None,
        image_provider=FakeImageProvider(),
        callbacks=PipelineCallbacks(),
    )
    await pipeline.advance(save, from_node_id="root", choice_id="c1")
    assert len(save.relationships) == 1
    assert save.relationships[0].type == RelationshipType.RIVAL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_pipeline.py::test_pipeline_merges_relationship_updates tests/unit/test_pipeline.py::test_pipeline_merges_relationship_update_existing tests/unit/test_pipeline.py::test_pipeline_merges_relationship_no_updates -v`
Expected: FAIL — relationships not being merged yet

- [ ] **Step 3: Implement merge logic in advance()**

In `src/storygen/pipeline.py`, add a module-level helper function before `_build_beat_prompt`:

```python
def _merge_relationships(
    save: GameSave, updates: list[Relationship], node_id: str
) -> None:
    """Merge relationship deltas from a beat into the save's relationship list."""
    for update in updates:
        key = (update.char_a_id, update.char_b_id)
        existing = next(
            (r for r in save.relationships if (r.char_a_id, r.char_b_id) == key),
            None,
        )
        if existing is not None:
            save.relationships.remove(existing)
        save.relationships.append(
            update.model_copy(update={"updated_at_node_id": node_id})
        )
```

Add import at top of `pipeline.py`:
```python
from storygen.core.models import Relationship
```
(Already imports from `storygen.llm.models` which re-exports, but for clarity we can use the re-export. Check if `Relationship` is re-exported from `storygen.llm.models` — it will be since `storygen/llm/models.py` re-exports from `storygen.core.models`. Use `from storygen.llm.models import ... Relationship` if available, otherwise add the import.)

In the `advance()` method, after the new_characters processing block (after the line that sets `introduced_at_node_id`, around line 313), add the merge call:

```python
        # Merge relationship updates from the beat.
        if beat.relationship_updates:
            _merge_relationships(save, beat.relationship_updates, new_node_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_pipeline.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/pipeline.py tests/unit/test_pipeline.py
git commit -m "feat: merge relationship deltas from beat into save"
```

---

### Task 5: Beat System Prompt — Relationship Tracking Instruction

**Files:**
- Modify: `src/storygen/llm/prompts.py:122-182` (`beat_system_prompt`)
- Test: `tests/unit/test_prompts.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_prompts.py`:

```python
def test_beat_system_prompt_includes_relationship_tracking() -> None:
    prompt = beat_system_prompt(
        theme=Theme(title="T", setting="S", premise="P", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
    )
    assert "relationship_updates" in prompt
    assert "relationship" in prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_prompts.py::test_beat_system_prompt_includes_relationship_tracking -v`
Expected: FAIL — "relationship_updates" not in prompt

- [ ] **Step 3: Add relationship tracking instruction to beat_system_prompt**

In `src/storygen/llm/prompts.py`, in `beat_system_prompt()`, add after the `new_characters` field description (after the line about "so the description IS the visual contract") and before "CONTINUATION RULES":

```python
        " - relationship_updates: optional list of new or changed pairwise"
        " relationships between characters. Only include relationships that"
        " clearly changed in this beat. Each has char_a_id, char_b_id,"
        " type (ally, rival, neutral, romantic, mentor, student, family,"
        " stranger), strength (1-5), and a brief context string. If no"
        " relationships changed, return an empty list.\n\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_prompts.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/llm/prompts.py tests/unit/test_prompts.py
git commit -m "feat: add relationship tracking instruction to beat system prompt"
```

---

### Task 6: RelationshipsScreen Modal

**Files:**
- Create: `src/storygen/screens/relationships.py`
- Test: `tests/unit/test_relationships_screen.py`

- [ ] **Step 1: Write failing test for RelationshipsScreen**

Create `tests/unit/test_relationships_screen.py`:

```python
"""Unit tests for RelationshipsScreen."""

from __future__ import annotations

from textual.app import App, ComposeResult

from storygen.core.models import Character, Relationship, RelationshipType
from storygen.screens.relationships import RelationshipsScreen


class _Harness(App[None]):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield RelationshipsScreen()

    def on_mount(self) -> None:
        screen = self.query_one(RelationshipsScreen)
        screen.set_data(
            characters=[
                Character(id="a", name="Aria", backstory="", personality="Bold.",
                          physical_description="Tall.", introduced_at_node_id="root"),
                Character(id="b", name="Kael", backstory="", personality="Swift.",
                          physical_description="Short.", introduced_at_node_id="root"),
                Character(id="c", name="Witch", backstory="", personality="Dark.",
                          physical_description="Green skin.", introduced_at_node_id="root"),
            ],
            relationships=[
                Relationship(char_a_id="a", char_b_id="b", type=RelationshipType.ALLY,
                             strength=4, context="bonded in ambush", updated_at_node_id="n1"),
                Relationship(char_a_id="a", char_b_id="c", type=RelationshipType.RIVAL,
                             strength=3, context="sworn enemies", updated_at_node_id="n2"),
            ],
        )


async def test_relationships_screen_renders() -> None:
    async with _Harness().run_test() as pilot:
        screen = pilot.app.query_one(RelationshipsScreen)
        content = screen.query_one("#rel-content")
        # Should contain character names and relationship info
        text = content.renderable.plain if hasattr(content.renderable, "plain") else str(content.renderable)
        assert "Aria" in text
        assert "Kael" in text
        assert "Witch" in text
        assert "ally" in text.lower()
        assert "rival" in text.lower()


async def test_relationships_screen_displays_no_relationships_message() -> None:
    """When no relationships exist, shows a message."""

    class _EmptyHarness(App[None]):
        CSS = "Screen { align: center middle; }"

        def compose(self) -> ComposeResult:
            yield RelationshipsScreen()

        def on_mount(self) -> None:
            screen = self.query_one(RelationshipsScreen)
            screen.set_data(
                characters=[
                    Character(id="a", name="Lone Wolf", backstory="", personality="Aloof.",
                              physical_description="Grey.", introduced_at_node_id="root"),
                ],
                relationships=[],
            )

    async with _EmptyHarness().run_test() as pilot:
        screen = pilot.app.query_one(RelationshipsScreen)
        content = screen.query_one("#rel-content")
        text = content.renderable.plain if hasattr(content.renderable, "plain") else str(content.renderable)
        assert "No known relationships" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_relationships_screen.py -v`
Expected: FAIL — `storygen.screens.relationships` module not found

- [ ] **Step 3: Implement RelationshipsScreen**

Create `src/storygen/screens/relationships.py`:

```python
"""RelationshipsScreen: modal showing pairwise character relationships."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from storygen.core.models import Character, Relationship, RelationshipType

_REL_TYPE_ICONS: dict[RelationshipType, str] = {
    RelationshipType.ALLY: "↔",
    RelationshipType.RIVAL: "⚔",
    RelationshipType.NEUTRAL: "○",
    RelationshipType.ROMANTIC: "♥",
    RelationshipType.MENTOR: "↑",
    RelationshipType.STUDENT: "↓",
    RelationshipType.FAMILY: "⌂",
    RelationshipType.STRANGER: "✗",
}


def _strength_bar(strength: int) -> str:
    filled = "█" * strength
    empty = "░" * (5 - strength)
    return f"{filled}{empty}"


class RelationshipsScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    RelationshipsScreen {
        align: center middle;
    }
    RelationshipsScreen #rel-container {
        width: 72;
        max-height: 80vh;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    RelationshipsScreen #rel-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    RelationshipsScreen #rel-content {
        height: auto;
        max-height: 70vh;
    }
    RelationshipsScreen .rel-char-header {
        text-style: bold;
        margin-top: 1;
    }
    RelationshipsScreen .rel-line {
        margin-left: 2;
    }
    RelationshipsScreen .rel-context {
        color: $text-muted;
        margin-left: 4;
    }
    RelationshipsScreen #rel-footer {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
        ("q", "app.pop_screen", "Close"),
    ]

    def __init__(
        self,
        characters: list[Character] | None = None,
        relationships: list[Relationship] | None = None,
    ) -> None:
        super().__init__()
        self._characters = characters or []
        self._relationships = relationships or []

    def set_data(
        self,
        characters: list[Character],
        relationships: list[Relationship],
    ) -> None:
        self._characters = characters
        self._relationships = relationships
        self._render_content()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="rel-container"):
            yield Static("Character Relationships", id="rel-title")
            yield Static(self._build_renderable(), id="rel-content")
            yield Static("Press Escape or q to close", id="rel-footer")

    def on_mount(self) -> None:
        self._render_content()

    def _render_content(self) -> None:
        try:
            content = self.query_one("#rel-content")
            content.update(self._build_renderable())
        except Exception:
            pass

    def _build_renderable(self) -> str:
        if not self._relationships:
            return "No known relationships."

        char_names = {c.id: c.name for c in self._characters}
        lines: list[str] = []

        # Group by character
        seen_chars: set[str] = set()
        for char in self._characters:
            char_rels = [
                r for r in self._relationships
                if r.char_a_id == char.id or r.char_b_id == char.id
            ]
            if not char_rels:
                continue
            if char.id in seen_chars:
                continue
            seen_chars.add(char.id)

            lines.append(f"[bold]{char.name}[/bold]")
            for rel in char_rels:
                other_id = rel.char_b_id if rel.char_a_id == char.id else rel.char_a_id
                other_name = char_names.get(other_id, other_id)
                icon = _REL_TYPE_ICONS.get(rel.type, "↔")
                bar = _strength_bar(rel.strength)
                lines.append(f"  {icon} {other_name}  {rel.type.value}  {bar} ({rel.strength}/5)")
                if rel.context:
                    lines.append(f"    [dim]{rel.context}[/dim]")
            lines.append("")

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_relationships_screen.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/screens/relationships.py tests/unit/test_relationships_screen.py
git commit -m "feat: add RelationshipsScreen modal"
```

---

### Task 7: PlayScreen Keybinding — Wire RelationshipsScreen

**Files:**
- Modify: `src/storygen/screens/play.py:106-136` (BINDINGS)
- Test: `tests/unit/test_play_screen.py`

- [ ] **Step 1: Write failing test for keybinding**

Append to `tests/unit/test_play_screen.py`:

```python
async def test_play_screen_relationships_keybinding_opens_modal(
    xdg_tmp: Path, reset_dotenv_cache: None
) -> None:
    """Pressing 'f' opens the RelationshipsScreen modal."""
    app = _make_app()
    async with app.run_test() as pilot:
        # Navigate to play screen
        await _goto_play(pilot)
        play = pilot.app.query_one(PlayScreen)
        play._loading = False  # pyright: ignore[reportPrivateUsage]
        await pilot.press("f")
        await pilot.pause()
        from storygen.screens.relationships import RelationshipsScreen
        assert pilot.app.screen is not None
        assert isinstance(pilot.app.screen, RelationshipsScreen)
        await pilot.press("escape")
```

Note: This test may need adjustment depending on the existing `_goto_play` helper. If the helper doesn't exist or the test structure differs significantly, check the existing test patterns in `test_play_screen.py` and adapt accordingly.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_play_screen.py::test_play_screen_relationships_keybinding_opens_modal -v`
Expected: FAIL — no `f` binding exists

- [ ] **Step 3: Add `f` keybinding and action to PlayScreen**

In `src/storygen/screens/play.py`:

Add import at top:
```python
from storygen.screens.relationships import RelationshipsScreen
```

Add binding to `BINDINGS` list (after the `"x", "export_book"` entry):
```python
        ("f", "relationships", "Relationships"),
```

Add action method (near the other action methods, e.g. after `action_endings`):

```python
    def action_relationships(self) -> None:
        if self._loading:
            return
        save = self._save
        if save is None:
            return
        self.app.push_screen(
            RelationshipsScreen(
                characters=save.characters,
                relationships=save.relationships,
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_play_screen.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/screens/play.py tests/unit/test_play_screen.py
git commit -m "feat: add 'f' keybinding to open RelationshipsScreen from PlayScreen"
```

---

### Task 8: Full Checkall + Fix Any Issues

**Files:** All modified files

- [ ] **Step 1: Run full checkall**

Run: `make checkall`
Expected: All formatting, linting, type checking, and tests pass.

- [ ] **Step 2: Fix any issues found**

Common fixes:
- Missing imports in re-export shim (`src/storygen/llm/models.py`) — add `Relationship`, `RelationshipType` to re-exports
- `test_play_screen.py` test may need adaptation to match existing helper patterns
- pyright strict mode issues with new code

- [ ] **Step 3: Run checkall again to confirm clean**

Run: `make checkall`
Expected: All green

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: address checkall issues for relationship tracking"
```

---

### Task 9: Update Ideas and Changelog

**Files:**
- Modify: `ideas.md` — Move "Character Relationship Tracking" to Completed section
- Modify: `CHANGELOG.md` — Add entry

- [ ] **Step 1: Update ideas.md**

Move the "Character Relationship Tracking" entry from the Gameplay & Narrative section to the Completed section with today's date.

- [ ] **Step 2: Update CHANGELOG.md**

Add entry under the current version header.

- [ ] **Step 3: Commit**

```bash
git add ideas.md CHANGELOG.md
git commit -m "docs: update ideas and changelog for relationship tracking"
```
