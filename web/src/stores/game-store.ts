"use client";

import { create } from "zustand";
import {
  type GameSave,
  type StoryNode,
  type Character,
  type NodeId,
  apiGet,
  apiPost,
} from "@/lib/api";

const API = "http://localhost:8101";

interface GraphEdge {
  parent_id: string;
  choice_text: string;
  child_id: string;
}

interface GraphResponse {
  edges: GraphEdge[];
}

interface GameState {
  currentGame: GameSave | null;
  currentNode: StoryNode | null;
  /** Partial narration text during streaming */
  narrationDelta: string;
  /** Characters discovered so far in this game */
  characters: Character[];
  /** Whether a beat is being generated */
  isLoading: boolean;
  /** Current image URL for the scene */
  currentImageUrl: string | null;
  /** Error message to display */
  error: string | null;

  // Actions
  loadGame: (gameId: string) => Promise<void>;
  advanceChoice: (choiceId: string) => Promise<void>;
  jumpToNode: (nodeId: NodeId) => void;
  retryImage: (gameId: string) => Promise<void>;
  editImage: (gameId: string, prompt: string) => Promise<void>;
  regenerateNode: (gameId: string) => Promise<void>;
  fetchGraph: (gameId: string) => Promise<GraphResponse>;
  fetchEndings: (gameId: string) => Promise<string[]>;
  generateTts: (gameId: string, nodeId: string) => Promise<{ audio_url: string }>;
  exportBook: (gameId: string) => Promise<{ path: string; filename: string }>;
  setLoading: (loading: boolean) => void;
  appendNarration: (text: string) => void;
  setBeatCommitted: (node: StoryNode) => void;
  setImageStatus: (status: string) => void;
  setCurrentImageUrl: (url: string | null) => void;
  addCharacters: (chars: Character[]) => void;
  setError: (error: string | null) => void;
  refreshGame: (gameId: string) => Promise<void>;
  reset: () => void;
}

const initialState = {
  currentGame: null as GameSave | null,
  currentNode: null as StoryNode | null,
  narrationDelta: "",
  characters: [] as Character[],
  isLoading: false,
  currentImageUrl: null as string | null,
  error: null as string | null,
};

