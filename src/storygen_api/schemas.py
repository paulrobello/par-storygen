"""Pydantic request/response models for the ``storygen_api`` REST surface.

These DTOs decouple the wire schema from the richer domain models in
:mod:`storygen.core.models` and :mod:`storygen.storage.save` — routers
translate between the two at the boundary.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from storygen.core.models import Character, NodeId


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------


class GameSummary(BaseModel):
    id: str
    title: str
    updated_at: datetime
    node_count: int
    is_ending: bool
    has_cover: bool = False


class GameListResponse(BaseModel):
    games: list[GameSummary]


class NodeDetail(BaseModel):
    id: NodeId
    parent_id: NodeId | None = None
    chosen_choice_id: str | None = None
    narration: str
    is_major: bool
    is_ending: bool
    image_status: str | None = None
    image_path: str | None = None
    image_prompt: str | None = None
    summary_to_here: str | None = None
    choices: list[ChoiceOption] = []
    created_at: datetime


class ChoiceOption(BaseModel):
    id: str
    text: str
    child_node_id: NodeId | None = None


class GameDetail(BaseModel):
    id: str
    title: str
    theme: dict[str, object]
    tone: dict[str, object]
    characters: list[dict[str, object]]
    current_node_id: NodeId
    root_node_id: NodeId
    nodes: dict[NodeId, NodeDetail]
    endings_reached: list[NodeId]
    art_style: str
    total_image_cost_usd: float = 0.0
    text_total_input_tokens: int = 0
    text_total_output_tokens: int = 0
    text_total_requests: int = 0
    relationships: list[dict[str, object]] = []
    created_at: datetime
    updated_at: datetime


class AdvanceRequest(BaseModel):
    choice_id: str
    from_node_id: str


class AdvanceResponse(BaseModel):
    node: NodeDetail
    new_characters: list[Character]
    image_status: str | None = None


class GraphEdge(BaseModel):
    parent_id: NodeId
    choice_text: str
    child_id: NodeId | None = None


class GraphResponse(BaseModel):
    edges: list[GraphEdge]


class JumpRequest(BaseModel):
    target_node_id: NodeId


class PruneRequest(BaseModel):
    node_id: NodeId


class RegenerateNodeRequest(BaseModel):
    """Re-roll the current node by pruning it and re-advancing from the parent."""

    pass


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


class WizardThemeRequest(BaseModel):
    prompt: str


class WizardThemeResponse(BaseModel):
    theme: dict[str, object]


class WizardCharactersRequest(BaseModel):
    theme: dict[str, object]
    prompt: str = ""
    imported_characters: list[dict[str, object]] = []


class WizardCharactersResponse(BaseModel):
    characters: list[dict[str, object]]


class WizardConfirmRequest(BaseModel):
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
    game_id: str
    title: str


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class SettingsResponse(BaseModel):
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
    id: str
    name: str
    backstory: str
    personality: str
    physical_description: str
    portrait_prompt: str
    exported_at: datetime
    source: str = "export"
    has_portrait: bool = False
    has_reference_image: bool = False
    reference_image_path: str | None = None


class CharacterLibraryResponse(BaseModel):
    characters: list[CharacterLibraryEntry]


class CharacterExportRequest(BaseModel):
    name: str
    backstory: str
    personality: str
    physical_description: str
    portrait_prompt: str = ""
    save_id: str = ""
    save_title: str = ""
    character_id: str | None = None


class CharacterUpdateRequest(BaseModel):
    name: str | None = None
    backstory: str | None = None
    personality: str | None = None
    physical_description: str | None = None
    portrait_prompt: str | None = None


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


class PortraitRegenerateRequest(BaseModel):
    art_style: str = "children's story book"


class PortraitEditRequest(BaseModel):
    prompt: str
    mode: str = "edit"  # "edit" or "full"
    use_current_as_ref: bool = False
    art_style: str = "children's story book"


class CharacterCreateRequest(BaseModel):
    concept: str
    name: str = ""


class StoryImportRequest(BaseModel):
    save_id: str
    character_ids: list[str]


class OutfitRequest(BaseModel):
    name: str
    description: str


class OutfitActionRequest(BaseModel):
    action: str  # "set" or "delete"


class SceneEditRequest(BaseModel):
    prompt: str
