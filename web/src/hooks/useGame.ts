"use client";

import { useEffect } from "react";
import { useGameStore } from "@/stores/game-store";

export function useGame(gameId: string | null) {
  const loadGame = useGameStore((s) => s.loadGame);
  const advanceChoice = useGameStore((s) => s.advanceChoice);
  const jumpToNode = useGameStore((s) => s.jumpToNode);
  const currentGame = useGameStore((s) => s.currentGame);
  const currentNode = useGameStore((s) => s.currentNode);
  const isLoading = useGameStore((s) => s.isLoading);
  const error = useGameStore((s) => s.error);
  const characters = useGameStore((s) => s.characters);
  const narrationDelta = useGameStore((s) => s.narrationDelta);
  const currentImageUrl = useGameStore((s) => s.currentImageUrl);

  useEffect(() => {
    if (gameId) {
      loadGame(gameId);
    }
  }, [gameId, loadGame]);

  return {
    currentGame,
    currentNode,
    isLoading,
    error,
    characters,
    narrationDelta,
    currentImageUrl,
    advanceChoice,
    jumpToNode,
    reload: () => gameId && loadGame(gameId),
  };
}
