"""Offline, opt-in migration of retired OpenAI image models.

Stop all storygen TUI/API processes first. Preview with::

    uv run python -m storygen.storage.migrate_image_models

Apply with ``--apply``. Each changed file gets a private, byte-exact sibling
``.image-model-<random>.bak`` before atomic replacement. Restore that backup
while the app is stopped to undo a migration. Backups can contain credentials.
No provider calls, schema upgrades, environment or .env changes are performed.
Change detection catches intervening writes; it cannot lock out app processes
that do not honor this command's lock. This is NOT an online migration or a
multi-file transaction: on an error, earlier successful replacements remain.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from collections.abc import Generator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from storygen.storage import paths

REPLACEMENT_MODEL = "gpt-image-2.6-flare"
# Exact known aliases only. Do not match prefixes or future/custom snapshots.
RETIRED_MODELS = frozenset({"gpt-image-2", "gpt-image-2-2026-04-21", "gpt-image-1.5"})
_OPENAI_URLS = (None, "", "https://api.openai.com/v1", "https://api.openai.com/v1/")


class MigrationError(Exception):
    """Migration refused without exposing JSON content or credentials."""


@dataclass(frozen=True)
class FilePlan:
    path: Path
    original: bytes
    replacement: bytes
    identity: tuple[int, int, int, int, int]
    fields: tuple[str, ...]


def _identity(path: Path) -> tuple[int, int, int, int, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.parent.is_symlink():
        raise MigrationError(f"Refusing non-regular file or linked game directory: {path}")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError("non-finite JSON number")


def plan_file(path: Path, *, state: bool) -> FilePlan | None:
    """Plan only known schema fields, preserving every other JSON value."""
    identity = _identity(path)
    original = path.read_bytes()
    if _identity(path) != identity:
        raise MigrationError(f"File changed while reading: {path}")
    try:
        data: Any = json.loads(original, object_pairs_hook=_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError):
        raise MigrationError(f"Invalid or ambiguous JSON: {path}") from None
    if not isinstance(data, dict):
        raise MigrationError(f"Expected JSON object: {path}")
    document = cast(dict[str, Any], data)
    fields: list[str] = []
    keys = (
        ("image_provider_prefs", "character_image_provider_prefs")
        if state
        else ("image_config", "character_image_config")
    )
    for key in keys:
        raw: Any = document.get(key)
        if not isinstance(raw, dict):
            continue
        config = cast(dict[str, Any], raw)
        model: Any = config.get("model")
        if (
            config.get("provider") == "openai"
            and config.get("base_url") in _OPENAI_URLS
            and isinstance(model, str)
            and model in RETIRED_MODELS
        ):
            config["model"] = REPLACEMENT_MODEL
            fields.append(f"{key}.model")
        # Only scene preferences support fallback. Its endpoint is independent
        # of the primary base_url (runtime.adapters.build_fallback_config).
        fallback: Any = config.get("fallback_model")
        if (
            state
            and key == "image_provider_prefs"
            and config.get("fallback_provider") == "openai"
            and isinstance(fallback, str)
            and fallback in RETIRED_MODELS
        ):
            config["fallback_model"] = REPLACEMENT_MODEL
            fields.append(f"{key}.fallback_model")
    if not fields:
        return None
    replacement = (
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode()
    return FilePlan(path, original, replacement, identity, tuple(fields))


def plan_migration(state_file: Path, games_dir: Path) -> list[FilePlan]:
    """Read only state.json and immediate games/*/game.json files."""
    candidates: list[tuple[Path, bool]] = []
    if state_file.exists() or state_file.is_symlink():
        candidates.append((state_file, True))
    candidates.extend((path, False) for path in sorted(games_dir.glob("*/game.json")))
    plans: list[FilePlan] = []
    for path, state in candidates:
        plan = plan_file(path, state=state)
        if plan is not None:
            plans.append(plan)
    return plans


def _check_unchanged(plan: FilePlan) -> None:
    if _identity(plan.path) != plan.identity or plan.path.read_bytes() != plan.original:
        raise MigrationError(f"File changed since preview; rerun migration: {plan.path}")


@contextmanager
def _lock(path: Path) -> Generator[None]:
    lock = path.with_name(f".{path.name}.image-model-migration.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise MigrationError(
            f"Migration lock exists (check for another migration): {lock}"
        ) from None
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def _private_file(path: Path, content: bytes, *, suffix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.image-model-", suffix=suffix, dir=path.parent)
    target = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def apply_migration(plans: Sequence[FilePlan]) -> list[Path]:
    """Back up and atomically replace changed files; return backup paths.

    All files are checked before any writes and again immediately before each
    replacement. Exclusive sibling locks serialize this migration command only.
    """
    backups: list[Path] = []
    with ExitStack() as stack:
        for plan in plans:
            stack.enter_context(_lock(plan.path))
        for plan in plans:
            _check_unchanged(plan)
        for plan in plans:
            _check_unchanged(plan)
            backup = _private_file(plan.path, plan.original, suffix=".bak")
            backups.append(backup)
            temporary = _private_file(plan.path, plan.replacement, suffix=".tmp")
            try:
                _check_unchanged(plan)
                os.replace(temporary, plan.path)
                # Persist the backup and replacement directory entries as well.
                fd = os.open(plan.path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                temporary.unlink(missing_ok=True)
    return backups


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write changes; stop all storygen processes first"
    )
    parser.add_argument("--state-file", type=Path, default=paths.config_root() / "state.json")
    parser.add_argument("--games-dir", type=Path, default=paths.games_root())
    args = parser.parse_args(argv)
    try:
        plans = plan_migration(args.state_file, args.games_dir)
        for plan in plans:
            print(f"{plan.path}: {', '.join(plan.fields)} -> {REPLACEMENT_MODEL}")
        if args.apply:
            backups = apply_migration(plans)
            for backup in backups:
                print(f"Backup: {backup}")
            print(f"Migrated {len(plans)} file(s).")
        else:
            print(
                f"Dry run: {len(plans)} file(s) would change. Stop storygen, then rerun with --apply."
            )
    except (OSError, MigrationError) as error:
        # Never echo a raw JSON parsing exception or file content.
        print(f"Migration stopped: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
