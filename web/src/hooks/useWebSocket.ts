"use client";

import { useEffect, useRef, useCallback } from "react";
import type { ServerEvent } from "@/lib/ws-types";
import type { StoryNode } from "@/lib/api";
import { API_BASE, WS_BASE } from "@/lib/config";
import { useGameStore } from "@/stores/game-store";

interface UseWebSocketOptions {
  gameId: string | null;
  enabled?: boolean;
}

export function useWebSocket({ gameId, enabled = true }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const appendNarration = useGameStore((s) => s.appendNarration);
  const setBeatCommitted = useGameStore((s) => s.setBeatCommitted);
  const setCurrentImageUrl = useGameStore((s) => s.setCurrentImageUrl);
  const setError = useGameStore((s) => s.setError);
  const addCharacters = useGameStore((s) => s.addCharacters);

  const connect = useCallback(() => {
    if (!gameId || !enabled) return;

    const ws = new WebSocket(`${WS_BASE}/api/ws/${gameId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log(`[WS] Connected to game ${gameId}`);
    };

    ws.onmessage = (event) => {
      try {
        const msg: ServerEvent = JSON.parse(event.data as string);
        switch (msg.type) {
          case "narration_delta":
            appendNarration(msg.text);
            break;
          case "beat_committed": {
            const store = useGameStore.getState();
            const game = store.currentGame;
            if (game) {
              const existingNode = game.nodes[msg.node_id];
              const node: StoryNode = {
                ...(existingNode ?? {}),
                id: msg.node_id,
                parent_id: existingNode?.parent_id ?? null,
                chosen_choice_id: existingNode?.chosen_choice_id ?? null,
                chosen_at: existingNode?.chosen_at ?? null,
                narration: store.narrationDelta,
                choices: msg.choices,
                is_major: existingNode?.is_major ?? false,
                is_ending: msg.is_ending,
                image_prompt: existingNode?.image_prompt ?? null,
                image_path: existingNode?.image_path ?? null,
                image_status: existingNode?.image_status ?? "not_planned",
                illustration_reasoning: existingNode?.illustration_reasoning ?? null,
                featured_character_ids: existingNode?.featured_character_ids ?? [],
                summary_to_here: existingNode?.summary_to_here ?? null,
                recap_text: existingNode?.recap_text ?? null,
                tts_audio_path: existingNode?.tts_audio_path ?? null,
                created_at: existingNode?.created_at ?? new Date().toISOString(),
              };
              setBeatCommitted(node);
            }
            break;
          }
          case "image_status":
            // Could update a per-node image status tracker
            break;
          case "image_committed":
            setCurrentImageUrl(
              `${API_BASE}/api/images/${gameId}/scene/${msg.node_id}`
            );
            break;
          case "image_failed":
            console.error(`[WS] Image failed for node ${msg.node_id}: ${msg.error}`);
            break;
          case "new_characters":
            addCharacters(msg.characters as Parameters<typeof addCharacters>[0]);
            break;
          case "error":
            setError(msg.message);
            break;
          case "pong":
            break;
        }
      } catch (err) {
        console.error("[WS] Failed to parse message:", err);
      }
    };

    ws.onclose = () => {
      console.log("[WS] Disconnected, reconnecting in 3s...");
      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, 3000);
    };

    ws.onerror = (err) => {
      console.error("[WS] Error:", err);
      ws.close();
    };
  }, [
    gameId,
    enabled,
    appendNarration,
    setBeatCommitted,
    setCurrentImageUrl,
    setError,
    addCharacters,
  ]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect on intentional close
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const send = useCallback((event: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(event));
    }
  }, []);

  return { send };
}
