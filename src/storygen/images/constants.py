"""Provider-agnostic image generation constants.

Centralises the default sizes, qualities, and streaming parameters so
pipeline, screens, and wizard code does not need to import from a
specific provider module.  Provider implementations may override locally
(e.g. Gemini uses a different aspect-ratio convention) but they reference
these names so cost-estimation call sites stay consistent.
"""

from __future__ import annotations

from typing import Final, Literal

# Default portrait/scene dimensions used by the OpenAI provider (and echoed
# in the Gemini provider for cost-estimation parity).  These strings become
# ``size=`` kwargs in the OpenAI API; other providers treat them as human-
# readable labels for pricing lookups only.
PORTRAIT_SIZE: Final[Literal["1024x1536"]] = "1024x1536"
PORTRAIT_QUALITY: Final[Literal["low"]] = "low"
SCENE_SIZE: Final[Literal["1024x1024"]] = "1024x1024"
SCENE_QUALITY: Final[Literal["auto"]] = "auto"

# Number of partial images requested when streaming is active (OpenAI only).
# 2 is the sweet spot: a low-detail preview arrives at ~5-15 s and a
# higher-detail preview at ~10-30 s, adding ~+5% to OpenAI image cost.
OPENAI_PARTIAL_IMAGES: Final[int] = 2
