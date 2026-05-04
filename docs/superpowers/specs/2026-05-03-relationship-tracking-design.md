# Character Relationship Tracking

**Date:** 2026-05-03
**Status:** Approved

## Problem

Characters in par-storygen exist as a flat list with no inter-character structure. The LLM implicitly infures character dynamics from narration but has no structured, persistent relationship data. This means:

- Relationships mentioned in early beats can be forgotten or contradicted later
- The player has no visibility into how characters relate to each other
- Beat prompts lack explicit relationship context, reducing narrative consistency

## Solution

Add a pairwise relationship matrix to `GameSave`. The beat agent extracts relationship changes inline during beat generation. Current relationships are fed back into beat prompts for narrative consistency. A new modal screen displays the full relationship view.

## Data Model

New types in `core/models.py`:

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
    char_a_id: CharacterId
    char_b_id: CharacterId
    type: RelationshipType
    strength: int = Field(ge=1, le=5)   # 1=acquaintance, 5=deep bond
    context: str = ""                    # e.g. "became allies after the siege"
    updated_at_node_id: NodeId           # which node last changed this

    @model_validator(mode="after")
    def _normalize_order(self) -> "Relationship":
        """Enforce char_a_id < char_b_id lexicographically to prevent duplicates."""
        if self.char_a_id > self.char_b_id:
            self.char_a_id, self.char_b_id = self.char_b_id, self.char_a_id
            if self.type == RelationshipType.MENTOR:
                self.type = RelationshipType.STUDENT
            elif self.type == RelationshipType.STUDENT:
                self.type = RelationshipType.MENTOR
        return self
```

**`GameSave`** gets a new field: `relationships: list[Relationship] = Field(default_factory=list[Relationship])`

**`StoryBeat`** (beat agent output) gets: `relationship_updates: list[Relationship] = Field(default_factory=list[Relationship])`

**Save migration** v2→v3 adds `relationships: []` to existing saves.

## Beat Pipeline Integration

### System Prompt Enhancement

The beat agent's system prompt (`beat_system_prompt()` in `prompts.py`) adds:

> "Track character dynamics. In `relationship_updates`, report any new or changed relationships between characters that are clearly expressed or implied by the narration. Only include relationships that meaningfully changed in this beat. If nothing changed, return an empty list."

### Beat Prompt Enhancement

`_build_beat_prompt()` in `pipeline.py` adds a RELATIONSHIPS section below the existing CAST section:

```
RELATIONSHIPS:
- Aria ↔ Kael: ally (strength 4) — bonded during the forest ambush
- Aria ↔ The Witch: rival (strength 3) — sworn enemies after the curse
```

Only characters present in the current CAST are included. New characters with no relationships are omitted.

### Merge Logic

After the beat returns, `BeatPipeline.advance()` merges `relationship_updates` into `save.relationships`:

1. For each update, find existing relationship by `(char_a_id, char_b_id)`
2. If found: update `type`, `strength`, `context`, `updated_at_node_id`
3. If not found: append new relationship
4. Existing relationships not in the update list are left unchanged

The LLM emits only *changes* (deltas), not the full state every beat.

## Relationship Modal Screen

New file: `screens/relationships.py` — `RelationshipsScreen(ModalScreen[None])`.

**Keybinding:** `r` from PlayScreen.

**Layout:**

```
┌─ Character Relationships ─────────────────────────┐
│                                                    │
│  Aria the Bold                                     │
│    ↔ Kael     ally    ████░  (4/5)  bonded during  │
│                        the forest ambush           │
│    ↔ The Witch rival   ███░░  (3/5)  sworn enemies │
│                        after the curse             │
│                                                    │
│  Kael the Swift                                    │
│    ↔ Aria     ally    ████░  (4/5)  bonded during  │
│                        the forest ambush           │
│                                                    │
│  The Witch                                         │
│    ↔ Aria     rival   ███░░  (3/5)  sworn enemies  │
│                        after the curse             │
│                                                    │
│              [Press Escape to close]               │
└────────────────────────────────────────────────────┘
```

- Each character gets a section showing all their pairwise relationships
- Strength shown as a text bar (5 chars: filled/empty blocks)
- Context shown as a dimmed caption below each relationship line
- Characters with no relationships shown with "No known relationships."
- Read-only view. Escape or `q` to close.

## Files Changed

### Modified
- `src/storygen/core/models.py` — `RelationshipType`, `Relationship`, `StoryBeat.relationship_updates`, `GameSave.relationships`
- `src/storygen/llm/prompts.py` — Beat system prompt with relationship tracking instruction
- `src/storygen/pipeline.py` — RELATIONSHIPS section in `_build_beat_prompt()`, merge logic in `advance()`
- `src/storygen/storage/save.py` — Migration v2→v3, `SAVE_VERSION` bump to 3
- `src/storygen/screens/play.py` — Add `r` keybinding for relationship modal

### Created
- `src/storygen/screens/relationships.py` — `RelationshipsScreen` modal

### Tests
- `tests/unit/test_models.py` — Relationship validation, lex-sort validator, MENTOR/STUDENT swap
- `tests/unit/test_pipeline.py` — RELATIONSHIPS in beat prompt, merge create/update/no-op
- `tests/unit/test_save.py` — Migration v2→v3
- `tests/unit/test_relationships_screen.py` — Screen renders with mock data

## Out of Scope

- No player editing of relationships
- No group/faction tracking
- No relationship history or per-node snapshots
- No changes to CharacterSheet widget (it remains unwired)
- No library character relationship export
