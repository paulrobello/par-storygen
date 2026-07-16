// ARC-015: tests for useWebSocket against canned ServerEvent payloads.
//
// This is the regression guard for ARC-001 (the three-way WS protocol
// divergence). Pre-ARC-001 the server emitted fields the React hook didn't
// read (delta vs text, status vs error, missing choices[]). These tests pin
// the post-fix contract: each canned payload carries the fields the hook's
// switch arms actually read, so a future server-side drift that drops a
// field surfaces as a failing assertion here rather than as a silently
// broken UI.

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "./useWebSocket";
import { useGameStore } from "@/stores/game-store";
import type { GameSave } from "@/lib/api";
import { MockWebSocket } from "../../vitest.setup";

// A minimal GameSave the hook's beat_committed handler accepts. The handler
// reads `store.currentGame` and no-ops if it's null, so beat_committed tests
// must seed the store first. Only the fields the handler touches need to be
// realistic; the rest are placeholders.
function _minimalGame(): GameSave {
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
    nodes: {},
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
  };
}

// Reset the Zustand store + MockWebSocket instance log between tests so
// assertions don't leak across cases.
beforeEach(() => {
  useGameStore.getState().reset();
  MockWebSocket.instances.length = 0;
});

afterEach(() => {
  useGameStore.getState().reset();
});

describe("useWebSocket", () => {
  it("connects to /api/ws/{gameId} on mount", () => {
    renderHook(() => useWebSocket({ gameId: "game-123" }));
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toContain("/api/ws/game-123");
  });

  it("appends narration_delta.text to the store's narration buffer", () => {
    const { result } = renderHook(() => useWebSocket({ gameId: "g1" }));
    // The hook returns { send }; we don't need it, but result must be used.
    expect(result.current).toBeDefined();
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.__receive({ type: "narration_delta", node_id: "n1", text: "Hello " });
      ws.__receive({ type: "narration_delta", node_id: "n1", text: "world." });
    });

    expect(useGameStore.getState().narrationDelta).toBe("Hello world.");
  });

  it("stores beat_committed with choices[] (ARC-001: was missing pre-fix)", () => {
    // Seed currentGame: the hook's beat_committed handler no-ops without one.
    useGameStore.setState({ currentGame: _minimalGame() });
    renderHook(() => useWebSocket({ gameId: "g1" }));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.__receive({
        type: "beat_committed",
        node_id: "node-42",
        is_ending: false,
        choices: [
          { id: "c1", text: "Go left", child_node_id: null },
          { id: "c2", text: "Go right", child_node_id: "node-43" },
        ],
      });
    });

    const game = useGameStore.getState().currentGame;
    expect(game).not.toBeNull();
    // The hook builds a StoryNode with the beat's choices and id.
    const node = game!.nodes["node-42"];
    expect(node).toBeDefined();
    expect(node.id).toBe("node-42");
    expect(node.is_ending).toBe(false);
    expect(node.choices).toHaveLength(2);
    expect(node.choices[0].id).toBe("c1");
    expect(node.choices[1].child_node_id).toBe("node-43");
  });

  it("sets the current image URL on image_committed (ARC-001: was never emitted)", () => {
    renderHook(() => useWebSocket({ gameId: "g1" }));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.__receive({
        type: "image_committed",
        node_id: "node-42",
        image_path: "games/g1/scene/node-42.png",
      });
    });

    // The hook builds the full URL from API_BASE + /api/images/...
    expect(useGameStore.getState().currentImageUrl).toContain(
      "/api/images/g1/scene/node-42"
    );
  });

  it("dispatches new_characters with the full card fields", () => {
    renderHook(() => useWebSocket({ gameId: "g1" }));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.__receive({
        type: "new_characters",
        characters: [
          {
            id: "c1",
            name: "Alyx",
            backstory: "A retired pilot.",
            personality: "Brave.",
            physical_description: "Tall.",
            portrait_path: null,
          },
        ],
      });
    });

    const chars = useGameStore.getState().characters;
    expect(chars).toHaveLength(1);
    expect(chars[0].name).toBe("Alyx");
    expect(chars[0].backstory).toBe("A retired pilot.");
  });

  it("sets the store error on error.message (ARC-001: server sent {error}, hook read {message})", () => {
    renderHook(() => useWebSocket({ gameId: "g1" }));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.__receive({ type: "error", code: "internal_error", message: "boom" });
    });

    expect(useGameStore.getState().error).toBe("boom");
  });

  it("does not throw on image_failed (logs only; ARC-001: error field contract)", () => {
    renderHook(() => useWebSocket({ gameId: "g1" }));
    const ws = MockWebSocket.instances[0];

    expect(() => {
      act(() => {
        ws.__receive({
          type: "image_failed",
          node_id: "n1",
          error: "image generation failed",
        });
      });
    }).not.toThrow();
    // image_failed is console.error'd by the hook; store error is unchanged.
    expect(useGameStore.getState().error).toBeNull();
  });
});
