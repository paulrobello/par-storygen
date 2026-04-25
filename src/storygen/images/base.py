"""Protocol describing what any image provider must expose."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class ImageProvider(Protocol):
    """Uniform surface for text-to-image backends."""

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes: ...

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[bytes],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes: ...
