"""Story preset listing route."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from storygen.core.presets import load_curated_presets, load_custom_presets
from storygen_api.security import verify_token

router = APIRouter(
    prefix="/api/presets",
    tags=["presets"],
    # SEC-104: presets can contain personal theme text; gate behind the shared
    # bearer token, matching the ``routers/games.py`` idiom.
    dependencies=[Depends(verify_token)],
)


@router.get("")
async def list_presets() -> dict[str, Any]:
    curated = load_curated_presets()
    custom = load_custom_presets()
    return {
        "curated": [p.model_dump() for p in curated],
        "custom": [p.model_dump() for p in custom],
    }
