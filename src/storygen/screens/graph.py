"""GraphScreen: navigate the full story graph for the current save.

Selecting a visited node sets the save's `current_node_id` (via the supplied
callback) and pops back to the play screen. Unexplored choices appear as
non-navigable leaves so the user can see where the story can still branch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from storygen.llm.models import NodeId, StoryNode
from storygen.screens._confirm_modal import ConfirmModal
from storygen.screens.replay import ReplayScreen
from storygen.storage.save import GameSave, prune_subtree
from storygen.storage.tree import path_from_root

# Maximum length (in characters) of the narration excerpt rendered for each
# tree node. Anything longer is ellipsized so the tree stays scannable.
_LABEL_MAX_LEN = 60


def _excerpt(text: str, *, max_len: int = _LABEL_MAX_LEN) -> str:
    """Collapse whitespace, take the first sentence-ish chunk, and ellipsize."""
    flat = " ".join(text.split())
    if not flat:
        return "(no narration)"
    # Prefer the first sentence so the root blurb (which often contains
    # multiple sentences) shows a useful summary in one line.
    first_sentence = flat.split(". ", 1)[0]
    candidate = first_sentence if len(first_sentence) <= max_len else flat
    if len(candidate) <= max_len:
        return candidate
    return candidate[: max_len - 1].rstrip() + "…"


def _suffixes(node: StoryNode) -> str:
    """Render the trailing tag glyphs for a node (ending/major/image)."""
    tags: list[str] = []
    if node.is_ending:
        tags.append("★")
    if node.is_major and not node.is_ending:
        tags.append("◆")
    if node.image_status == "done":
        tags.append("[+]")
    if node.tts_audio_path:
        tags.append("♪")
    return " ".join(tags)


def _format_label(node: StoryNode, *, is_current: bool, is_on_path: bool = False) -> str:
    if is_current:
        marker = "→"
    elif is_on_path:
        marker = "▸"
    else:
        marker = "·"
    body = _excerpt(node.narration)
    suffix = _suffixes(node)
    return f"{marker} {body} {suffix}".rstrip()


class _StoryTree(Tree[dict[str, object]]):
    """Tree subclass that highlights the root-to-current path with accent color."""

    def __init__(
        self,
        path_ids: frozenset[str],
        label: str,
        data: dict[str, object],
        **kwargs: object,
    ) -> None:
        super().__init__(label, data=data, **kwargs)  # type: ignore[no-untyped-def]
        self._path_ids = path_ids

    def update_path(self, path_ids: frozenset[str]) -> None:
        self._path_ids = path_ids

    def render_label(
        self,
        node: TreeNode[dict[str, object]],
        base_style: Style,
        style: Style,
    ) -> Text:
        data = node.data or {}
        nid = data.get("node_id")
        if isinstance(nid, str) and nid in self._path_ids:
            cyan = Style(color="cyan")
            return super().render_label(node, base_style + cyan, style + cyan)
        return super().render_label(node, base_style, style)


class GraphScreen(Screen[None]):
    """Modal screen that renders the story tree and lets the user jump to a node."""

    DEFAULT_CSS = """
    GraphScreen #graph-body {
        padding: 1 2;
    }
    GraphScreen #graph-legend {
        height: auto;
        padding: 0 1 1 1;
        color: $text-muted;
    }
    GraphScreen Tree {
        height: 1fr;
    }
    """

    _LEGEND = (
        "[b]Legend[/b]   "
        "[$accent]→[/] current   "
        "[$accent]▸[/] path   "
        "[$text-muted]·[/] beat   "
        "[$text-muted]○[/] unexplored choice   "
        "★ ending   "
        "◆ major beat   "
        "[+] illustrated   "
        "♪ audio"
    )

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("r", "replay", "Replay"),
        ("p", "prune", "Prune"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(
        self,
        save: GameSave,
        on_node_selected: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._save = save
        self._on_node_selected = on_node_selected
        # Map from node_id -> TreeNode so we can scroll/highlight the current
        # node after the tree is built.
        self._node_widgets: dict[NodeId, TreeNode[dict[str, object]]] = {}
        # Compute the root-to-current path for highlighting.
        self._path_ids: frozenset[str] = frozenset(
            n.id for n in path_from_root(save, save.current_node_id)
        )
        root = save.nodes[save.root_node_id]
        root_data: dict[str, object] = {"node_id": root.id}
        self._tree: _StoryTree = _StoryTree(
            self._path_ids,
            _format_label(
                root,
                is_current=save.current_node_id == root.id,
                is_on_path=root.id in self._path_ids,
            ),
            data=root_data,
            id="graph-tree",
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="graph-body"):
            yield Static(self._LEGEND, id="graph-legend", markup=True)
            yield self._tree
        yield Footer()

    def on_mount(self) -> None:
        self._apply_header()
        self._build_tree()
        self._tree.root.expand_all()
        # Hand keyboard focus to the Tree so arrow keys / Enter work without
        # the user having to click first.
        self._tree.focus()
        # Defer cursor positioning until after the first render so that
        # TreeNode._line values have been computed by _build().
        self.call_after_refresh(self._focus_current_node)

    def _apply_header(self) -> None:
        """Mirror PlayScreen's header convention with a graph-specific subtitle."""
        self.title = self._save.theme.title
        cost = f"${self._save.total_image_cost_usd:.4f}"
        n_nodes = len(self._save.nodes)
        self.sub_title = f"{cost}  ·  Graph ({n_nodes} nodes)"

    def _build_tree(self) -> None:
        """Populate the tree from the save's root node, recursively."""
        root_node = self._save.nodes[self._save.root_node_id]
        # The tree's root TreeNode was created in __init__; record it and
        # populate its children.
        root_data: dict[str, object] = {"node_id": root_node.id}
        self._tree.root.data = root_data
        self._node_widgets[root_node.id] = self._tree.root
        self._tree.root.expand()
        self._add_children_for(self._tree.root, root_node)

    def _add_children_for(
        self,
        parent_widget: TreeNode[dict[str, object]],
        parent_node: StoryNode,
    ) -> None:
        for choice in parent_node.choices:
            if choice.child_node_id is None:
                # Unexplored branch — render as a non-navigable leaf so the
                # user sees the choice text but can't jump to a non-existent
                # node.
                unexplored_data: dict[str, object] = {"unexplored": True}
                parent_widget.add_leaf(
                    f"○ {choice.text} (unexplored)",
                    data=unexplored_data,
                )
                continue
            child_node = self._save.nodes.get(choice.child_node_id)
            if child_node is None:
                # Defensive: the cache link points at a missing node. Surface
                # it so it's not silently dropped.
                missing_data: dict[str, object] = {"unexplored": True}
                parent_widget.add_leaf(
                    f"○ {choice.text} (missing node)",
                    data=missing_data,
                )
                continue
            label = _format_label(
                child_node,
                is_current=self._save.current_node_id == child_node.id,
                is_on_path=child_node.id in self._path_ids,
            )
            child_data: dict[str, object] = {"node_id": child_node.id}
            child_widget = parent_widget.add(
                label,
                data=child_data,
                expand=True,
            )
            self._node_widgets[child_node.id] = child_widget
            self._add_children_for(child_widget, child_node)

    def _focus_current_node(self) -> None:
        """Scroll the Tree to the current node and place the cursor on it.

        Uses ``move_cursor`` rather than ``select_node`` so we don't fire a
        spurious ``NodeSelected`` event during mount (which would jump the
        user back to the play screen as soon as the graph appears).
        """
        widget = self._node_widgets.get(self._save.current_node_id)
        if widget is None:
            return
        self._tree.move_cursor(widget)
        self._tree.scroll_to_node(widget, animate=False)

    def on_tree_node_selected(self, event: Tree.NodeSelected[dict[str, object]]) -> None:
        data = event.node.data or {}
        if data.get("unexplored"):
            self.notify(
                "This branch hasn't been generated yet — "
                "pick it from the play screen to generate the beat.",
                severity="information",
                timeout=4,
            )
            return
        node_id = data.get("node_id")
        if not isinstance(node_id, str):
            return
        self._jump_to(node_id)

    def _jump_to(self, node_id: NodeId) -> None:
        """Hand `node_id` to the caller's selection callback.

        Centralizes the "jump-to-node" path so both direct tree selection and
        the ReplayScreen's `j` (jump-to-live) flow use the exact same wiring.
        """
        self._on_node_selected(node_id)

    def action_replay(self) -> None:
        """Push the ReplayScreen for the currently highlighted tree node.

        On `j` from inside ReplayScreen, the callback fires `_jump_to` so the
        user lands back on PlayScreen at the chosen beat (Graph + Replay both
        pop, leaving PlayScreen on top).
        """
        cursor = self._tree.cursor_node
        if cursor is None or cursor.data is None:
            self.notify(
                "Select a node to replay first.",
                severity="warning",
                timeout=3,
            )
            return
        data = cursor.data
        if data.get("unexplored"):
            self.notify(
                "This branch hasn't been generated yet — nothing to replay.",
                severity="warning",
                timeout=3,
            )
            return
        node_id = data.get("node_id")
        if not isinstance(node_id, str):
            return
        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ReplayScreen(
                self._save,
                node_id,
                on_jump_to_live=self._jump_to,
            )
        )

    def action_prune(self) -> None:
        """Prune the subtree rooted at the currently highlighted node."""
        cursor = self._tree.cursor_node
        if cursor is None or cursor.data is None:
            self.notify("Select a node to prune.", severity="warning", timeout=3)
            return
        data = cursor.data
        if data.get("unexplored"):
            self.notify(
                "This branch hasn't been generated yet — nothing to prune.",
                severity="warning",
                timeout=3,
            )
            return
        node_id = data.get("node_id")
        if not isinstance(node_id, str):
            return
        if node_id == self._save.root_node_id:
            self.notify("Cannot prune the root node.", severity="warning", timeout=3)
            return
        from storygen.storage.tree import descendants as _desc

        doomed = _desc(self._save, node_id)
        n_images = sum(1 for nid in doomed if self._save.nodes[nid].image_status == "done")
        parts = [f"{len(doomed)} node{'s' if len(doomed) != 1 else ''}"]
        if n_images:
            parts.append(f"{n_images} image{'s' if n_images != 1 else ''}")
        msg = f"Prune this branch? ({', '.join(parts)} will be deleted)"
        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ConfirmModal(msg, confirm_label="Prune"),
            lambda result: self._on_prune_confirm(result, node_id=node_id),
        )

    def _on_prune_confirm(self, result: bool | None, *, node_id: str) -> None:
        """Handle the prune confirmation dialog response."""
        if not result:
            return
        try:
            prune_subtree(self._save, node_id=node_id)
        except Exception as exc:
            self.notify(f"Prune failed: {exc}", severity="error", timeout=5)
            return
        self._apply_header()
        # Recompute path — prune may have moved current_node_id.
        self._path_ids = frozenset(
            n.id for n in path_from_root(self._save, self._save.current_node_id)
        )
        self._tree.update_path(self._path_ids)
        # Rebuild the tree from scratch.
        self._tree.clear()
        self._node_widgets.clear()
        self._build_tree()
        self._tree.root.expand_all()
        self._tree.focus()
        self.call_after_refresh(self._focus_current_node)
        self.notify("Branch pruned.", severity="information", timeout=3)
