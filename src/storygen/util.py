"""Cross-cutting utilities."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def open_in_system_viewer(path: Path) -> None:
    """Open ``path`` in the operating system's default application.

    Best-effort: failures are swallowed (e.g. headless CI, missing helper).
    The path must already exist; callers should check before invoking.

    Security: uses list-form ``subprocess.Popen`` (never ``shell=True``), so
    the path argument cannot be used for shell injection.  Path traversal
    safety relies on callers having validated ``path`` via
    ``paths.safe_join`` before reaching this function (SEC-004).
    """
    if not path.exists():
        return
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]  # pragma: no cover
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        # No viewer registered, command not on PATH, etc. — surface nothing.
        return
