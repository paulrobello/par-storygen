"""TTS (text-to-speech) support via par-cli-tts."""

from storygen.tts.cache import (
    relative_tts_cache_path,
    synthesize_to_cache,
    tts_cache_path,
)
from storygen.tts.player import TTSPlayer, TTSState

__all__ = [
    "TTSPlayer",
    "TTSState",
    "relative_tts_cache_path",
    "synthesize_to_cache",
    "tts_cache_path",
]
