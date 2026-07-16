from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from storygen.core.presets import load_curated_presets, load_custom_presets

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("")
async def list_presets() -> dict[str, Any]:
    curated = load_curated_presets()
    custom = load_custom_presets()
    return {
        "curated": [p.model_dump() for p in curated],
        "custom": [p.model_dump() for p in custom],
    }
