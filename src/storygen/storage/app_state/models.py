"""Persisted-prefs dataclasses for app state.

Frozen dataclasses persisted to ``state.json`` via the writers in
:mod:`.io`. Field defaults reference the constants in :mod:`.defaults`.
"""

from __future__ import annotations

from dataclasses import dataclass

from storygen.core.models import ReaderLevel
from storygen.storage.app_state.defaults import (
    DEFAULT_ART_STYLE,
    DEFAULT_CHARACTER_IMAGE_MODEL,
    DEFAULT_CHARACTER_IMAGE_PROVIDER,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_IMAGE_PROVIDER,
    DEFAULT_NARRATION_STYLE,
    DEFAULT_PACING,
    DEFAULT_READER_LEVEL,
    DEFAULT_TARGET_MAJOR_BEATS,
    DEFAULT_TEXT_MODEL,
    DEFAULT_TEXT_PROVIDER,
    DEFAULT_TONE_PRESET,
    DEFAULT_TTS_AUTO_READ,
    DEFAULT_TTS_AUTO_READ_RECAP,
    DEFAULT_TTS_PREGENERATE_PREFETCH_AUDIO,
    DEFAULT_TTS_PROVIDER,
    MAX_TARGET_MAJOR_BEATS,
    MIN_TARGET_MAJOR_BEATS,
)


def clamp_target_beats(value: object) -> int:
    """Coerce ``value`` to an int and clamp into [MIN, MAX].

    Falls back to ``DEFAULT_TARGET_MAJOR_BEATS`` if the value can't be coerced.
    Consumed by :func:`storygen.storage.app_state.io.read_wizard_defaults`.
    """
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_TARGET_MAJOR_BEATS
    return max(MIN_TARGET_MAJOR_BEATS, min(MAX_TARGET_MAJOR_BEATS, n))


@dataclass(frozen=True)
class ProviderPrefs:
    """Persisted text-provider preferences (Settings screen → state.json)."""

    provider: str = DEFAULT_TEXT_PROVIDER  # one of PROVIDER_CHOICES ids
    model: str = DEFAULT_TEXT_MODEL
    base_url: str = ""  # empty → provider factory picks its default
    api_key: str = ""  # blank → fall back to env var


@dataclass(frozen=True)
class ImageProviderPrefs:
    """Persisted image-provider preferences (Settings screen → state.json).

    ``fallback_provider``/``fallback_model`` configure the router's fallback
    target for transient primary-provider failures (added in Phase 3). Empty
    strings mean "no fallback."
    """

    provider: str = DEFAULT_IMAGE_PROVIDER  # one of IMAGE_PROVIDER_CHOICES ids
    model: str = DEFAULT_IMAGE_MODEL
    base_url: str = ""  # empty → factory picks the provider's default URL
    api_key: str = ""  # blank → fall back to env var
    fallback_provider: str = ""  # "" = no fallback
    fallback_model: str = ""  # "" = use SUGGESTED_IMAGE_MODELS[fallback_provider][0]


@dataclass(frozen=True)
class CharacterImageProviderPrefs:
    """Persisted character-portrait image-provider preferences."""

    provider: str = DEFAULT_CHARACTER_IMAGE_PROVIDER  # one of IMAGE_PROVIDER_CHOICES ids
    model: str = DEFAULT_CHARACTER_IMAGE_MODEL
    base_url: str = ""  # empty → factory picks the provider's default URL
    api_key: str = ""  # blank → fall back to env var


@dataclass(frozen=True)
class WizardDefaults:
    """Persisted defaults that pre-fill the new-story wizard widgets."""

    theme: str = ""
    tone_preset: str = DEFAULT_TONE_PRESET
    tone_descriptor: str = ""  # only used when preset == "custom"
    narration_style: str = DEFAULT_NARRATION_STYLE
    art_style: str = DEFAULT_ART_STYLE
    target_major_beats: int = DEFAULT_TARGET_MAJOR_BEATS
    reader_level: ReaderLevel = DEFAULT_READER_LEVEL
    pacing: str = DEFAULT_PACING
    characters: str = ""
    save_to_catalog: bool = True


@dataclass(frozen=True)
class TTSPrefs:
    """Persisted TTS preferences (Settings screen → state.json)."""

    provider: str = DEFAULT_TTS_PROVIDER  # one of TTS_PROVIDER_CHOICES ids
    api_key: str = ""  # blank → fall back to provider env var
    voice: str = ""  # blank → use provider default
    auto_read: bool = DEFAULT_TTS_AUTO_READ
    auto_read_recap: bool = DEFAULT_TTS_AUTO_READ_RECAP
    # ENH-006-T2: speculative narration synth during branch prefetch. Off by
    # default (spends provider credits). Uses the voice configured at prefetch
    # time — change voice and the next speak() regenerates.
    pregenerate_prefetch_audio: bool = DEFAULT_TTS_PREGENERATE_PREFETCH_AUDIO
