"use client";

import { useEffect, useRef, useCallback } from "react";
import type { ServerEvent } from "@/lib/ws-types";
import type { StoryNode } from "@/lib/api";
import { NODE_DEFAULTS, sceneImageUrl } from "@/lib/api";
import { API_TOKEN, WS_BASE } from "@/lib/config";
import { useGameStore } from "@/stores/game-store";

// QA-016: keep WebSocket lifecycle logs out of production builds; real
// failures still surface unconditionally via console.error below.
function debugLog(...args: unknown[]): void {
  if (process.env.NODE_ENV !== "production") {
    console.log(...args);
  }
}

// QA-015: reconnect with exponential backoff. Base delay, multiplier, cap, and
// the close codes that signal an unrecoverable handshake failure (4403 auth
// refused, 4404 game not found — see src/storygen_api/routers/ws.py).
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
const FATAL_CLOSE_CODES = new Set([4403, 4404]);

interface UseWebSocketOptions {
  gameId: string | null;
  enabled?: boolean;
}

export function useWebSocket({ gameId, enabled = true }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef<number>(RECONNECT_BASE_MS);
  const appendNarration = useGameStore((s) => s.appendNarration);
  const setBeatCommitted = useGameStore((s) => s.setBeatCommitted);
  const setCurrentImageUrl = useGameStore((s) => s.setCurrentImageUrl);
  const setError = useGameStore((s) => s.setError);
  const addCharacters = useGameStore((s) => s.addCharacters);
  const markImageFailed = useGameStore((s) => s.markImageFailed);

  const connect = useCallback(() => {
    if (!gameId || !enabled) return;

    // SEC-102: when a bearer token is configured, offer it as the
    // ``bearer.<token>`` WebSocket subprotocol so the server's
    // ``ws_authorize`` accepts the handshake (browsers cannot set arbitrary
    // headers on a WS upgrade). The server reads the offered subprotocol
    // from the request; it does not need to echo it back for the browser to
    // consider the handshake successful. No token → plain WS (loopback-trust
    // mode in local dev).
    const wsUrl = `${WS_BASE}/api/ws/${gameId}`;
    const ws = API_TOKEN
      ? new WebSocket(wsUrl, [`bearer.${API_TOKEN}`])
      : new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      // QA-015: a successful open resets the backoff window so a brief blip
      // doesn't inherit a large retry delay after recovery.
      reconnectDelayRef.current = RECONNECT_BASE_MS;
      debugLog(`[WS] Connected to game ${gameId}`);
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
              // QA-014: defaults-spread merge. NODE_DEFAULTS supplies static
              // defaults, existingNode overrides with stored values (and
              // carries any new fields the server adds in the future), and the
              // beat-specific fields land last. created_at stays dynamic so a
              // freshly-created node gets a real timestamp.
              const node: StoryNode = {
                ...NODE_DEFAULTS,
                ...(existingNode ?? {}),
                id: msg.node_id,
                narration: store.narrationDelta,
                choices: msg.choices,
                is_ending: msg.is_ending,
                created_at: existingNode?.created_at ?? new Date().toISOString(),
              };
              setBeatCommitted(node);
            }
            break;
          }
          case "image_committed":
            // QA-013: route shape lives in sceneImageUrl. image_committed only
            // fires once the scene lands, so image_status is "done".
            setCurrentImageUrl(
              sceneImageUrl(gameId, { id: msg.node_id, image_status: "done" }),
            );
            break;
          case "image_failed":
            console.error(`[WS] Image failed for node ${msg.node_id}: ${msg.error}`);
            // QA-007: mark the node failed so ImagePanel shows a failure state
            // instead of an infinite spinner.
            markImageFailed(msg.node_id);
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

    ws.onclose = (event) => {
      // QA-015: 4403 (auth refused) and 4404 (game not found) are not
      // transient — retrying would hammer a guaranteed failure, so stop.
      if (FATAL_CLOSE_CODES.has(event.code)) {
        debugLog(`[WS] Closed with fatal code ${event.code}; not reconnecting`);
        return;
      }
      const delay = reconnectDelayRef.current;
      reconnectDelayRef.current = Math.min(delay * 2, RECONNECT_MAX_MS);
      debugLog(`[WS] Disconnected, reconnecting in ${delay}ms...`);
      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, delay);
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
    markImageFailed,
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
