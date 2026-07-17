"""Shared retry classification for OpenAI-compatible image providers.

Both :mod:`storygen.images.ollama_provider` and
:mod:`storygen.images.zai_provider` wrap an ``AsyncOpenAI`` client against an
OpenAI-compatible endpoint and share the exact same retry policy: retry on
transient ``openai.APIError`` / ``httpx.TransportError`` faults, but never
retry ``openai.NotFoundError`` (a 404 means the model id is wrong or not
pulled locally — permanent until the user acts). Hoisted here so the two
providers cannot drift.
"""

from __future__ import annotations

import httpx
import openai
from openai import NotFoundError

# Transient API + network faults worth retrying. We deliberately do NOT retry
# on ``httpx.HTTPStatusError`` — a 4xx from the image URL fetch is almost
# always permanent (expired URL, 404 on delayed generation). Nor do we retry
# ``openai.NotFoundError`` (subclass of ``APIError``): that means the model
# id is wrong, which will not fix itself on retry.
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    openai.APIError,
    httpx.TransportError,
)


def is_retryable(exc: BaseException) -> bool:
    """Return True if ``exc`` should trigger a tenacity retry.

    Excludes :class:`openai.NotFoundError` — permanent misconfiguration
    (wrong model id on Z.AI, or Ollama model not pulled locally).
    """
    if isinstance(exc, NotFoundError):
        return False
    return isinstance(exc, _RETRYABLE_EXCEPTIONS)
