"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Owns the replay modal
// state (open/index/nodes), the open handler that fetches the node path, and
// the arrow-key / space keyboard navigation effect.
import { useCallback, useEffect, useState } from "react";
import type React from "react";
import { apiGet } from "@/lib/api";
import type { StoryNode } from "@/lib/api";

export interface Replay {
  replayModal: boolean;
  replayIndex: number;
  replayNodes: StoryNode[];
  setReplayIndex: React.Dispatch<React.SetStateAction<number>>;
  viewReplay: () => Promise<void>;
  closeReplay: () => void;
}

export function useReplay(gameId: string, currentNode: StoryNode | null): Replay {
  const [replayModal, setReplayModal] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayNodes, setReplayNodes] = useState<StoryNode[]>([]);

  const viewReplay = useCallback(async () => {
    if (!gameId || !currentNode) return;
    try {
      const nodes = await apiGet<StoryNode[]>(
        `/api/games/${gameId}/path?target_node_id=${currentNode.id}`,
      );
      setReplayNodes(nodes);
      setReplayIndex(0);
      setReplayModal(true);
    } catch {
      /* silently fail */
    }
  }, [gameId, currentNode]);

  // Keyboard navigation for replay modal
  useEffect(() => {
    if (!replayModal) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        setReplayIndex((i) => Math.min(i + 1, replayNodes.length - 1));
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setReplayIndex((i) => Math.max(i - 1, 0));
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [replayModal, replayNodes.length]);

  return {
    replayModal,
    replayIndex,
    replayNodes,
    setReplayIndex,
    viewReplay,
    closeReplay: () => setReplayModal(false),
  };
}
