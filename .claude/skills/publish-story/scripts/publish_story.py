#!/usr/bin/env python3
"""Publish an exported par-storygen story folder to pardev."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

REMOTE_HOST = os.environ.get("PUBLISH_STORY_REMOTE", "root@lenny1.par-com.net")
REMOTE_BASE = os.environ.get("PUBLISH_STORY_REMOTE_BASE", "/docker/pardev/data/par-storygen")
PUBLIC_BASE = os.environ.get("PUBLISH_STORY_PUBLIC_URL", "https://pardev.net/par-storygen")
_SAFE_FOLDER_RE = re.compile(r"^[A-Za-z0-9._-]+$")


REMOTE_INDEX_SCRIPT = r"""
set -eu
remote_base=$1
href=$2
label=$3

mkdir -p "$remote_base"
index="$remote_base/index.html"

if [ ! -f "$index" ]; then
  cat > "$index" <<'HTML'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Par Storygen Exports</title>
</head>
<body>
  <h1>Par Storygen Exports</h1>
  <ul>
  </ul>
</body>
</html>
HTML
fi

if ! grep -Fq "href=\"$href\"" "$index"; then
  line="<li><a href=\"$href\">$label</a></li>"
  tmp=$(mktemp)
  awk -v line="$line" '
    BEGIN { inserted = 0 }
    {
      low = tolower($0)
      if (!inserted && low ~ /<\/ul>/) {
        print "    " line
        inserted = 1
      }
      print
    }
    END {
      if (!inserted) {
        print line
      }
    }
  ' "$index" > "$tmp"
  cat "$tmp" > "$index"
  rm -f "$tmp"
fi
"""


def _run(cmd: list[str], *, dry_run: bool, input_text: str | None = None) -> None:
    printable = " ".join(cmd)
    if dry_run:
        print(f"DRY RUN: {printable}")
        return
    subprocess.run(cmd, input=input_text, text=True, check=True)


def _open_url(url: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY RUN: open {url}")
        return
    if sys.platform == "darwin":
        cmd = ["open", url]
    else:
        cmd = ["xdg-open", url]
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        print(f"Could not open browser automatically: {exc}", file=sys.stderr)


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish an exported par-storygen story folder to pardev.net.",
    )
    parser.add_argument(
        "story_dir",
        nargs="?",
        help="Path to the exported story folder to publish.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print actions without rsyncing, SSHing, or opening a browser.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the public story index URL after publishing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not args.story_dir:
        print("Missing story folder path. Ask the user for the exported story folder path.", file=sys.stderr)
        return 2

    story_dir = Path(args.story_dir).expanduser().resolve()
    if not story_dir.is_dir():
        print(f"Story folder does not exist or is not a directory: {story_dir}", file=sys.stderr)
        return 2

    story_name = story_dir.name
    if not _SAFE_FOLDER_RE.fullmatch(story_name):
        print(
            "Story folder name must contain only letters, numbers, dots, underscores, and hyphens: "
            f"{story_name}",
            file=sys.stderr,
        )
        return 2

    remote_base = REMOTE_BASE.rstrip("/")
    remote_story_dir = f"{remote_base}/{story_name}"
    public_base = PUBLIC_BASE.rstrip("/")
    story_url = f"{public_base}/{quote(story_name)}/"
    label = _html_escape(story_name)

    print(f"Publishing {story_dir} -> {REMOTE_HOST}:{remote_story_dir}/")
    _run(["ssh", REMOTE_HOST, "mkdir", "-p", remote_story_dir], dry_run=args.dry_run)
    _run(
        ["rsync", "-az", f"{story_dir}/", f"{REMOTE_HOST}:{remote_story_dir}/"],
        dry_run=args.dry_run,
    )
    _run(
        ["ssh", REMOTE_HOST, "sh", "-s", "--", remote_base, story_url, label],
        dry_run=args.dry_run,
        input_text=REMOTE_INDEX_SCRIPT,
    )

    print(f"Story URL: {story_url}")
    print(f"Index URL: {public_base}")
    if not args.no_open:
        _open_url(public_base, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
