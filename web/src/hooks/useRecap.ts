"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Owns the recap modal
// open state and the auto-trigger (show recap once per node when settings
// allow), implemented as a render-phase state adjustment.
import { useState } from "react";
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
  // Node the auto-trigger last fired for. Firing at most once per node is
  // guarded by state instead of a ref so the check is render-safe.
  const [autoShownFor, setAutoShownFor] = useState<string | null>(null);

  // Auto-trigger recap when a new node has recap_text and settings allow it.
  // Render-phase adjustment (react.dev/learn/you-might-not-need-an-effect):
  // re-evaluated on every render, so a settings change while sitting on the
  // same node still opens the recap, as the old effect did.
  if (
    currentNode?.id &&
    currentNode.recap_text &&
    currentNode.id !== autoShownFor &&
    !recapModal
  ) {
    const autoRecap = settings?.auto_recap_enabled ?? true;
    const resumeRecap = settings?.resume_recap_enabled ?? true;

    if (autoRecap || resumeRecap) {
      setAutoShownFor(currentNode.id);
      setRecapModal(true);
    }
  }

  return { recapModal, setRecapModal };
}
