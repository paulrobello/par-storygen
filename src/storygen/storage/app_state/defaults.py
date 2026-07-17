"""Default values, choice tuples, and allow-lists for app state.

Consumed by :mod:`.models` (dataclass field defaults), :mod:`.io`
(reader/writer fallbacks), and directly by the Settings screen, the
provider factories, and the wizard.

Provider constants (``PROVIDER_CHOICES``, ``IMAGE_PROVIDER_CHOICES``,
``SUGGESTED_MODELS``, ``SUGGESTED_IMAGE_MODELS``, ``IMAGE_API_KEY_ENV``,
``PROVIDER_SUPPORTS_REFS``, ``ALLOWED_PROVIDERS``, ``ALLOWED_IMAGE_PROVIDERS``)
are derived from the declarative registry in :mod:`storygen.core.providers`
(ENH-005). TTS constants remain here pending ENH-006.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import get_args

from storygen.core.models import ReaderLevel
from storygen.core.providers import IMAGE_PROVIDERS, TEXT_PROVIDERS

ALLOWED_PACINGS: frozenset[str] = frozenset({"slow", "moderate", "fast"})
ALLOWED_READER_LEVELS: frozenset[str] = frozenset(get_args(ReaderLevel))

DEFAULT_ART_STYLE: str = "children's story book"
DEFAULT_TONE_PRESET: str = "serious"
DEFAULT_NARRATION_STYLE: str = "third_person"

DEFAULT_TARGET_MAJOR_BEATS: int = 5
MIN_TARGET_MAJOR_BEATS: int = 2
MAX_TARGET_MAJOR_BEATS: int = 30

DEFAULT_PACING: str = "moderate"
DEFAULT_READER_LEVEL: ReaderLevel = "ages_11_15"

DEFAULT_TEXT_PROVIDER: str = "openai"
DEFAULT_TEXT_MODEL: str = "gpt-4o-mini"

# UI-facing (label, provider-id) pairs — consumed by the Settings screen Select widget.
# Immutable tuple-of-tuples so callers can't mutate the module's source of truth.
# Order follows TEXT_PROVIDERS insertion order (openai, openrouter, ollama).
PROVIDER_CHOICES: tuple[tuple[str, str], ...] = tuple(
    (p.label, p.id) for p in TEXT_PROVIDERS.values()
)

# Per-provider curated model suggestions for the Settings screen.
# Wrapped in MappingProxyType so the top-level dict is read-only; list values
# are still mutable but callers shouldn't need to touch them.
SUGGESTED_MODELS: MappingProxyType[str, list[str]] = MappingProxyType(
    {pid: list(info.suggested_models) for pid, info in TEXT_PROVIDERS.items()}
)

ALLOWED_PROVIDERS: frozenset[str] = frozenset(TEXT_PROVIDERS.keys())

DEFAULT_IMAGE_PROVIDER: str = "openai"
DEFAULT_IMAGE_MODEL: str = "gpt-image-2"
DEFAULT_CHARACTER_IMAGE_PROVIDER: str = "openai"
DEFAULT_CHARACTER_IMAGE_MODEL: str = "gpt-image-2"

# UI-facing (label, provider-id) pairs — consumed by the Settings screen Select widget.
# Order follows IMAGE_PROVIDERS insertion order (openai, gemini, zai, ollama).
IMAGE_PROVIDER_CHOICES: tuple[tuple[str, str], ...] = tuple(
    (p.label, p.id) for p in IMAGE_PROVIDERS.values()
)

# Per-provider curated image-model suggestions for the Settings screen.
SUGGESTED_IMAGE_MODELS: MappingProxyType[str, tuple[str, ...]] = MappingProxyType(
    {pid: info.suggested_models for pid, info in IMAGE_PROVIDERS.items()}
)

# Which providers support reference-image inputs (portrait-anchored scene gen).
# Mirrors the registry's supports_reference_images field; ARC-115 requires this
# to agree with each provider class's attribute — asserted by
# tests/unit/test_provider_registry.py.
PROVIDER_SUPPORTS_REFS: frozenset[str] = frozenset(
    pid for pid, info in IMAGE_PROVIDERS.items() if info.supports_reference_images
)

# Per-provider environment variable name that supplies the provider's API key.
# None means the provider needs no auth (Ollama local). STORYGEN_IMAGE_API_KEY
# continues to override any of these (existing env pattern on the image side).
IMAGE_API_KEY_ENV: MappingProxyType[str, str | None] = MappingProxyType(
    {pid: info.key_env_var for pid, info in IMAGE_PROVIDERS.items()}
)

ALLOWED_IMAGE_PROVIDERS: frozenset[str] = frozenset(IMAGE_PROVIDERS.keys())

DEFAULT_TTS_PROVIDER: str = "openai"
DEFAULT_TTS_VOICE: str = ""
DEFAULT_TTS_AUTO_READ: bool = False
DEFAULT_TTS_AUTO_READ_RECAP: bool = False
# ENH-006-T2: speculative TTS synth during branch prefetch. Off by default —
# it spends TTS-provider credits on choices the user may never pick. The cache
# key embeds provider+voice, so a voice change after pregeneration means the
# next speak() misses and regenerates (correct, slightly wasteful).
DEFAULT_TTS_PREGENERATE_PREFETCH_AUDIO: bool = False
DEFAULT_AUTO_RECAP: bool = False
DEFAULT_RESUME_RECAP: bool = True
DEFAULT_RECAP_INTERVAL: int = 3

TTS_PROVIDER_CHOICES: tuple[tuple[str, str], ...] = (
    ("OpenAI", "openai"),
    ("ElevenLabs", "elevenlabs"),
    ("Deepgram", "deepgram"),
    ("Google Gemini", "gemini"),
    ("Kokoro (local)", "kokoro-onnx"),
)

TTS_API_KEY_ENV: MappingProxyType[str, str | None] = MappingProxyType(
    {
        "openai": "OPENAI_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "deepgram": "DEEPGRAM_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "kokoro-onnx": None,
    }
)

ALLOWED_TTS_PROVIDERS: frozenset[str] = frozenset(pid for _, pid in TTS_PROVIDER_CHOICES)

DEFAULT_GRAPHICS_MODE: str = "halfblock"

GRAPHICS_MODE_CHOICES: tuple[tuple[str, str], ...] = (
    ("Auto Detect", "auto"),
    ("Kitty TGP", "kitty"),
    ("Sixel", "sixel"),
    ("iTerm2", "iterm2"),
    ("Halfblock", "halfblock"),
)

ALLOWED_GRAPHICS_MODES: frozenset[str] = frozenset(pid for _, pid in GRAPHICS_MODE_CHOICES)
