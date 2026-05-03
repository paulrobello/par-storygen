# Graph Prune Subtree

**Date:** 2026-05-03
**Status:** Approved

## Summary

Add the ability to delete a subtree from the story graph in GraphScreen. Selecting a node and pressing `p` removes it and all descendants, cleans up associated image/audio files, and reverts the parent's choice to "unexplored."

## Behavior

1. User navigates to a node in GraphScreen and presses `p`.
2. Root node is guarded — shows a warning, does nothing.
3. A `Confirm` dialog appears: "Prune this branch? (N nodes, M images will be deleted)"
4. On confirm:
   - Collect all descendant node IDs via BFS from the selected node.
   - Remove all collected nodes + the selected node from `save.nodes`.
   - Clear the parent's `StoredChoice.child_node_id` for the link pointing to the pruned node. The parent's choice reverts to unexplored.
   - If `save.current_node_id` was in the pruned subtree, set it to the parent of the pruned node.
   - Remove any entries in `save.endings_reached` that reference pruned nodes.
   - Delete image files (`images/nodes/<node_id>.png`) and TTS audio files from disk for each pruned node.
   - Persist via `save_game(save)`.
   - Rebuild the GraphScreen tree widget.

## Keybinding

`p` — "Prune" in `GraphScreen.BINDINGS`.

## Constraints

- Cannot prune root.
- Pruning the current position is allowed — current_node_id moves to the parent.
- Pruning a node with many descendants deletes all of them. The confirmation dialog shows the count.

## Files

| File | Change |
|------|--------|
| `src/storygen/storage/tree.py` | Add `descendants(save, node_id) -> list[NodeId]` — BFS collector |
| `src/storygen/storage/save.py` | Add `prune_subtree(save, node_id) -> int` — mutates save, cleans disk, returns count of deleted nodes |
| `src/storygen/screens/graph.py` | Add `action_prune()` with Confirm dialog, tree rebuild after prune |
