"""Regression tests for the ``/api/images`` surface (SEC-101).

SEC-101 removed the unauthenticated ``StaticFiles`` mount over ``games_root``
from ``storygen_api.main``. That mount bypassed FastAPI dependencies
(including ``verify_token``) and exposed every file under the save-data
directory — including ``game.json`` and ``llm/`` transcripts — to any
unauthenticated client.

The routers in ``routers/images.py`` already serve every asset the frontend
needs (scene PNGs, portrait PNGs, outfit endpoints), each behind
``verify_token``. These tests pin that contract: the side-door stays closed,
and the legitimate router routes keep serving.

Note on auth: a server token is configured and sent on each request so that
matched router routes clear ``verify_token``. The SEC-101 regression
assertions (``game.json`` / ``llm/`` → 404) hold regardless of auth: those
paths match no router route, so FastAPI returns 404 before ``verify_token``
runs — which is exactly the property the deleted mount violated.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient

from storygen.llm.models import (
    Character,
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.storage.save import GameSave, save_game


def _make_save(xdg_tmp: Any) -> GameSave:
    """Build and persist a minimal GameSave under the isolated XDG root."""
    from datetime import UTC, datetime
    from uuid import uuid4

    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You open your eyes.",
        choices=[StoredChoice(id="c1", text="Look around")],
        is_major=True,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save = GameSave(
        version=4,
        id=uuid4(),
        theme=Theme(title="T", setting="S", premise="P", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        character_image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[
            Character(
                id="alyx",
                name="Alyx",
                backstory="b",
                personality="p",
                physical_description="d",
                portrait_path=None,
                portrait_prompt=None,
                introduced_at_node_id="root",
            )
        ],
        nodes={"root": root},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    save_game(save)
    return save


@pytest.fixture
def app_client(xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient with a server token configured (auth-gated mode).

    A token is set (and sent on every request via ``_AUTH``) so requests that
    match a router route clear ``verify_token``. This mirrors the
    ``test_api_rate_limit`` fixture. The SEC-101 regression assertions
    (``game.json`` / ``llm/`` → 404) are independent of auth: those paths
    match no router route, so FastAPI returns 404 before ``verify_token``
    runs — which is exactly the property the mount violated.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "sec101-test-token")
    from storygen_api.security import reset_token_cache

    reset_token_cache()
    from storygen_api import deps

    deps.get_app_config.cache_clear()
    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client

    reset_token_cache()
    deps.get_app_config.cache_clear()


_AUTH = {"Authorization": "Bearer sec101-test-token"}


# Minimal 1x1 transparent PNG used to prove the router route serves a real file.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_save_data_game_json_404(app_client: TestClient, xdg_tmp: Any) -> None:
    """SEC-101: ``game.json`` under the save root is not reachable via HTTP.

    This is the load-bearing regression: if the ``StaticFiles`` mount over
    ``games_root`` is ever re-introduced, this path returns 200 and the test
    fails. With the mount removed, no router route matches and FastAPI
    returns 404.
    """
    save = _make_save(xdg_tmp)
    game_id = str(save.id)

    # Sanity: the file exists on disk (otherwise a 404 proves nothing).
    from storygen.storage import paths

    game_json = paths.game_dir(game_id) / "game.json"
    assert game_json.exists(), f"game.json not written at {game_json}"

    r = app_client.get(f"/api/images/{game_id}/game.json", headers=_AUTH)
    assert r.status_code == 404, (
        f"expected 404 (mount removed), got {r.status_code}; the StaticFiles "
        "mount over games_root may have been re-introduced (SEC-101 regression)"
    )


def test_save_data_llm_dir_not_served(app_client: TestClient, xdg_tmp: Any) -> None:
    """SEC-101: the ``llm/`` transcript directory is not reachable via HTTP.

    ``llm/`` sits under ``games_root`` and holds raw LLM request/response
    transcripts. The mount exposed it; with the mount gone it must 404.
    """
    save = _make_save(xdg_tmp)
    game_id = str(save.id)
    from storygen.storage import paths

    llm_dir = paths.game_dir(game_id) / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)
    (llm_dir / "beat-root.json").write_text("{}")

    r = app_client.get(f"/api/images/{game_id}/llm/beat-root.json", headers=_AUTH)
    assert r.status_code == 404, (
        f"expected 404 for llm/ transcript, got {r.status_code} "
        "(SEC-101 regression: save-data directory is being served)"
    )


def test_scene_router_route_still_serves(app_client: TestClient, xdg_tmp: Any) -> None:
    """SEC-101 companion: the legitimate scene router route still serves PNGs.

    Deleting the mount must not break image serving — the token-gated router
    route ``GET /api/images/{game_id}/scene/{node_id}``` is the sanctioned
    path. With no image on disk the handler returns its own 404; after writing
    the PNG where the router expects it, the same route returns 200 +
    ``image/png`` — proving the router (not a static mount) owns serving.
    """
    from storygen.storage import paths

    save = _make_save(xdg_tmp)
    game_id = str(save.id)
    node_id = "root"

    # No image on disk yet → router handler returns its own 404.
    r = app_client.get(f"/api/images/{game_id}/scene/{node_id}", headers=_AUTH)
    assert r.status_code == 404

    # Write a scene PNG where the router expects it and confirm the handler
    # serves it (200, image/png).
    image_path = paths.node_image_path(game_id, node_id)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(_PNG_BYTES)

    r = app_client.get(f"/api/images/{game_id}/scene/{node_id}", headers=_AUTH)
    assert r.status_code == 200, f"router scene route should serve PNG, got {r.status_code}"
    assert r.headers["content-type"] == "image/png"
