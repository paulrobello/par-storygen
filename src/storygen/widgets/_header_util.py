"""Shared header-subtitle formatting helpers for TUI screens."""

from __future__ import annotations

from storygen.storage.save import GameSave


def format_cost_subtitle(save: GameSave) -> str:
    """Return the standard cost + token sub-title string for a save.

    Format: ``"$X.XXXX  ·  N↑/N↓ tok"``

    Used by PlayScreen and PortraitsScreen to keep their ``_apply_header``
    sub_title values consistent without duplication.
    """
    cost = f"${save.total_image_cost_usd:.4f}"
    in_tok = save.text_total_input_tokens
    out_tok = save.text_total_output_tokens
    return f"{cost}  ·  {in_tok}↑/{out_tok}↓ tok"
