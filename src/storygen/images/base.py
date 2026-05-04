"""Protocol describing what any image provider must expose."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import NamedTuple, Protocol, runtime_checkable


class ReferencePortrait(NamedTuple):
    """A named reference image for scene generation.

    Providers that support reference images use the ``name`` field to build
    prompt guidance telling the LLM which character each image depicts (e.g.
    "Image 1: Alice", "Image 2: current scene artwork").  The ``data`` field
    holds the raw PNG bytes.
    """

    name: str
    data: bytes


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
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes: ...
