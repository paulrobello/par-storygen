# Graph Prune Subtree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add subtree pruning to GraphScreen so users can delete a node and all its descendants, reverting the parent choice to unexplored.

**Architecture:** Add a `descendants()` BFS helper to `tree.py`, a `prune_subtree()` mutation+disk-cleanup function to `save.py`, and wire it into `graph.py` with a `p` keybinding and `Confirm` dialog. Pure-function storage layer, thin UI glue.

**Tech Stack:** Python 3.13, Textual, Pydantic, pytest

---

### Task 1: Add `descendants()` helper to `tree.py`

**Files:**
- Modify: `src/storygen/storage/tree.py`
- Test: `tests/unit/test_tree.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_tree.py`, importing `descendants` from `storygen.storage.tree`:

```python
def test_descendants_returns_bfs_order() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
            "b": _node("b", "root", chose="c2"),
            "a1": _node("a1", "a", chose="c1"),
            "a2": _node("a2", "a", chose="c2"),
            "a1x": _node("a1x", "a1", chose="c1"),
        }
    )
    result = descendants(save, "a")
    assert set(result) == {"a", "a1", "a2", "a1x"}
    # a appears before its children
    assert result.index("a") < result.index("a1")


def test_descendants_leaf_returns_self_only() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
        }
    )
    assert descendants(save, "a") == ["a"]


def test_descendants_root_returns_everything() -> None:
    save = _empty_save(
        {
            "root": _node("root", None),
            "a": _node("a", "root", chose="c1"),
            "b": _node("b", "root", chose="c2"),
        }
    )
    assert set(descendants(save, "root")) == {"root", "a", "b"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tree.py::test_descendants_returns_bfs_order -v`
Expected: FAIL — `ImportError: cannot import name 'descendants'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/storygen/storage/tree.py`, after the existing `children_index` function:

```python
def descendants(save: GameSave, node_id: NodeId) -> list[NodeId]:
    """Return *node_id* and all its descendants in BFS order.

    Uses :func:`children_index` for O(n) traversal.
    """
    idx = children_index(save)
    result: list[NodeId] = []
    queue: list[NodeId] = [node_id]
    while queue:
        current = queue.pop(0)
        result.append(current)
        queue.extend(idx.get(current, []))
    return result
```