export const useGameStore = create<GameState>((set, get) => ({
  ...initialState,

  loadGame: async (gameId: string) => {
    set({ isLoading: true, error: null });
    try {
      const game = await apiGet<GameSave>(`/api/games/${gameId}`);
      const currentNode = game.nodes[game.current_node_id] ?? null;
      const imageUrl =
        currentNode?.image_status === "done"
          ? `${API}/api/images/${gameId}/scene/${game.current_node_id}`
          : null;
      set({
        currentGame: game,
        currentNode,
        characters: game.characters,
        isLoading: false,
        currentImageUrl: imageUrl,
        narrationDelta: currentNode?.narration ?? "",
      });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to load game",
      });
    }
  },

  advanceChoice: async (choiceId: string) => {
    const game = get().currentGame;
    if (!game) return;
    set({ isLoading: true, error: null, narrationDelta: "" });
    try {
      const result = await apiPost<{ node: StoryNode }>(
        `/api/games/${game.id}/advance`,
        { choice_id: choiceId }
      );
      const imageUrl =
        result.node.image_status === "done"
          ? `${API}/api/images/${game.id}/scene/${result.node.id}`
          : null;

      const updatedNodes = { ...game.nodes, [result.node.id]: result.node };
      set((state) => ({
        currentGame: state.currentGame
          ? {
              ...state.currentGame,
              nodes: updatedNodes,
              current_node_id: result.node.id,
            }
          : null,
        currentNode: result.node,
        isLoading: false,
        narrationDelta: result.node.narration,
        currentImageUrl: imageUrl,
      }));
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to advance",
      });
    }
  },

  jumpToNode: (nodeId: NodeId) => {
    const game = get().currentGame;
    if (!game) return;
    const node = game.nodes[nodeId];
    if (!node) return;
    const imageUrl =
      node.image_status === "done"
        ? `${API}/api/images/${game.id}/scene/${node.id}`
        : null;
    set({
      currentNode: node,
      narrationDelta: node.narration,
      currentImageUrl: imageUrl,
    });
  },

  setLoading: (loading: boolean) => set({ isLoading: loading }),
  appendNarration: (text: string) =>
    set((state) => ({ narrationDelta: state.narrationDelta + text })),
  setBeatCommitted: (node: StoryNode) => {
    const game = get().currentGame;
    if (!game) return;
    set((state) => ({
      currentGame: state.currentGame
        ? {
            ...state.currentGame,
            nodes: { ...state.currentGame.nodes, [node.id]: node },
            current_node_id: node.id,
          }
        : null,
      currentNode: node,
      isLoading: false,
    }));
  },
  setImageStatus: (_status: string) => {
    /* Used by WebSocket handler */
  },
  setCurrentImageUrl: (url: string | null) => set({ currentImageUrl: url }),
  addCharacters: (chars: Character[]) =>
    set((state) => {
      const existing = new Set(state.characters.map((c) => c.id));
      return {
        characters: [...state.characters, ...chars.filter((c) => !existing.has(c.id))],
      };
    }),
  setError: (error: string | null) => set({ error }),

  // --- New API actions ---

  retryImage: async (gameId: string) => {
    const node = get().currentNode;
    if (!node) return;
    set({ isLoading: true, error: null });
    try {
      await apiPost(`/api/images/${gameId}/scene/${node.id}/retry`);
      await get().refreshGame(gameId);
    } catch (err) {
      set({ isLoading: false, error: err instanceof Error ? err.message : "Retry failed" });
    }
  },

  editImage: async (gameId: string, prompt: string) => {
    const node = get().currentNode;
    if (!node) return;
    set({ isLoading: true, error: null });
    try {
      await apiPost(`/api/images/${gameId}/scene/${node.id}/edit`, { prompt });
      await get().refreshGame(gameId);
    } catch (err) {
      set({ isLoading: false, error: err instanceof Error ? err.message : "Edit failed" });
    }
  },

  regenerateNode: async (gameId: string) => {
    set({ isLoading: true, error: null, narrationDelta: "" });
    try {
      const result = await apiPost<{ node: StoryNode }>(
        `/api/games/${gameId}/regenerate-node`,
        {}
      );
      const imageUrl =
        result.node.image_status === "done"
          ? `${API}/api/images/${gameId}/scene/${result.node.id}`
          : null;
      const game = get().currentGame;
      const updatedNodes = { ...game?.nodes, [result.node.id]: result.node };
      set((state) => ({
        currentGame: state.currentGame
          ? {
              ...state.currentGame,
              nodes: updatedNodes,
              current_node_id: result.node.id,
            }
          : null,
        currentNode: result.node,
        isLoading: false,
        narrationDelta: result.node.narration,
        currentImageUrl: imageUrl,
      }));
    } catch (err) {
      set({ isLoading: false, error: err instanceof Error ? err.message : "Regenerate failed" });
    }
  },

  fetchGraph: async (gameId: string) => {
    return apiGet<GraphResponse>(`/api/games/${gameId}/graph`);
  },

  fetchEndings: async (gameId: string) => {
    return apiGet<string[]>(`/api/games/${gameId}/endings`);
  },

  generateTts: async (gameId: string, nodeId: string) => {
    return apiPost<{ audio_url: string }>(`/api/tts/${gameId}/${nodeId}/generate`);
  },

  exportBook: async (gameId: string) => {
    return apiPost<{ path: string; filename: string }>(`/api/games/${gameId}/export-book`);
  },

  refreshGame: async (gameId: string) => {
    try {
      const game = await apiGet<GameSave>(`/api/games/${gameId}`);
      const nodeId = game.current_node_id;
      const currentNode = game.nodes[nodeId] ?? null;
      const imageUrl =
        currentNode?.image_status === "done"
          ? `${API}/api/images/${gameId}/scene/${nodeId}`
          : null;
      set((state) => ({
        currentGame: game,
        currentNode: currentNode ?? state.currentNode,
        characters: game.characters,
        isLoading: false,
        currentImageUrl: imageUrl,
        narrationDelta: currentNode?.narration ?? state.narrationDelta,
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Refresh failed" });
    }
  },

  reset: () => set(initialState),
}));
