"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Owns portrait
// regen/edit/export loading state + the shared portrait toast. The gallery
// modal and the page shell both consume this — the shell renders the toast.
import { useCallback, useState } from "react";
import { apiPost } from "@/lib/api";
import type { Character } from "@/lib/api";
import { useGameStore } from "@/stores/game-store";

export interface PortraitActions {
  regenLoading: boolean;
  editLoading: boolean;
  exportLoading: boolean;
  toastMessage: string | null;
  /** Show a toast for ~3s, then clear it. */
  notify: (msg: string) => void;
  clearToast: () => void;
  regen: (charId: string) => Promise<void>;
  /** Returns true on success — callers may gate close-on-success on this. */
  edit: (charId: string, prompt: string) => Promise<boolean>;
  exportChar: (char: Character) => Promise<void>;
}

const TOAST_MS = 3000;

export function usePortraitActions(gameId: string, gameTitle: string): PortraitActions {
  const [regenLoading, setRegenLoading] = useState(false);
  const [editLoading, setEditLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const notify = useCallback((msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), TOAST_MS);
  }, []);

  const regen = useCallback(
    async (charId: string) => {
      setRegenLoading(true);
      try {
        await apiPost(`/api/images/${gameId}/portrait/${charId}/retry`);
        await useGameStore.getState().refreshGame(gameId);
        notify("Portrait regenerated");
      } catch (err) {
        notify(`Failed: ${err instanceof Error ? err.message : "Unknown error"}`);
      } finally {
        setRegenLoading(false);
      }
    },
    [gameId, notify],
  );

  const edit = useCallback(
    async (charId: string, prompt: string): Promise<boolean> => {
      setEditLoading(true);
      try {
        await apiPost(`/api/images/${gameId}/portrait/${charId}/edit`, {
          prompt,
          mode: "full",
          use_current_as_ref: false,
        });
        await useGameStore.getState().refreshGame(gameId);
        notify("Portrait updated");
        return true;
      } catch (err) {
        notify(`Failed: ${err instanceof Error ? err.message : "Unknown error"}`);
        return false;
      } finally {
        setEditLoading(false);
      }
    },
    [gameId, notify],
  );

  const exportChar = useCallback(
    async (char: Character) => {
      setExportLoading(true);
      try {
        await apiPost("/api/characters", {
          name: char.name,
          backstory: char.backstory,
          personality: char.personality,
          physical_description: char.physical_description,
          portrait_prompt: char.portrait_prompt ?? "",
          save_id: gameId,
          save_title: gameTitle,
          character_id: char.id,
        });
        notify(`${char.name} exported to library`);
      } catch (err) {
        notify(`Export failed: ${err instanceof Error ? err.message : "Unknown error"}`);
      } finally {
        setExportLoading(false);
      }
    },
    [gameId, gameTitle, notify],
  );

  return {
    regenLoading,
    editLoading,
    exportLoading,
    toastMessage,
    notify,
    clearToast: () => setToastMessage(null),
    regen,
    edit,
    exportChar,
  };
}
