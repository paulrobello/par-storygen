"""OpenAPI snapshot test — catches REST contract drift (ARC-108).

The committed ``data/openapi.json`` is the authoritative REST contract. If
``app.openapi()`` changes (schema field renamed, route added/removed, response
shape altered), this test fails with a diff and instructions to regenerate.

Regenerate after an intended change::

    STORYGEN_UPDATE_OPENAPI=1 uv run pytest tests/unit/test_api_openapi_snapshot.py -q

Then also update ``web/src/lib/api.ts`` to match.
"""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

_SNAPSHOT_PATH = Path(__file__).parent / "data" / "openapi.json"


def _normalize(spec: dict[str, Any]) -> str:
    """Normalize the OpenAPI spec for deterministic comparison.

    Drops volatile ``info.version`` (tracks package version, changes on
    release) and serializes with ``sort_keys`` so dict ordering does not
    cause flakes.
    """
    spec_dict = dict(spec)
    info = spec_dict.get("info")
    if isinstance(info, dict):
        info_typed = cast(dict[str, Any], info)
        spec_dict["info"] = {k: v for k, v in info_typed.items() if k != "version"}
    return json.dumps(spec_dict, sort_keys=True, indent=2, ensure_ascii=False)


def _build_spec() -> dict[str, Any]:
    """Build the app and return its OpenAPI spec dict."""
    from storygen_api.main import app

    return app.openapi()


def test_openapi_matches_snapshot() -> None:
    """The REST contract must match the committed snapshot.

    On mismatch: review the diff below. If the change is intended, regenerate
    the snapshot with::

        STORYGEN_UPDATE_OPENAPI=1 uv run pytest tests/unit/test_api_openapi_snapshot.py -q

    Then update ``web/src/lib/api.ts`` to match the new contract.
    """
    normalized = _normalize(_build_spec())

    if os.environ.get("STORYGEN_UPDATE_OPENAPI") == "1":
        _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT_PATH.write_text(normalized + "\n", encoding="utf-8")
        pytest.skip("OpenAPI snapshot regenerated; review and commit the new file.")

    if not _SNAPSHOT_PATH.exists():
        pytest.fail(
            f"OpenAPI snapshot not found at {_SNAPSHOT_PATH}.\n"
            "Regenerate with:\n"
            "  STORYGEN_UPDATE_OPENAPI=1 uv run pytest "
            "tests/unit/test_api_openapi_snapshot.py -q"
        )

    expected = _SNAPSHOT_PATH.read_text(encoding="utf-8").strip()
    actual = normalized.strip()

    if actual != expected:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile="committed snapshot (tests/unit/data/openapi.json)",
                tofile="current app.openapi()",
                n=3,
            )
        )
        pytest.fail(
            "OpenAPI contract drift detected.\n\n"
            "If this is an intended change, regenerate the snapshot:\n"
            "  STORYGEN_UPDATE_OPENAPI=1 uv run pytest "
            "tests/unit/test_api_openapi_snapshot.py -q\n"
            "Then update web/src/lib/api.ts to match.\n\n"
            f"Diff:\n{diff}"
        )
