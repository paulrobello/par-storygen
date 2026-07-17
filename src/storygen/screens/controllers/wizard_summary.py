"""Pure confirm-summary builder for :class:`WizardScreen` (ARC-012/QA-006).

The confirm step renders a human-readable summary of the wizard choices.
The string construction — including the branched tone formatting and the
cast-list join — has no widget dependency, so it is extracted here and is
unit-testable without a Textual Screen. The reader-level label lookup stays
on the screen because it shares the ``READER_LEVEL_OPTIONS`` constant with
:class:`SettingsScreen`.
"""

from __future__ import annotations

from collections.abc import Sequence

from storygen.core.models import Character, Theme, Tone


def _format_tone(tone: Tone | None) -> str:
    if tone is None:
        return ""
    if tone.preset == "custom":
        return f"custom: {tone.custom_descriptor}"
    if tone.custom_descriptor:
        return f"{tone.preset} ({tone.custom_descriptor})"
    return tone.preset


def build_confirm_summary(
    *,
    theme: Theme | None,
    tone: Tone | None,
    style: str,
    art_style: str,
    target_major_beats: int,
    reader_label: str,
    characters: Sequence[Character],
) -> str:
    """Render the wizard confirm-step summary text from the current choices."""
    cast_str = ", ".join(c.name for c in characters) if characters else "(no characters yet)"
    return (
        f"Theme: {theme.title if theme else ''}\n"
        f"Tone: {_format_tone(tone)}\n"
        f"Style: {style}\n"
        f"Art: {art_style}\n"
        f"Length: {target_major_beats} beats\n"
        f"Reader level: {reader_label}\n"
        f"Cast: {cast_str}"
    )
