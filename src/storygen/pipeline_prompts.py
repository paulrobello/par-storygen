"""Pure prompt-construction helpers extracted from ``pipeline.py`` (ARC-011).

These functions take a ``GameSave`` (+ ids) and return a string. They perform
no I/O, mutate no state, and touch no module-level singletons — so they are
safe to unit-test in isolation (see ``tests/unit/test_pipeline_helpers.py``)
and to reason about independently of the ``BeatPipeline`` coordinator that
calls them.

Extracted from ``pipeline.py`` to chip at its 1042-LOC monolith. The split is
deliberately narrow: ``BeatPipeline.advance`` and the prefetch lifecycle stay
in ``pipeline.py`` because their control flow is intrinsic to the pipeline
coordinator (the audit explicitly endorses this boundary).
"""

from __future__ import annotations

from storygen.core.models import StoryNode
from storygen.core.models import one_sentence as _one_sentence
from storygen.storage.save import GameSave
from storygen.storage.tree import path_from_root, segment_since_last_summary

__all__ = [
    "build_beat_prompt",
    "pacing_hint_for_depth",
    "resolve_chosen_text",
]


def build_beat_prompt(save: GameSave, from_node_id: str, choice_text: str) -> str:
    """Compose the user-side prompt sent to the beat agent.

    Includes:
      - Cast roster (names + brief descriptions) so the model doesn't drift
        on character traits or invent new ones.
      - The last major beat's accumulated summary (if any).
      - Full narration of all beats since that major beat, in order.
      - The choice the player just made.
    """
    sections: list[str] = []

    # Cast - one-liner for quick ID plus full backstory so the beat agent
    # can naturally reference character history and relationships.
    if save.characters:
        cast_lines: list[str] = []
        for c in save.characters:
            line = (
                f"- [{c.id}] {c.name}: {_one_sentence(c.personality)}"
                + (f" {_one_sentence(c.backstory_summary)}" if c.backstory_summary else "")
                + f" ({_one_sentence(c.physical_description)})"
            )
            if c.backstory:
                line += f"\n  Backstory: {c.backstory}"
            cast_lines.append(line)
        sections.append("CAST:\n" + "\n".join(cast_lines))

    if save.relationships:
        char_names = {c.id: c.name for c in save.characters}
        name_to_id = {c.name: c.id for c in save.characters}

        def _resolve(key: str) -> str:
            if key in char_names:
                return char_names[key]
            return key  # already a name or unknown

        known = set(char_names) | set(name_to_id)
        rel_lines = [
            f"- {_resolve(r.char_a_id)} ↔ {_resolve(r.char_b_id)}:"
            f" {r.type.value} (strength {r.strength}) — {r.context}"
            for r in save.relationships
            if r.char_a_id in known and r.char_b_id in known
        ]
        if rel_lines:
            sections.append("RELATIONSHIPS:\n" + "\n".join(rel_lines))

    prev_summary, segment = segment_since_last_summary(save, from_node_id)
    if prev_summary:
        sections.append(f"STORY-SO-FAR SUMMARY:\n{prev_summary}")

    if segment:
        beat_lines: list[str] = []
        for node in segment:
            chosen = resolve_chosen_text(save, node)
            line = f"- {node.narration}"
            if chosen:
                line += f"\n  -> player chose: {chosen}"
            beat_lines.append(line)
        sections.append("BEATS SINCE LAST SUMMARY:\n" + "\n".join(beat_lines))

    sections.append(f"PLAYER JUST CHOSE: {choice_text}")

    # Pacing is measured in MAJOR beats so far (the unit target_major_beats
    # is denominated in), not total beats. Count across the full ancestor path.
    full_chain = path_from_root(save, from_node_id)
    major_so_far = sum(1 for n in full_chain if n.is_major)
    pacing_hint = pacing_hint_for_depth(major_so_far, save.target_major_beats, save.pacing)
    if pacing_hint:
        sections.append(pacing_hint.strip())
    return "\n\n".join(sections)


def pacing_hint_for_depth(depth: int, target: int, pacing: str = "moderate") -> str:
    """Encourage the model to wind down rather than meander indefinitely.

    Uses ratios of the per-save ``target`` so very short stories don't get a
    "tighten" prod at beat 5 of 5 and very long stories don't get told to
    "resolve now" at beat 11 of 30.
    """
    multiplier = {"slow": 1.4, "fast": 0.7}.get(pacing, 1.0)
    silent_threshold = max(int(target * 0.3 * multiplier), 1)
    tension_threshold = max(int(target * 0.6 * multiplier), 1)
    climax_threshold = max(int(target * 0.9 * multiplier), 1)
    if depth <= silent_threshold:
        return ""
    if depth <= tension_threshold:
        return f" This will be beat #{depth + 1}; keep tension rising."
    if depth <= climax_threshold:
        return (
            f" This will be beat #{depth + 1}; start tightening toward a"
            " climax — set up the resolution rather than introducing new"
            " unrelated mysteries."
        )
    return (
        f" This will be beat #{depth + 1}; the story has run long. Strongly"
        " consider resolving the central conflict in this beat or the next."
        " Set is_ending=true once the resolution lands."
    )


def resolve_chosen_text(save: GameSave, node: StoryNode) -> str:
    """Look up the player-facing text of the choice that led to ``node``."""
    if node.chosen_choice_id is None or node.parent_id is None:
        return ""
    parent = save.nodes.get(node.parent_id)
    if parent is None:
        return ""
    for c in parent.choices:
        if c.id == node.chosen_choice_id:
            return c.text
    return ""
