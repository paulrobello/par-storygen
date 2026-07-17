"""Pydantic request/response models for the ``storygen_api`` REST surface.

These DTOs decouple the wire schema from the richer domain models in
:mod:`storygen.core.models` and :mod:`storygen.storage.save` — routers
translate between the two at the boundary.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from storygen.core.models import Character, NodeId

# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------


class GameSummary(BaseModel):
    """One row in the game list (lightweight, no node tree)."""

    id: str = Field(description="Save UUID (hex).")
    title: str = Field(description="Human-readable story title.")
    updated_at: datetime = Field(description="Last write time of the save.")
    node_count: int = Field(description="Number of nodes currently in the tree.")
    is_ending: bool = Field(
        description="True when the current cursor sits on a terminal (ending) node."
    )
    has_cover: bool = False


class GameListResponse(BaseModel):
    """Response envelope for `GET /api/games`."""

    games: list[GameSummary]


class ChoiceOption(BaseModel):
    """A single choice offered at a node, with its resolved child if explored."""

    id: str = Field(description="Stable choice id (unique within the parent node).")
    text: str = Field(description="Player-facing choice label.")
    child_node_id: NodeId | None = Field(
        default=None,
        description="Id of the node this choice leads to, or null while unexplored.",
    )


class NodeDetail(BaseModel):
    """Full projection of a single story node for the client."""

    id: NodeId = Field(description="Node id (content-addressed).")
    parent_id: NodeId | None = Field(
        default=None, description="Parent node id; null for the root."
    )
    chosen_choice_id: str | None = Field(
        default=None,
        description="Id of the choice taken from the parent to reach this node.",
    )
    narration: str = Field(description="Narration text shown to the player.")
    is_major: bool = Field(description="True for major (summary-triggering) beats.")
    is_ending: bool = Field(description="True when this node ends the story.")
    image_status: str | None = Field(
        default=None,
        description="Scene-image lifecycle state: "
        "not_planned | generating | done | failed.",
    )
    image_path: str | None = Field(
        default=None, description="Relative path to the scene image, when present."
    )
    image_prompt: str | None = Field(
        default=None, description="Prompt used (or to be used) for the scene image."
    )
    summary_to_here: str | None = Field(
        default=None,
        description="Cumulative story-so-far summary anchored at this node, "
        "present only on major beats.",
    )
    choices: list[ChoiceOption] = []
    created_at: datetime = Field(description="When the node was first committed.")


class GameDetail(BaseModel):
    """Full game state: the node tree plus aggregated metadata."""

    id: str = Field(description="Save UUID (hex).")
    title: str = Field(description="Human-readable story title.")
    theme: dict[str, object] = Field(description="Theme blob (premise, tone, etc.).")
    tone: dict[str, object] = Field(description="Tone blob (preset + descriptor).")
    characters: list[dict[str, object]] = Field(
        description="Current cast roster (may grow mid-story)."
    )
    current_node_id: NodeId = Field(description="Cursor position in the tree.")
    root_node_id: NodeId = Field(description="Root node id.")
    nodes: dict[NodeId, NodeDetail] = Field(description="Full node map keyed by id.")
    endings_reached: list[NodeId] = Field(
        description="Node ids of every ending the player has reached."
    )
    art_style: str = Field(description="Art-style string threaded into image prompts.")
    total_image_cost_usd: float = Field(
        default=0.0, description="Cumulative image spend in USD."
    )
    text_total_input_tokens: int = Field(default=0, description="Cumulative input tokens.")
    text_total_output_tokens: int = Field(
        default=0, description="Cumulative output tokens."
    )
    text_total_requests: int = Field(default=0, description="Cumulative LLM call count.")
    relationships: list[dict[str, object]] = []
    created_at: datetime = Field(description="Save creation time.")
    updated_at: datetime = Field(description="Last write time.")


class AdvanceRequest(BaseModel):
    """Body for `POST /api/games/{id}/advance` — pick a choice."""

    choice_id: str = Field(description="Id of the choice being taken.")
    from_node_id: str = Field(description="Node the choice is being taken from.")


class AdvanceResponse(BaseModel):
    """Result of an advance: the landed node plus any side effects."""

    node: NodeDetail
    new_characters: list[Character] = Field(
        description="Characters introduced by this beat (may be empty)."
    )
    image_status: str | None = Field(
        default=None,
        description="Scene-image state at response time "
        "(the image may still be rendering asynchronously).",
    )


class GraphEdge(BaseModel):
    """One parent→child edge in the story tree."""

    parent_id: NodeId = Field(description="Parent node id.")
    choice_text: str = Field(description="Label of the choice leading to the child.")
    child_id: NodeId | None = Field(
        default=None, description="Child node id, or null while unexplored."
    )


class GraphResponse(BaseModel):
    """Edge list for `GET /api/games/{id}/graph`."""

    edges: list[GraphEdge]


class JumpRequest(BaseModel):
    """Body for the jump-to-node endpoint."""

    target_node_id: NodeId = Field(description="Node to move the cursor to.")


class PruneRequest(BaseModel):
    """Body for the prune-subtree endpoint."""

    node_id: NodeId = Field(description="Root of the subtree to delete.")


class RegenerateNodeRequest(BaseModel):
    """Re-roll the current node by pruning it and re-advancing from the parent."""

    pass


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


class WizardThemeRequest(BaseModel):
    """Body for the theme-generation wizard step."""

    prompt: str = Field(description="Free-text premise the theme is derived from.")


class WizardThemeResponse(BaseModel):
    """Generated theme blob."""

    theme: dict[str, object]


class WizardCharactersRequest(BaseModel):
    """Body for the character-generation wizard step."""

    theme: dict[str, object] = Field(description="Theme blob from the theme step.")
    prompt: str = ""
    imported_characters: list[dict[str, object]] = []


class WizardCharactersResponse(BaseModel):
    """Generated cast roster."""

    characters: list[dict[str, object]]


class WizardConfirmRequest(BaseModel):
    """Body for the confirm-and-create-game wizard step."""

    theme: dict[str, object]
    tone: dict[str, object]
    narration_style: str = "third_person"
    characters: list[dict[str, object]]
    art_style: str = "children's story book"
    target_major_beats: int = 5
    reader_level: str = "ages_11_15"
    pacing: str = "moderate"
    theme_prompt: str = ""
    character_prompt: str = ""


class WizardConfirmResponse(BaseModel):
    """Ids of the newly created game."""

    game_id: str = Field(description="UUID of the new save.")
    title: str = Field(description="Generated story title.")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class SettingsResponse(BaseModel):
    """Snapshot of every persisted preference + provider default."""

    art_enabled: bool = True
    prefetch_enabled: bool = False
    prefetch_images_enabled: bool = False
    image_streaming_enabled: bool = False
    llm_cache_enabled: bool = False
    auto_select_enabled: bool = False
    auto_open_art_enabled: bool = False
    auto_recap_enabled: bool = False
    resume_recap_enabled: bool = True
    recap_interval: int = 3
    graphics_mode: str = "halfblock"
    text_provider: dict[str, object] = {}
    image_provider: dict[str, object] = {}
    character_image_provider: dict[str, object] = {}
    wizard_defaults: dict[str, object] = {}
    tts_prefs: dict[str, object] = {}


class SettingsUpdateRequest(BaseModel):
    """Partial update for `PUT /api/settings` — only set fields are applied."""

    art_enabled: bool | None = None
    prefetch_enabled: bool | None = None
    prefetch_images_enabled: bool | None = None
    image_streaming_enabled: bool | None = None
    llm_cache_enabled: bool | None = None
    auto_select_enabled: bool | None = None
    auto_open_art_enabled: bool | None = None
    auto_recap_enabled: bool | None = None
    resume_recap_enabled: bool | None = None
    recap_interval: int | None = None
    graphics_mode: str | None = None
    text_provider: dict[str, object] | None = None
    image_provider: dict[str, object] | None = None
    character_image_provider: dict[str, object] | None = None
    wizard_defaults: dict[str, object] | None = None
    tts_prefs: dict[str, object] | None = None


# ---------------------------------------------------------------------------
# Characters library
# ---------------------------------------------------------------------------


class CharacterLibraryEntry(BaseModel):
    """One exported character in the cross-game library."""

    id: str = Field(description="Library id (uuid4 hex, independent of save char id).")
    name: str
    backstory: str
    personality: str
    physical_description: str
    portrait_prompt: str = Field(description="Prompt the portrait was generated from.")
    exported_at: datetime = Field(description="When the character was exported.")
    source: str = "export"
    has_portrait: bool = False
    has_reference_image: bool = False
    reference_image_path: str | None = None


class CharacterLibraryResponse(BaseModel):
    """Response envelope for `GET /api/library`."""

    characters: list[CharacterLibraryEntry]


class CharacterExportRequest(BaseModel):
    """Body for exporting a character into the library."""

    name: str
    backstory: str
    personality: str
    physical_description: str
    portrait_prompt: str = ""
    save_id: str = ""
    save_title: str = ""
    character_id: str | None = None


class CharacterUpdateRequest(BaseModel):
    """Partial update for an in-place library character edit."""

    name: str | None = None
    backstory: str | None = None
    personality: str | None = None
    physical_description: str | None = None
    portrait_prompt: str | None = None


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


class PortraitRegenerateRequest(BaseModel):
    """Body for the portrait-regenerate endpoint."""

    art_style: str = "children's story book"


class PortraitEditRequest(BaseModel):
    """Body for the portrait edit/regenerate endpoint."""

    prompt: str
    mode: str = "edit"  # "edit" or "full"
    use_current_as_ref: bool = False
    art_style: str = "children's story book"


class CharacterCreateRequest(BaseModel):
    """Body for creating a new library character from a concept."""

    concept: str
    name: str = ""


class StoryImportRequest(BaseModel):
    """Body for importing characters from another save into the library."""

    save_id: str = Field(description="Source save to pull characters from.")
    character_ids: list[str] = Field(description="Character ids to import.")


class OutfitRequest(BaseModel):
    """Body for creating a character outfit."""

    name: str
    description: str


class OutfitActionRequest(BaseModel):
    """Body for the set/delete outfit action."""

    action: str  # "set" or "delete"


class SceneEditRequest(BaseModel):
    """Body for the scene-prompt-edit endpoint."""

    prompt: str
