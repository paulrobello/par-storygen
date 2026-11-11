"""Offline migration tests: all filesystem fixtures are isolated."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from storygen.storage import migrate_image_models as migration


def _write(path: Path, data: dict[str, Any]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False).encode()
    path.write_bytes(content)
    return content


def _config(model: str = "gpt-image-2", **extra: Any) -> dict[str, Any]:
    return {"provider": "openai", "model": model, **extra}


@pytest.mark.parametrize("model", sorted(migration.RETIRED_MODELS))
@pytest.mark.parametrize(
    "base_url", [None, "", "https://api.openai.com/v1", "https://api.openai.com/v1/"]
)
def test_migrates_only_known_fields(tmp_path: Path, model: str, base_url: str | None) -> None:
    path = tmp_path / "game.json"
    data: dict[str, Any] = {
        "version": 1,
        "image_config": _config(model, base_url=base_url, api_key="secret"),
        "character_image_config": _config(model),
        "nodes": {"model": model, "text": "雪", "media": "images/one.png"},
        "text_config": _config(model),
        "unknown": [1, None, False],
    }
    original = _write(path, data)
    plan = migration.plan_file(path, state=False)
    assert plan is not None
    assert path.read_bytes() == original
    result = json.loads(plan.replacement)
    data["image_config"]["model"] = migration.REPLACEMENT_MODEL
    data["character_image_config"]["model"] = migration.REPLACEMENT_MODEL
    assert result == data


@pytest.mark.parametrize(
    "config",
    [
        _config("gpt-image-2-custom"),
        _config("gpt-image-1"),
        _config("gpt-image-2.5-flare"),
        _config(migration.REPLACEMENT_MODEL),
        _config(provider="ollama"),
        _config(base_url="https://proxy.example/v1"),
        _config(base_url="https://api.openai.com.evil/v1"),
        _config(base_url="http://api.openai.com/v1"),
        {"model": "gpt-image-2"},
        {"provider": "openai"},
        {"provider": "openai", "model": []},
    ],
)
def test_skips_custom_unknown_and_missing(tmp_path: Path, config: dict[str, Any]) -> None:
    path = tmp_path / "game.json"
    original = _write(path, {"image_config": config})
    assert migration.plan_file(path, state=False) is None
    assert path.read_bytes() == original


def test_state_primary_portrait_and_independent_fallback(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    data: dict[str, Any] = {
        "image_provider_prefs": _config(
            base_url="https://proxy.example/v1",
            fallback_provider="openai",
            fallback_model="gpt-image-1.5",
        ),
        "character_image_provider_prefs": _config("gpt-image-1.5"),
        "provider_prefs": _config(),
        "api_key": "leave this alone",
    }
    _write(path, data)
    plan = migration.plan_file(path, state=True)
    assert plan is not None
    data["image_provider_prefs"]["fallback_model"] = migration.REPLACEMENT_MODEL
    data["character_image_provider_prefs"]["model"] = migration.REPLACEMENT_MODEL
    assert json.loads(plan.replacement) == data


def test_apply_backups_permissions_idempotence_and_scope(tmp_path: Path) -> None:
    state = tmp_path / "config" / "state.json"
    games = tmp_path / "games"
    game = games / "one" / "game.json"
    state_original = _write(state, {"image_provider_prefs": _config()})
    game_original = _write(game, {"image_config": _config()})
    ignored = games / "one" / "media.json"
    ignored_original = _write(ignored, {"image_config": _config()})
    plans = migration.plan_migration(state, games)
    backups = migration.apply_migration(plans)
    assert len(backups) == 2
    assert [p.read_bytes() for p in backups] == [state_original, game_original]
    for path in [*backups, state, game]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert ignored.read_bytes() == ignored_original
    assert migration.plan_migration(state, games) == []
    assert not list(tmp_path.rglob("*.tmp"))
    assert not list(tmp_path.rglob("*.lock"))


@pytest.mark.parametrize("bad", ['{"image_config":', '{"x":1,"x":2}', '{"x":NaN}', "[]"])
def test_invalid_json_refused_without_content(tmp_path: Path, bad: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(bad)
    with pytest.raises(migration.MigrationError):
        migration.plan_file(path, state=True)
    assert path.read_text() == bad


def test_changed_file_aborts_all_before_writing(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    game = tmp_path / "games" / "one" / "game.json"
    original = _write(state, {"image_provider_prefs": _config()})
    _write(game, {"image_config": _config()})
    plans = migration.plan_migration(state, tmp_path / "games")
    game.write_text('{"changed":true}')
    with pytest.raises(migration.MigrationError, match="changed"):
        migration.apply_migration(plans)
    assert state.read_bytes() == original
    assert not list(tmp_path.rglob("*.bak"))
    assert not list(tmp_path.rglob("*.lock"))


def test_change_during_backup_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "game.json"
    original = _write(path, {"image_config": _config()})
    plan = migration.plan_file(path, state=False)
    assert plan is not None
    create = migration._private_file  # pyright: ignore[reportPrivateUsage]

    def race(path: Path, content: bytes, *, suffix: str) -> Path:
        result = create(path, content, suffix=suffix)
        path.write_text('{"concurrent":true}')
        return result

    monkeypatch.setattr(migration, "_private_file", race)
    with pytest.raises(migration.MigrationError, match="changed"):
        migration.apply_migration([plan])
    assert path.read_text() == '{"concurrent":true}'
    assert next(tmp_path.glob("*.bak")).read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_existing_lock_and_symlink_refused(tmp_path: Path) -> None:
    path = tmp_path / "game.json"
    _write(path, {"image_config": _config()})
    plan = migration.plan_file(path, state=False)
    assert plan is not None
    lock = tmp_path / ".game.json.image-model-migration.lock"
    lock.write_text("active")
    with pytest.raises(migration.MigrationError, match="lock exists"):
        migration.apply_migration([plan])
    assert lock.read_text() == "active"
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(migration.MigrationError, match="non-regular"):
        migration.plan_file(link, state=False)


def test_atomic_replace_failure_keeps_original_and_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "game.json"
    original = _write(path, {"image_config": _config()})
    plan = migration.plan_file(path, state=False)
    assert plan is not None

    def fail(src: Path, dst: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        migration.apply_migration([plan])
    assert path.read_bytes() == original
    assert next(tmp_path.glob("*.bak")).read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_cli_default_is_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state = tmp_path / "state.json"
    original = _write(state, {"image_provider_prefs": _config(api_key="secret")})
    args = ["--state-file", str(state), "--games-dir", str(tmp_path / "games")]
    assert migration.main(args) == 0
    assert "Dry run" in capsys.readouterr().out
    assert state.read_bytes() == original
    assert len(list(tmp_path.iterdir())) == 1
    assert migration.main([*args, "--apply"]) == 0
    assert "secret" not in capsys.readouterr().out
    assert migration.main(args) == 0
    assert "0 file(s)" in capsys.readouterr().out


def test_failed_backup_never_replaces_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "game.json"
    original = _write(path, {"image_config": _config()})
    plan = migration.plan_file(path, state=False)
    assert plan is not None

    def fail(path: Path, content: bytes, *, suffix: str) -> Path:
        raise OSError("simulated backup failure")

    monkeypatch.setattr(migration, "_private_file", fail)
    with pytest.raises(OSError):
        migration.apply_migration([plan])
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.lock"))


def test_non_openai_fallback_and_unknown_sections_untouched(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = _write(
        path,
        {
            "image_provider_prefs": {
                "provider": "gemini",
                "fallback_provider": "ollama",
                "fallback_model": "gpt-image-2",
            },
            "character_image_provider_prefs": None,
            "other": _config(),
        },
    )
    assert migration.plan_file(path, state=True) is None
    assert path.read_bytes() == original


def test_missing_roots_are_noop(tmp_path: Path) -> None:
    assert (
        migration.plan_migration(tmp_path / "missing-state.json", tmp_path / "missing-games") == []
    )
    assert list(tmp_path.iterdir()) == []
