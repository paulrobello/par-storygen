"""Routed image provider — primary + optional fallback.

Phase 4 of the v1.1 image-provider plan: a thin wrapper that hands each
generate-call to the primary provider, and on a terminal exception
(retries already exhausted by the concrete provider's own tenacity loop)
hands the same call to an optional fallback provider before giving up.

The router does NOT own ref-loss bookkeeping — that is wired at provider
construction time by the factory (see :mod:`storygen.images.provider_factory`).
It only owns the "primary exploded, switching to <fallback>" transparency
surface via the ``on_fallback`` callback.

Layer rule: this module imports only from :mod:`storygen.images.base` (the
``ImageProvider`` Protocol). It does NOT import concrete provider classes —
callers assemble primary/fallback and hand them in.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable

from storygen.images.base import ImageProvider, ReferencePortrait


class RoutedImageProvider:
    """Route image generation to a primary, falling back on terminal failure.

    Each concrete provider runs its own tenacity retry loop. The router
    catches whatever exception escapes after retries are spent; if a
    ``fallback`` was provided it invokes ``on_fallback`` (transparency)
    and re-attempts the call against the fallback.

    If BOTH primary and fallback raise, the PRIMARY's exception is
    re-raised — the user chose the primary, and its error context is the
    more useful signal to surface. The fallback's exception is chained as
    the primary's ``__cause__`` (``raise primary_exc from fb_exc``) so
    operators debugging a "both providers down" incident see both
    tracebacks in the chain.
    """

    def __init__(
        self,
        primary: ImageProvider,
        fallback: ImageProvider | None = None,
        *,
        primary_label: str = "primary",
        fallback_label: str = "fallback",
        on_fallback: Callable[[str, Exception], None] | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._primary_label = primary_label
        self._fallback_label = fallback_label
        self._on_fallback = on_fallback

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        try:
            return await self._primary.generate_portrait(
                description,
                transparent=transparent,
                art_style=art_style,
                on_partial=on_partial,
                reference_image=reference_image,
            )
        except Exception as exc:
            return await self._handle_fallback_portrait(
                exc,
                description=description,
                transparent=transparent,
                art_style=art_style,
                on_partial=on_partial,
                reference_image=reference_image,
            )

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes:
        try:
            return await self._primary.generate_scene(
                prompt,
                reference_portraits=reference_portraits,
                art_style=art_style,
                on_partial=on_partial,
            )
        except Exception as exc:
            return await self._handle_fallback_scene(
                exc,
                prompt=prompt,
                reference_portraits=reference_portraits,
                art_style=art_style,
                on_partial=on_partial,
            )

    async def _handle_fallback_portrait(
        self,
        primary_exc: Exception,
        *,
        description: str,
        transparent: bool,
        art_style: str,
        on_partial: Callable[[bytes], Awaitable[None]] | None,
        reference_image: bytes | None = None,
    ) -> bytes:
        if self._fallback is None:
            raise primary_exc
        if self._on_fallback is not None:
            # Never let the transparency callback crash the render.
            with contextlib.suppress(Exception):
                self._on_fallback(self._fallback_label, primary_exc)
        try:
            return await self._fallback.generate_portrait(
                description,
                transparent=transparent,
                art_style=art_style,
                on_partial=on_partial,
                reference_image=reference_image,
            )
        except Exception as fb_exc:
            # Fallback also failed — surface the primary's error (the user
            # asked for the primary), but chain the fallback's exception
            # as __cause__ so operators see both tracebacks.
            raise primary_exc from fb_exc

    async def _handle_fallback_scene(
        self,
        primary_exc: Exception,
        *,
        prompt: str,
        reference_portraits: list[ReferencePortrait],
        art_style: str,
        on_partial: Callable[[bytes], Awaitable[None]] | None,
    ) -> bytes:
        if self._fallback is None:
            raise primary_exc
        if self._on_fallback is not None:
            with contextlib.suppress(Exception):
                self._on_fallback(self._fallback_label, primary_exc)
        try:
            return await self._fallback.generate_scene(
                prompt,
                reference_portraits=reference_portraits,
                art_style=art_style,
                on_partial=on_partial,
            )
        except Exception as fb_exc:
            # Fallback also failed — surface the primary's error, chaining
            # the fallback exception as __cause__ for debuggability.
            raise primary_exc from fb_exc
