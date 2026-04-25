"""Raw LLM response cache — dev/debug only.

When ``app_state.llm_cache_enabled()`` is True, the pipeline dumps every
agent exchange (beat/illustration/summary/blurb) to a sidecar JSON file
keyed by (node_id, agent_name) under the save's directory. Disabled by
default; no player-visible behavior.

Layout::

    $XDG_DATA_HOME/storygen/games/<save-id>/llm/
        <node-id>-beat.json
        <node-id>-illustration.json
        <node-id>-summary.json
        <node-id>-blurb.json  (root-node blurb backfill only)

Wizard-stage agents (theme / characters / adapt-backstory) pre-date the
save directory and are out of scope — the cache is strictly per-node.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from storygen.storage import paths


def llm_cache_dir(save_id: str) -> Path:
    """Absolute path to the per-save LLM cache directory."""
    return paths.game_dir(save_id) / "llm"


def llm_exchange_path(save_id: str, node_id: str, agent_name: str) -> Path:
    """Sidecar file for one agent call keyed by (node, agent)."""
    return llm_cache_dir(save_id) / f"{node_id}-{agent_name}.json"


def dump_llm_exchange(save_id: str, node_id: str, agent_name: str, raw_bytes: bytes) -> None:
    """Atomically write the raw LLM exchange bytes to the sidecar file.

    ``raw_bytes`` is pydantic-ai's ``result.all_messages_json()`` output.
    Atomic write via ``.tmp + os.replace`` so a concurrent reader never
    sees a half-written file. Best-effort: any ``OSError`` is swallowed
    (the cache is debug-only; failure must not crash gameplay) and any
    leftover ``.tmp`` file is removed.
    """
    path = llm_exchange_path(save_id, node_id, agent_name)
    tmp = path.with_suffix(".json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Restrict the cache dir to owner-only: LLM exchanges may contain
        # prompt content that should not be world-readable.
        os.chmod(path.parent, 0o700)
        tmp.write_bytes(raw_bytes)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        # Debug cache; never raise into gameplay.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def read_llm_exchange(save_id: str, node_id: str, agent_name: str) -> bytes | None:
    """Read back a previously-dumped exchange, or ``None`` if missing/unreadable.

    Intended for dev tooling that wants to re-parse or diff exchanges
    post-hoc. Not called by the pipeline itself.
    """
    path = llm_exchange_path(save_id, node_id, agent_name)
    try:
        return path.read_bytes()
    except OSError:
        return None
