"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Owns TTS read-aloud
// loading state for the scene narration + recap, plus auto-play (random
// choice every 3s). Auto-play needs isStreaming + advanceChoice so it can
// gate itself during beat generation.
import { useCallback, useEffect, useState } from "react";
import { API_BASE as API } from "@/lib/config";
import type { StoryNode } from "@/lib/api";
import { useGameStore } from "@/stores/game-store";

export interface PlayTts {
  ttsLoading: boolean;
  recapTtsLoading: boolean;
  autoPlay: boolean;
  toggleAutoPlay: () => void;
  readAloud: () => Promise<void>;
  recapReadAloud: () => Promise<void>;
}

const AUTO_PLAY_DELAY_MS = 3000;

export function usePlayTts(
  gameId: string,
  currentNode: StoryNode | null,
  isStreaming: boolean,
  advanceChoice: (choiceId: string) => Promise<void>,
): PlayTts {
  const [autoPlay, setAutoPlay] = useState(false);
  const [ttsLoading, setTtsLoading] = useState(false);
  const [recapTtsLoading, setRecapTtsLoading] = useState(false);

  const readAloud = useCallback(async () => {
    if (!currentNode) return;
    setTtsLoading(true);
    try {
      const result = await useGameStore.getState().generateTts(gameId, currentNode.id);
      // Trigger audio playback
      const audio = new Audio(`${API}${result.audio_url}`);
      audio.play().catch(() => {});
    } catch {
      /* error set in store */
    } finally {
      setTtsLoading(false);
    }
  }, [gameId, currentNode]);

  const recapReadAloud = useCallback(async () => {
    if (!currentNode) return;
    setRecapTtsLoading(true);
    try {
      const result = await useGameStore.getState().generateTts(gameId, currentNode.id);
      const audio = new Audio(`${API}${result.audio_url}`);
      audio.play().catch(() => {});
    } catch {
      /* silently fail */
    } finally {
      setRecapTtsLoading(false);
    }
  }, [gameId, currentNode]);

  // Auto-play: pick a random choice after a delay. Re-checks conditions at
  // fire time since they may have changed since the timer was scheduled.
  useEffect(() => {
    if (!autoPlay) return;
    if (isStreaming || !currentNode || currentNode.is_ending) return;
    const choices = currentNode.choices ?? [];
    if (choices.length === 0) return;
    const timer = setTimeout(() => {
      const state = useGameStore.getState();
      if (state.isLoading || !state.currentNode) return;
      if (state.currentNode.is_ending) {
        setAutoPlay(false);
        return;
      }
      const currentChoices = state.currentNode.choices ?? [];
      if (currentChoices.length === 0) {
        setAutoPlay(false);
        return;
      }
      const randomIdx = Math.floor(Math.random() * currentChoices.length);
      advanceChoice(currentChoices[randomIdx].id);
    }, AUTO_PLAY_DELAY_MS);
    return () => clearTimeout(timer);
  }, [autoPlay, isStreaming, currentNode, advanceChoice]);

  const toggleAutoPlay = useCallback(() => setAutoPlay((p) => !p), []);

  return { ttsLoading, recapTtsLoading, autoPlay, toggleAutoPlay, readAloud, recapReadAloud };
}
