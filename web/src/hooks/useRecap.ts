"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Owns the recap modal
// open state and the auto-trigger effect (show recap once per node when
// settings allow). The ref tracks which node we've already auto-shown for.
import { useEffect, useRef, useState } from "react";
import type { SettingsResponse, StoryNode } from "@/lib/api";

export interface Recap {
  recapModal: boolean;
  setRecapModal: (open: boolean) => void;
}

export function useRecap(
  currentNode: StoryNode | null,
  settings: SettingsResponse | null,
): Recap {
  const [recapModal, setRecapModal] = useState(false);
  const recapShownForNode = useRef<string | null>(null);

  // Auto-trigger recap when a new node has recap_text and settings allow it
  useEffect(() => {
    if (!currentNode?.recap_text || !currentNode?.id) return;
    if (recapShownForNode.current === currentNode.id) return;
    if (recapModal) return;

    const autoRecap = settings?.auto_recap_enabled ?? true;
    const resumeRecap = settings?.resume_recap_enabled ?? true;

    if (autoRecap || resumeRecap) {
      recapShownForNode.current = currentNode.id;
      setRecapModal(true);
    }
  }, [
    currentNode?.id,
    currentNode?.recap_text,
    settings?.auto_recap_enabled,
    settings?.resume_recap_enabled,
    recapModal,
  ]);

  return { recapModal, setRecapModal };
}
