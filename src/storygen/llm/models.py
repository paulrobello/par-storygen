"""Re-exports of shared domain types from ``storygen.core.models``.

All types previously defined here have moved to the neutral
``storygen.core.models`` package so that neither ``storage`` nor ``llm``
depends on the other.  This module is kept as a backward-compatible shim:
any code that still does ``from storygen.llm.models import Character``
continues to work without modification.
"""

from storygen.core.models import (
    AdaptedBackstory,
    Character,
    CharacterId,
    CharacterOutfit,
    Choice,
    IllustrationPlan,
    ImageProviderConfig,
    ImageStatus,
    NodeId,
    Relationship,
    RelationshipType,
    StoredChoice,
    StoryBeat,
    StoryNode,
    Summary,
    TextProviderConfig,
    Theme,
    Tone,
)

__all__ = [
    "AdaptedBackstory",
    "Character",
    "CharacterId",
    "CharacterOutfit",
    "Choice",
    "IllustrationPlan",
    "ImageProviderConfig",
    "ImageStatus",
    "NodeId",
    "Relationship",
    "RelationshipType",
    "StoredChoice",
    "StoryBeat",
    "StoryNode",
    "Summary",
    "TextProviderConfig",
    "Theme",
    "Tone",
]
