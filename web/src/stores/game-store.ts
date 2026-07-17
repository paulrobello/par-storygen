"use client";

import { create } from "zustand";
import {
  type GameSave,
  type StoryNode,
  type Character,
  type NodeId,
  apiGet,
  apiPost,
  sceneImageUrl,
} from "@/lib/api";

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
  markImageFailed: (nodeId: NodeId) => void;
  setCurrentImageUrl: (url: string | null) => void;
  addCharacters: (chars: Character[]) => void;
  updateCharacter: (characterId: string, updates: Partial<Pick<Character, "name" | "personality" | "physical_description" | "backstory">>) => void;
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
      const imageUrl = currentNode ? sceneImageUrl(gameId, currentNode) : null;
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
      const imageUrl = sceneImageUrl(game.id, result.node);

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
    const imageUrl = sceneImageUrl(game.id, node);
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
  markImageFailed: (nodeId: NodeId) =>
    set((state) => {
      const game = state.currentGame;
      if (!game) return state;
      const failed = game.nodes[nodeId];
      if (!failed) return state;
      // QA-007: flip the node's image_status to "failed" so ImagePanel shows a
      // failure state instead of an infinite spinner. Also update currentNode
      // when it matches, since ImagePanel reads from currentNode.
      const updatedNode = { ...failed, image_status: "failed" as const };
      return {
        currentGame: {
          ...game,
          nodes: { ...game.nodes, [nodeId]: updatedNode },
        },
        currentNode:
          state.currentNode?.id === nodeId ? updatedNode : state.currentNode,
      };
    }),
  setCurrentImageUrl: (url: string | null) => set({ currentImageUrl: url }),
  addCharacters: (chars: Character[]) =>
    set((state) => {
      const existing = new Set(state.characters.map((c) => c.id));
      return {
        characters: [...state.characters, ...chars.filter((c) => !existing.has(c.id))],
      };
    }),
  updateCharacter: (characterId, updates) =>
    set((state) => {
      const updatedCharacters = state.characters.map((c) =>
        c.id === characterId ? { ...c, ...updates } : c
      );
      const updatedGame = state.currentGame
        ? {
            ...state.currentGame,
            characters: state.currentGame.characters.map((c) =>
              c.id === characterId ? { ...c, ...updates } : c
            ),
          }
        : null;
      return { characters: updatedCharacters, currentGame: updatedGame };
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
      const imageUrl = sceneImageUrl(gameId, result.node);
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
      const imageUrl = currentNode ? sceneImageUrl(gameId, currentNode) : null;
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
