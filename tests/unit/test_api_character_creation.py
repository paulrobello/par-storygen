"""Character creation accepts a reference upload without a second image render."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from storygen.core.models import Character
from storygen.storage.library import library_reference_path
from storygen_api.deps import get_wizard_image_provider
from storygen_api.main import create_app
from storygen_api.routers import characters
from storygen_api.security import verify_token


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (2, 2), "blue").save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("with_reference", [False, True])
@pytest.mark.parametrize("portrait_fails", [False, True])
def test_create_character(
    xdg_tmp: Path, monkeypatch: pytest.MonkeyPatch, with_reference: bool, portrait_fails: bool
) -> None:
    del xdg_tmp
    portrait = AsyncMock(return_value=_png())
    if portrait_fails:
        portrait.side_effect = RuntimeError("provider unavailable")
    provider = SimpleNamespace(generate_portrait=portrait)
    run = AsyncMock(
        return_value=SimpleNamespace(
            output=[
                Character(
                    id="c1",
                    name="Generated",
                    backstory="A scholar.",
                    personality="Curious.",
                    physical_description="A blue cloak.",
                    introduced_at_node_id="root",
                )
            ]
        )
    )
    monkeypatch.setattr(characters, "get_app_config", lambda: SimpleNamespace(text_config=None))
    monkeypatch.setattr(characters, "build_text_model", MagicMock(return_value=None))
    factory = MagicMock(return_value=SimpleNamespace(run=run))
    monkeypatch.setattr(characters.agent_mod, "build_catalog_character_agent", factory)
    app = create_app()
    app.dependency_overrides[verify_token] = lambda: None
    app.dependency_overrides[get_wizard_image_provider] = lambda: provider
    with TestClient(app) as client:
        if with_reference:
            response = client.post(
                "/api/characters/create-with-reference",
                data={"concept": "a scholar", "name": "Alyx"},
                files={"reference_image": ("ref.png", _png(), "image/png")},
            )
        else:
            response = client.post(
                "/api/characters/create", json={"concept": "a scholar", "name": "Alyx"}
            )
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["name"] == "Alyx"
    assert entry["has_reference_image"] is with_reference
    run.assert_awaited_once_with("Create a character named 'Alyx'. a scholar")
    portrait.assert_awaited_once()
    assert portrait.await_args is not None
    assert portrait.await_args.kwargs.get("reference_image") == (_png() if with_reference else None)
    if with_reference:
        assert library_reference_path(entry["id"]).read_bytes() == _png()


@pytest.mark.parametrize("image_bytes", [b"not an image", b""])
def test_invalid_reference_rejected_before_generation(
    monkeypatch: pytest.MonkeyPatch, image_bytes: bytes
) -> None:
    factory = MagicMock()
    monkeypatch.setattr(characters.agent_mod, "build_catalog_character_agent", factory)
    app = create_app()
    app.dependency_overrides[verify_token] = lambda: None
    app.dependency_overrides[get_wizard_image_provider] = lambda: SimpleNamespace()
    with TestClient(app) as client:
        response = client.post(
            "/api/characters/create-with-reference",
            data={"concept": "a scholar"},
            files={"reference_image": ("bad.png", image_bytes, "image/png")},
        )
    assert response.status_code == 400
    factory.assert_not_called()
