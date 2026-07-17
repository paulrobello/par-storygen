// QA-003: regression coverage for the Zustand game store — the correctness
// core of the web client. Both WebSocket events (useWebSocket.ts) and REST
// calls (api.ts) dispatch through these actions, so a silent regression here
// breaks the entire play loop. Covers loadGame, advanceChoice (optimistic +
// success + error), setBeatCommitted (incl. the QA-014 unknown-field
// passthrough regression), jumpToNode, markImageFailed (QA-007), and the
// setError / load-error paths.
//
// Mocking: only the network helpers (apiGet/apiPost) are stubbed. The real
// sceneImageUrl + NODE_DEFAULTS are kept so the store's internal
// currentImageUrl derivation is exercised end-to-end.

import { describe, it, expect, beforeEach, vi } from "vitest";
import { useGameStore } from "./game-store";
import { NODE_DEFAULTS, type GameSave, type StoryNode } from "@/lib/api";

const apiFns = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiGet: apiFns.apiGet, apiPost: apiFns.apiPost };
});

beforeEach(() => {
  useGameStore.getState().reset();
  apiFns.apiGet.mockReset();
  apiFns.apiPost.mockReset();
});

function makeNode(overrides: Partial<StoryNode> = {}): StoryNode {
  return {
    ...NODE_DEFAULTS,
    id: "n1",
    narration: "narration",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeGame(overrides: Partial<GameSave> = {}): GameSave {
  const root = makeNode({ id: "root", narration: "root narration" });
  // `child` carries image_status "done" so sceneImageUrl yields a real URL for
  // derivation assertions.
  const child = makeNode({
    id: "child",
    narration: "child narration",
    image_status: "done",
  });
  return {
    version: 4,
    id: "g1",
    theme: { title: "T", setting: "S", premise: "P", keywords: [] },
    tone: { preset: "serious", custom_descriptor: null },
    narration_style: "third_person",
    art_style: "default",
    target_major_beats: 10,
    reader_level: "ages_11_15",
    pacing: "moderate",
    text_config: { provider: "openai", model: "gpt-4o-mini", base_url: null },
    image_config: { provider: "openai", model: "gpt-image-2", base_url: null },
    character_image_config: { provider: "openai", model: "gpt-image-2", base_url: null },
    characters: [],
    relationships: [],
    nodes: { root, child },
    root_node_id: "root",
    current_node_id: "root",
    endings_reached: [],
    total_image_cost_usd: 0,
    text_total_input_tokens: 0,
    text_total_output_tokens: 0,
    text_total_requests: 0,
    text_calls_by_model: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("useGameStore", () => {
  describe("loadGame", () => {
    it("populates currentGame, currentNode, characters, and narrationDelta on success", async () => {
      const game = makeGame();
      apiFns.apiGet.mockResolvedValue(game);

      await useGameStore.getState().loadGame("g1");

      const s = useGameStore.getState();
      expect(s.currentGame).not.toBeNull();
      expect(s.currentGame?.id).toBe("g1");
      // current_node_id in the fixture is "root".
      expect(s.currentNode?.id).toBe("root");
      expect(s.characters).toEqual(game.characters);
      expect(s.narrationDelta).toBe("root narration");
      expect(s.isLoading).toBe(false);
      expect(s.error).toBeNull();
      expect(apiFns.apiGet).toHaveBeenCalledWith("/api/games/g1");
    });

    it("derives a scene image URL when the current node has image_status done", async () => {
      const game = makeGame({ current_node_id: "child" });
      apiFns.apiGet.mockResolvedValue(game);

      await useGameStore.getState().loadGame("g1");

      expect(useGameStore.getState().currentImageUrl).toContain(
        "/api/images/g1/scene/child",
      );
    });

    it("leaves currentImageUrl null when the current node image is not done", async () => {
      const game = makeGame(); // current_node_id "root", image_status "not_planned"
      apiFns.apiGet.mockResolvedValue(game);

      await useGameStore.getState().loadGame("g1");

      expect(useGameStore.getState().currentImageUrl).toBeNull();
    });

    it("sets error and clears loading on fetch failure", async () => {
      apiFns.apiGet.mockRejectedValue(new Error("API 500: boom"));

      await useGameStore.getState().loadGame("g1");

      const s = useGameStore.getState();
      expect(s.isLoading).toBe(false);
      expect(s.currentGame).toBeNull();
      expect(s.error).toBe("API 500: boom");
    });

    it("uses a generic message when the thrown value is not an Error", async () => {
      apiFns.apiGet.mockRejectedValue("string error");

      await useGameStore.getState().loadGame("g1");

      expect(useGameStore.getState().error).toBe("Failed to load game");
    });
  });

  describe("advanceChoice", () => {
    it("sets optimistic loading state and clears narration/error before the POST resolves", async () => {
      useGameStore.setState({
        currentGame: makeGame(),
        narrationDelta: "stale",
        error: "prior",
      });
      // Hold the POST pending so we can observe the pre-await state.
      let resolvePost!: (v: { node: StoryNode }) => void;
      apiFns.apiPost.mockReturnValue(
        new Promise((r) => {
          resolvePost = r;
        }),
      );

      const pending = useGameStore.getState().advanceChoice("c1");
      const optimistic = useGameStore.getState();
      expect(optimistic.isLoading).toBe(true);
      expect(optimistic.narrationDelta).toBe("");
      expect(optimistic.error).toBeNull();

      resolvePost({
        node: makeNode({ id: "n2", narration: "advanced" }),
      });
      await pending;
    });

    it("merges the returned node, advances current_node_id, and derives its image URL", async () => {
      useGameStore.setState({ currentGame: makeGame() });
      const next = makeNode({
        id: "n2",
        narration: "advanced",
        image_status: "done",
      });
      apiFns.apiPost.mockResolvedValue({ node: next });

      await useGameStore.getState().advanceChoice("c1");

      const s = useGameStore.getState();
      expect(s.isLoading).toBe(false);
      expect(s.currentNode?.id).toBe("n2");
      expect(s.currentGame?.current_node_id).toBe("n2");
      expect(s.currentGame?.nodes["n2"]).toEqual(next);
      expect(s.narrationDelta).toBe("advanced");
      expect(s.currentImageUrl).toContain("/api/images/g1/scene/n2");
      expect(apiFns.apiPost).toHaveBeenCalledWith("/api/games/g1/advance", {
        choice_id: "c1",
      });
    });

    it("sets error and clears loading on advance failure", async () => {
      useGameStore.setState({ currentGame: makeGame() });
      apiFns.apiPost.mockRejectedValue(new Error("API 502: upstream"));

      await useGameStore.getState().advanceChoice("c1");

      const s = useGameStore.getState();
      expect(s.isLoading).toBe(false);
      expect(s.error).toBe("API 502: upstream");
    });

    it("no-ops when no game is loaded", async () => {
      await useGameStore.getState().advanceChoice("c1");
      expect(apiFns.apiPost).not.toHaveBeenCalled();
    });
  });

  describe("setBeatCommitted", () => {
    it("merges the node into the save, advances current_node_id, and clears loading", () => {
      useGameStore.setState({
        currentGame: makeGame(),
        isLoading: true,
        narrationDelta: "delta text",
      });
      const node = makeNode({ id: "beat-1", narration: "delta text" });

      useGameStore.getState().setBeatCommitted(node);

      const s = useGameStore.getState();
      expect(s.currentGame?.nodes["beat-1"]).toEqual(node);
      expect(s.currentGame?.current_node_id).toBe("beat-1");
      expect(s.currentNode?.id).toBe("beat-1");
      expect(s.isLoading).toBe(false);
    });

    it("no-ops when no game is loaded", () => {
      useGameStore.getState().setBeatCommitted(makeNode({ id: "beat-1" }));
      expect(useGameStore.getState().currentGame).toBeNull();
    });

    // QA-014 regression: useWebSocket.ts builds the node via a defaults-spread
    // ({...NODE_DEFAULTS, ...existingNode, ...beatFields}) precisely so that
    // fields the server adds in the future pass through instead of being
    // dropped by an explicit field-by-field reconstruction. setBeatCommitted
    // must store whatever it's given verbatim (id-keyed replace), not project
    // to a known-keys allowlist — pin that end-to-end.
    it("preserves unknown/extra fields on the merged node (QA-014)", () => {
      useGameStore.setState({ currentGame: makeGame() });
      const nodeWithExtra = {
        ...NODE_DEFAULTS,
        id: "beat-x",
        narration: "n",
        created_at: "2026-01-01T00:00:00Z",
        future_field: "keep-me", // not part of the StoryNode interface
      } as unknown as StoryNode;

      useGameStore.getState().setBeatCommitted(nodeWithExtra);

      const stored = useGameStore.getState().currentGame?.nodes["beat-x"];
      expect(stored).toBeDefined();
      expect((stored as Record<string, unknown>).future_field).toBe("keep-me");
    });
  });

  describe("jumpToNode", () => {
    it("switches currentNode to the target and derives its image URL", () => {
      useGameStore.setState({ currentGame: makeGame() });

      useGameStore.getState().jumpToNode("child"); // image_status "done"

      const s = useGameStore.getState();
      expect(s.currentNode?.id).toBe("child");
      expect(s.narrationDelta).toBe("child narration");
      expect(s.currentImageUrl).toContain("/api/images/g1/scene/child");
    });

    it("no-ops for an unknown node id (keeps the current node)", () => {
      useGameStore.setState({ currentGame: makeGame() });
      const before = useGameStore.getState().currentNode;

      useGameStore.getState().jumpToNode("does-not-exist");

      expect(useGameStore.getState().currentNode).toBe(before);
    });

    it("no-ops when no game is loaded", () => {
      useGameStore.getState().jumpToNode("child");
      expect(useGameStore.getState().currentNode).toBeNull();
    });
  });

  describe("markImageFailed (QA-007)", () => {
    it("flips the target node image_status to failed in the save", () => {
      useGameStore.setState({ currentGame: makeGame() });

      useGameStore.getState().markImageFailed("root");

      expect(
        useGameStore.getState().currentGame?.nodes["root"].image_status,
      ).toBe("failed");
    });

    it("updates currentNode too when it matches the failed node", () => {
      const game = makeGame();
      useGameStore.setState({ currentGame: game });
      useGameStore.getState().jumpToNode("root");
      expect(useGameStore.getState().currentNode?.id).toBe("root");

      useGameStore.getState().markImageFailed("root");

      expect(useGameStore.getState().currentNode?.image_status).toBe("failed");
    });

    it("leaves currentNode unchanged when failing a non-current node", () => {
      const game = makeGame();
      useGameStore.setState({ currentGame: game });
      useGameStore.getState().jumpToNode("child");
      const childBefore = useGameStore.getState().currentNode;
      expect(childBefore?.id).toBe("child");

      useGameStore.getState().markImageFailed("root");

      expect(useGameStore.getState().currentNode).toBe(childBefore);
      expect(useGameStore.getState().currentNode?.image_status).toBe("done");
      expect(
        useGameStore.getState().currentGame?.nodes["root"].image_status,
      ).toBe("failed");
    });

    it("no-ops when the node id is unknown (returns the same state ref)", () => {
      useGameStore.setState({ currentGame: makeGame() });
      const before = useGameStore.getState().currentGame;
      useGameStore.getState().markImageFailed("nope");
      expect(useGameStore.getState().currentGame).toBe(before);
    });

    it("no-ops when no game is loaded", () => {
      useGameStore.getState().markImageFailed("root");
      expect(useGameStore.getState().currentGame).toBeNull();
    });
  });

  describe("setError", () => {
    it("sets the error string", () => {
      useGameStore.getState().setError("boom");
      expect(useGameStore.getState().error).toBe("boom");
    });

    it("clears the error when passed null", () => {
      useGameStore.getState().setError("boom");
      useGameStore.getState().setError(null);
      expect(useGameStore.getState().error).toBeNull();
    });
  });

  describe("reset", () => {
    it("restores the initial state", () => {
      useGameStore.setState({
        currentGame: makeGame(),
        error: "x",
        narrationDelta: "y",
        isLoading: true,
      });

      useGameStore.getState().reset();

      const s = useGameStore.getState();
      expect(s.currentGame).toBeNull();
      expect(s.currentNode).toBeNull();
      expect(s.error).toBeNull();
      expect(s.narrationDelta).toBe("");
      expect(s.isLoading).toBe(false);
    });
  });
});
