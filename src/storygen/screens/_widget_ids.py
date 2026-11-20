"""Embed arbitrary strings (e.g. LLM-chosen character ids) in Textual widget ids.

Textual ids may only contain letters, numbers, underscores and hyphens, but
character ids come from the LLM and can be anything (``"Jane Doe"``).
Letters, digits and hyphens pass through unchanged; every other character,
including ``_`` itself, becomes ``_`` plus six hex digits of its code point.
The encoding is reversible and never contains ``__``, so callers can still
use ``__`` as a separator.
"""

from __future__ import annotations

import re

_SAFE_CHAR = re.compile(r"[A-Za-z0-9-]")
_ESCAPE = re.compile(r"_([0-9a-f]{6})")


def encode_id_part(value: str) -> str:
    """Encode *value* so it can be embedded after a prefix in a widget id."""
    return "".join(ch if _SAFE_CHAR.fullmatch(ch) else f"_{ord(ch):06x}" for ch in value)


def decode_id_part(part: str) -> str:
    """Reverse :func:`encode_id_part`."""
    return _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), part)
