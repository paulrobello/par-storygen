"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Owns the scene-image
// retry/edit flow and the edit-prompt modal state. The scene image URL +
// image status live in game-store (currentImageUrl, currentNode.image_status).
import { useCallback, useState } from "react";
import type { StoryNode } from "@/lib/api";
import { useGameStore } from "@/stores/game-store";

export interface SceneImage {
  editImageModal: boolean;
  editPrompt: string;
  setEditPrompt: (p: string) => void;
  retryImage: () => Promise<void>;
  openEdit: () => void;
  closeEdit: () => void;
  submitEdit: () => Promise<void>;
}

export function useSceneImage(gameId: string, currentNode: StoryNode | null): SceneImage {
  const [editImageModal, setEditImageModal] = useState(false);
  const [editPrompt, setEditPrompt] = useState("");

  const retryImage = useCallback(async () => {
    await useGameStore.getState().retryImage(gameId);
  }, [gameId]);

  const openEdit = useCallback(() => {
    if (!currentNode?.image_prompt) return;
    setEditPrompt(currentNode.image_prompt);
    setEditImageModal(true);
  }, [currentNode?.image_prompt]);

  const submitEdit = useCallback(async () => {
    if (!editPrompt.trim()) return;
    setEditImageModal(false);
    await useGameStore.getState().editImage(gameId, editPrompt);
  }, [gameId, editPrompt]);

  return {
    editImageModal,
    editPrompt,
    setEditPrompt,
    retryImage,
    openEdit,
    closeEdit: () => setEditImageModal(false),
    submitEdit,
  };
}
