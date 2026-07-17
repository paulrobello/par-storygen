"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Owns the graph + endings
// modal open states, their fetched data, and the four handlers that open /
// close / jump / prune them. The modals themselves are presentational
// components under web/src/components/play/.
import { useCallback, useState } from "react";
import { useGameStore } from "@/stores/game-store";

export interface GraphEdge {
  parent_id: string;
  choice_text: string;
  child_id: string | null;
}

export interface GameViews {
  graphModal: boolean;
  endingsModal: boolean;
  graphEdges: GraphEdge[];
  endingsList: string[];
  closeGraph: () => void;
  closeEndings: () => void;
  viewGraph: () => Promise<void>;
  viewEndings: () => Promise<void>;
  jumpToEnding: (nodeId: string) => void;
  prune: () => Promise<void>;
}

export function useGameViews(gameId: string): GameViews {
  const [graphModal, setGraphModal] = useState(false);
  const [endingsModal, setEndingsModal] = useState(false);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [endingsList, setEndingsList] = useState<string[]>([]);

  const viewGraph = useCallback(async () => {
    try {
      const data = await useGameStore.getState().fetchGraph(gameId);
      setGraphEdges(data.edges);
      setGraphModal(true);
    } catch {
      /* error set in store */
    }
  }, [gameId]);

  const viewEndings = useCallback(async () => {
    try {
      const data = await useGameStore.getState().fetchEndings(gameId);
      setEndingsList(data);
      setEndingsModal(true);
    } catch {
      /* error set in store */
    }
  }, [gameId]);

  const jumpToEnding = useCallback((nodeId: string) => {
    setEndingsModal(false);
    useGameStore.getState().jumpToNode(nodeId);
  }, []);

  // Prune handler — refresh game data after pruning from the graph, then
  // re-fetch graph edges so the graph updates.
  const prune = useCallback(async () => {
    await useGameStore.getState().refreshGame(gameId);
    try {
      const data = await useGameStore.getState().fetchGraph(gameId);
      setGraphEdges(data.edges);
    } catch {
      /* graph refresh is best-effort */
    }
  }, [gameId]);

  return {
    graphModal,
    endingsModal,
    graphEdges,
    endingsList,
    closeGraph: () => setGraphModal(false),
    closeEndings: () => setEndingsModal(false),
    viewGraph,
    viewEndings,
    jumpToEnding,
    prune,
  };
}
