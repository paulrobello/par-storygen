"""Pure-function helpers for walking the story tree in a GameSave."""

from __future__ import annotations

from collections.abc import Iterable

from storygen.llm.models import NodeId, StoryNode
from storygen.storage.save import GameSave


def path_from_root(save: GameSave, node_id: NodeId) -> list[StoryNode]:
    """Return nodes from root to `node_id` inclusive, in order."""
    chain: list[StoryNode] = []
    current: NodeId | None = node_id
    while current is not None:
        node = save.nodes[current]
        chain.append(node)
        current = node.parent_id
    chain.reverse()
    return chain


def ancestors(save: GameSave, node_id: NodeId) -> list[StoryNode]:
    """Return ancestors of `node_id` ordered closest-first (parent, grandparent, ...)."""
    result: list[StoryNode] = []
    current = save.nodes[node_id].parent_id
    while current is not None:
        node = save.nodes[current]
        result.append(node)
        current = node.parent_id
    return result


def children(save: GameSave, node_id: NodeId) -> Iterable[StoryNode]:
    """Return nodes whose `parent_id == node_id`. Order is not guaranteed."""
    return [n for n in save.nodes.values() if n.parent_id == node_id]


def children_index(save: GameSave) -> dict[NodeId, list[NodeId]]:
    """Pre-build a parent → children map for the entire tree.

    Prefer this over calling :func:`children` repeatedly when you need
    to walk the full tree (e.g. rendering the graph), as it is O(n) rather
    than O(n²) for n nodes.

    Returns:
        A dict mapping each node id to a list of its direct children's ids.
        Nodes with no children are absent from the dict (not mapped to ``[]``).
    """
    index: dict[NodeId, list[NodeId]] = {}
    for node in save.nodes.values():
        if node.parent_id is not None:
            index.setdefault(node.parent_id, []).append(node.id)
    return index


def latest_summary(save: GameSave, node_id: NodeId) -> str | None:
    """Walk ancestors newest-first and return the first `summary_to_here`.

    Includes `node_id` itself as the newest candidate.
    """
    chain = [save.nodes[node_id], *ancestors(save, node_id)]
    for node in chain:
        if node.summary_to_here:
            return node.summary_to_here
    return None


def segment_since_last_summary(
    save: GameSave, node_id: NodeId
) -> tuple[str | None, list[StoryNode]]:
    """Return the beats between the last summary anchor and *node_id*.

    Walks ancestors closest-first, collecting nodes until one with
    ``summary_to_here`` is found.  Returns:

    * ``prev_summary`` - the ``summary_to_here`` from that ancestor, or
      ``None`` when no prior summary exists (first major beat).
    * ``segment`` - all collected nodes in chronological (root-first) order,
      **including** *node_id* itself but **excluding** the ancestor that
      contributed ``prev_summary``.
    """
    node = save.nodes[node_id]
    if node.summary_to_here:
        return node.summary_to_here, []
    collected: list[StoryNode] = [node]
    for anc in ancestors(save, node_id):
        if anc.summary_to_here:
            collected.reverse()
            return anc.summary_to_here, collected
        collected.append(anc)
    collected.reverse()
    return None, collected