Also add `descendants` to the module's imports are already covered. No import changes needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tree.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/storygen/storage/tree.py tests/unit/test_tree.py
git commit -m "feat: add descendants() BFS helper to tree.py"
```

---

### Task 2: Add `prune_subtree()` to `save.py`

**Files:**
- Modify: `src/storygen/storage/save.py`
- Modify: `src/storygen/storage/paths.py`
- Test: `tests/unit/test_save.py`

- [ ] **Step 1: Add `node_audio_glob` helper to `paths.py`**

We need a way to find TTS audio files for a node. The audio path pattern is `audio/<node_id>-<provider>-<voice_hash>.<ext>`. Add a glob helper since the exact provider/voice/ext are not stored on the node (only the relative path is, and there could theoretically be multiple):

Add to `src/storygen/storage/paths.py` at the end:

```python
def node_audio_glob(game_id: str, node_id: str) -> list[Path]:
    """Return all TTS audio files matching a node id on disk."""
    audio_dir = game_dir(game_id) / "audio"
    if not audio_dir.is_dir():
        return []
    return sorted(audio_dir.glob(f"{node_id}-*.*"))
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/unit/test_save.py`. First add `descendants` and `prune_subtree` to the imports:

```python
from storygen.storage.save import GameSave, load_game, prune_subtree, save_game
```

Then add test helpers and tests:

```python
def _save_with_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GameSave:
    """Build a save with root → a → a1, root → b, save it to disk."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    nodes = {
        "root": StoryNode(
            id="root", parent_id=None, chosen_choice_id=None, chosen_at=None,
            narration="root beat",
            choices=[
                StoredChoice(id="c1", text="go a", child_node_id="a"),
                StoredChoice(id="c2", text="go b", child_node_id="b"),
            ],
            is_major=True, is_ending=False, image_prompt=None, image_path=None,
            image_status="not_planned", illustration_reasoning=None,
            featured_character_ids=[], summary_to_here=None,
            created_at=datetime.now(UTC),
        ),
        "a": StoryNode(
            id="a", parent_id="root", chosen_choice_id="c1",
            chosen_at=datetime.now(UTC), narration="beat a",
            choices=[StoredChoice(id="c3", text="go a1", child_node_id="a1")],
            is_major=False, is_ending=False, image_prompt=None,
            image_path="images/nodes/a.png", image_status="done",
            illustration_reasoning=None, featured_character_ids=[],
            summary_to_here=None, created_at=datetime.now(UTC),
        ),
        "a1": StoryNode(
            id="a1", parent_id="a", chosen_choice_id="c3",
            chosen_at=datetime.now(UTC), narration="beat a1",
            choices=[], is_major=False, is_ending=True,
            image_prompt=None, image_path=None, image_status="not_planned",
            illustration_reasoning=None, featured_character_ids=[],
            summary_to_here=None, tts_audio_path="audio/a1-legacy-abcd1234.mp3",
            created_at=datetime.now(UTC),
        ),
        "b": StoryNode(
            id="b", parent_id="root", chosen_choice_id="c2",
            chosen_at=datetime.now(UTC), narration="beat b",
            choices=[], is_major=False, is_ending=False, image_prompt=None,
            image_path=None, image_status="not_planned", illustration_reasoning=None,
            featured_character_ids=[], summary_to_here=None,
            created_at=datetime.now(UTC),
        ),
    }
    save = GameSave(
        version=1, id=uuid4(),
        theme=Theme(title="T", setting="S", premise="P", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[], nodes=nodes, root_node_id="root", current_node_id="a1",
        endings_reached=["a1"],
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    save_game(save)
    return save


def test_prune_subtree_removes_descendants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    count = prune_subtree(save)
    assert count == 2  # a + a1
    assert set(save.nodes.keys()) == {"root", "b"}
    # parent choice reverted to unexplored
    assert save.nodes["root"].choices[0].child_node_id is None
    assert save.nodes["root"].choices[1].child_node_id == "b"


def test_prune_subtree_moves_current_to_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    assert save.current_node_id == "a1"
    prune_subtree(save)
    assert save.current_node_id == "root"


def test_prune_subtree_cleans_endings_reached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    assert "a1" in save.endings_reached
    prune_subtree(save)
    assert save.endings_reached == []


def test_prune_subtree_deletes_image_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    # Create fake image file for node "a"
    from storygen.storage import paths
    img = paths.node_image_path(str(save.id), "a")
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"fake-png")
    assert img.exists()
    prune_subtree(save)
    assert not img.exists()


def test_prune_subtree_deletes_audio_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    # Create fake audio file for node "a1"
    from storygen.storage import paths
    paths.ensure_game_dirs(str(save.id))
    audio = paths.game_dir(str(save.id)) / "audio" / "a1-legacy-abcd1234.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"fake-audio")
    assert audio.exists()
    prune_subtree(save)
    assert not audio.exists()


def test_prune_subtree_root_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    try:
        prune_subtree(save, node_id="root")
    except ValueError:
        return
    raise AssertionError("expected ValueError for root prune")
```

Note: the `prune_subtree` function will take an optional `node_id` parameter defaulting to `save.current_node_id`. But in these tests we'll use the cursor-position approach — we'll set `current_node_id` to the target before calling, OR pass `node_id` explicitly. Looking at the test above, the first tests just call `prune_subtree(save)` without node_id — so it will need to operate on a node the test sets up. Let me revise: the function signature will be `prune_subtree(save, *, node_id: str | None = None)` where `None` means "use the current cursor node". But for the tests, we'll always pass `node_id` explicitly except where we test the default. Actually, for simplicity, let's make `node_id` required — the GraphScreen will pass it explicitly.

Revised tests — all calls pass `node_id="a"`:

```python
def test_prune_subtree_removes_descendants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    count = prune_subtree(save, node_id="a")
    assert count == 2  # a + a1
    assert set(save.nodes.keys()) == {"root", "b"}
    assert save.nodes["root"].choices[0].child_node_id is None
    assert save.nodes["root"].choices[1].child_node_id == "b"


def test_prune_subtree_moves_current_to_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    assert save.current_node_id == "a1"
    prune_subtree(save, node_id="a")
    assert save.current_node_id == "root"


def test_prune_subtree_cleans_endings_reached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    assert "a1" in save.endings_reached
    prune_subtree(save, node_id="a")
    assert save.endings_reached == []


def test_prune_subtree_deletes_image_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    from storygen.storage import paths
    img = paths.node_image_path(str(save.id), "a")
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"fake-png")
    assert img.exists()
    prune_subtree(save, node_id="a")
    assert not img.exists()


def test_prune_subtree_deletes_audio_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    from storygen.storage import paths
    paths.ensure_game_dirs(str(save.id))
    audio = paths.game_dir(str(save.id)) / "audio" / "a1-legacy-abcd1234.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"fake-audio")
    assert audio.exists()
    prune_subtree(save, node_id="a")
    assert not audio.exists()


def test_prune_subtree_root_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save = _save_with_tree(tmp_path, monkeypatch)
    try:
        prune_subtree(save, node_id="root")
    except ValueError:
        return
    raise AssertionError("expected ValueError for root prune")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_save.py::test_prune_subtree_removes_descendants -v`
Expected: FAIL — `ImportError: cannot import name 'prune_subtree'`

- [ ] **Step 4: Write minimal implementation**

Add to `src/storygen/storage/save.py`. First add imports at top:

```python
from storygen.storage.tree import descendants
```

Add `prune_subtree` to `__all__` list.

Add function after `delete_game`:

```python
def prune_subtree(save: GameSave, *, node_id: NodeId) -> int:
    """Remove *node_id* and all its descendants from the save and disk.

    Mutates ``save`` in place: removes nodes from ``save.nodes``, clears
    the parent's ``child_node_id`` link, relocates ``current_node_id`` if
    it was inside the pruned subtree, removes pruned nodes from
    ``endings_reached``, deletes associated image and audio files, and
    persists the result.

    Args:
        save: The game save to mutate.
        node_id: The root of the subtree to prune. Must not be the root node.

    Returns:
        The number of nodes removed (including ``node_id`` itself).

    Raises:
        ValueError: If ``node_id`` is the save's root node.
    """
    if node_id == save.root_node_id:
        raise ValueError("Cannot prune the root node")

    doomed = descendants(save, node_id)
    doomed_set = set(doomed)

    # Clear parent's child_node_id link so the choice reverts to unexplored.
    target_node = save.nodes[node_id]
    parent = save.nodes[target_node.parent_id]  # type: ignore[arg-type]
    for choice in parent.choices:
        if choice.child_node_id == node_id:
            choice.child_node_id = None
            break

    # Relocate current_node_id if it was in the pruned subtree.
    if save.current_node_id in doomed_set:
        save.current_node_id = target_node.parent_id  # type: ignore[assignment]

    # Clean endings_reached.
    save.endings_reached = [e for e in save.endings_reached if e not in doomed_set]

    # Delete image and audio files from disk.
    game_id = str(save.id)
    for nid in doomed:
        node = save.nodes[nid]
        # Scene illustration.
        if node.image_path:
            from storygen.storage import paths as _paths
            img_abs = _paths.safe_join(_paths.game_dir(game_id), node.image_path)
            if img_abs.exists():
                img_abs.unlink()
        # TTS audio — use relative path if present, else glob.
        if node.tts_audio_path:
            from storygen.storage import paths as _paths
            audio_abs = _paths.safe_join(_paths.game_dir(game_id), node.tts_audio_path)
            if audio_abs.exists():
                audio_abs.unlink()
        else:
            # No stored path — clean up any stale audio files by glob.
            from storygen.storage import paths as _paths
            for p in _paths.node_audio_glob(game_id, nid):
                p.unlink(missing_ok=True)

    # Remove nodes from the dict.
    for nid in doomed:
        del save.nodes[nid]

    save_game(save)
    return len(doomed)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_save.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/storygen/storage/save.py src/storygen/storage/paths.py tests/unit/test_save.py
git commit -m "feat: add prune_subtree() to save.py with disk cleanup"
```

---

### Task 3: Wire prune action into `GraphScreen`

**Files:**
- Modify: `src/storygen/screens/graph.py`
- Test: `tests/unit/test_graph_screen.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_graph_screen.py`. First add `prune_subtree` and `Confirm` imports:

```python
from unittest.mock import MagicMock
from storygen.storage.save import prune_subtree
```

Add tests:

```python
@pytest.mark.asyncio
async def test_prune_binding_present() -> None:
    """`p` is registered in GraphScreen BINDINGS."""
    keys = [b[0] for b in GraphScreen.BINDINGS]
    assert "p" in keys


@pytest.mark.asyncio
async def test_action_prune_root_shows_warning() -> None:
    """Pruning root shows a warning and does nothing."""
    save = _root_save()
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        # Cursor is on root by default.
        screen.action_prune()
        await pilot.pause()
        # Still on graph screen, no confirm pushed.
        assert isinstance(app.screen, GraphScreen)
        # Root still exists.
        assert "root" in save.nodes


@pytest.mark.asyncio
async def test_action_prune_unexplored_shows_warning() -> None:
    """Pruning an unexplored leaf shows a warning."""
    save = _root_save()
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        unexplored = next(n for n in _walk(tree.root) if (n.data or {}).get("unexplored"))
        tree.move_cursor(unexplored)
        await pilot.pause()
        screen.action_prune()
        await pilot.pause()
        assert isinstance(app.screen, GraphScreen)


@pytest.mark.asyncio
async def test_action_prune_with_visited_node_pushes_confirm() -> None:
    """Pruning a visited node pushes a Confirm dialog."""
    save = _root_save()
    save.nodes["root"].choices[0].child_node_id = "child"
    save.nodes["child"] = _make_child(
        "child", parent_id="root", chosen_choice_id="c1",
        narration="A second beat.",
    )
    app = _Harness(save)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GraphScreen)
        tree = cast(Tree[dict[str, object]], screen.query_one(Tree))
        target = next(n for n in _walk(tree.root) if (n.data or {}).get("node_id") == "child")
        tree.move_cursor(target)
        await pilot.pause()
        screen.action_prune()
        await pilot.pause()
        # Confirm dialog should be pushed
        from textual.widgets import Confirm as ConfirmWidget
        assert any(
            isinstance(s, ConfirmWidget) for s in app.screen.walk_children()
        ) or type(app.screen).__name__ == "Confirm"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_graph_screen.py::test_prune_binding_present -v`
Expected: FAIL — `p` not in BINDINGS

- [ ] **Step 3: Write minimal implementation**

Modify `src/storygen/screens/graph.py`:

1. Add import at top:
```python
from textual.widgets import Confirm
```

2. Add `prune_subtree` import:
```python
from storygen.storage.save import prune_subtree
```

3. Add `p` binding to `BINDINGS`:
```python
BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
    ("r", "replay", "Replay"),
    ("p", "prune", "Prune"),
    ("escape", "app.pop_screen", "Back"),
]
```

4. Add `action_prune` method to `GraphScreen`:

```python
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
    # Count descendants for the confirmation message.
    from storygen.storage.tree import descendants as _desc
    doomed = _desc(self._save, node_id)
    n_images = sum(
        1 for nid in doomed if self._save.nodes[nid].image_status == "done"
    )
    parts = [f"{len(doomed)} node{'s' if len(doomed) != 1 else ''}"]
    if n_images:
        parts.append(f"{n_images} image{'s' if n_images != 1 else ''}")
    msg = f"Prune this branch? ({', '.join(parts)} will be deleted)"
    self.app.push_screen(
        Confirm(msg, id="prune-confirm"),  # pyright: ignore[reportUnknownMemberType]
        self._on_prune_confirm,
    )

def _on_prune_confirm(self, result: bool) -> None:
    """Handle the prune confirmation dialog response."""
    if not result:
        return
    cursor = self._tree.cursor_node
    if cursor is None or cursor.data is None:
        return
    node_id = cursor.data.get("node_id")
    if not isinstance(node_id, str):
        return
    try:
        prune_subtree(self._save, node_id=node_id)
    except Exception as exc:
        self.notify(f"Prune failed: {exc}", severity="error", timeout=5)
        return
    self._apply_header()
    # Rebuild the tree from scratch.
    self._tree.clear()
    self._node_widgets.clear()
    self._build_tree()
    self._tree.root.expand_all()
    self._tree.focus()
    self.call_after_refresh(self._focus_current_node)
    self.notify("Branch pruned.", severity="information", timeout=3)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_graph_screen.py -v`
Expected: all PASS

- [ ] **Step 5: Run full check**

Run: `make checkall`
Expected: all PASS (fmt, lint, typecheck, test)

- [ ] **Step 6: Commit**

```bash
git add src/storygen/screens/graph.py tests/unit/test_graph_screen.py
git commit -m "feat: wire prune action into GraphScreen with confirm dialog"
```

---

### Task 4: Integration smoke test and final verification

**Files:** none new — manual + checkall

- [ ] **Step 1: Run full check**

Run: `make checkall`
Expected: all PASS

- [ ] **Step 2: Verify typecheck passes**

Run: `uv run pyright src/storygen/storage/tree.py src/storygen/storage/save.py src/storygen/screens/graph.py`
Expected: 0 errors

- [ ] **Step 3: Commit any remaining fixes**
