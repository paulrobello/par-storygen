"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  apiDelete,
  apiGet,
  apiPost,
  apiPostForm,
  apiPut,
} from "@/lib/api";
import type {
  CharacterLibraryResponse,
  LibraryCharacter,
  PortraitEditRequest,
  StoryImportRequest,
} from "@/lib/api";

/** Editable character fields rendered in the detail modal. */
export interface CharacterEditForm {
  name: string;
  personality: string;
  physical_description: string;
  backstory: string;
}

/** Input to {@link CharacterActions.createCharacter}. */
export interface CreateCharacterInput {
  name: string;
  concept: string;
  referenceImage: File | null;
}

export type ReferenceImageMode = "use_as_is" | "style_transfer";

export interface CharacterActions {
  characters: LibraryCharacter[];
  isLoading: boolean;
  error: string | null;
  showError: (msg: string) => void;
  refresh: () => Promise<LibraryCharacter[]>;
  saveCharacter: (
    char: LibraryCharacter,
    form: CharacterEditForm
  ) => Promise<LibraryCharacter>;
  deleteCharacter: (char: LibraryCharacter) => Promise<void>;
  regeneratePortrait: (char: LibraryCharacter) => Promise<LibraryCharacter>;
  editPortrait: (
    char: LibraryCharacter,
    body: PortraitEditRequest
  ) => Promise<LibraryCharacter>;
  uploadReferenceImage: (
    char: LibraryCharacter,
    file: File,
    mode: ReferenceImageMode
  ) => Promise<LibraryCharacter | null>;
  removeReferenceImage: (
    char: LibraryCharacter
  ) => Promise<LibraryCharacter>;
  createCharacter: (input: CreateCharacterInput) => Promise<LibraryCharacter[]>;
  importFromStory: (saveId: string, charIds: Set<string>) => Promise<void>;
}

/** How long a transient error banner stays visible before auto-dismissing. */
const ERROR_AUTO_DISMISS_MS = 5000;

/**
 * Owns the character-library list state and the per-character async actions
 * (regen / edit / save / delete / reference-image / create / import).
 *
 * Each action performs the API call, applies the resulting mutation to the
 * in-memory list, and returns the updated character (or list) so the caller
 * can sync any detail-view state it owns. Errors are surfaced through the
 * shared `error` banner via `showError`; callers do not need their own
 * try/catch unless they want additional recovery.
 */
export function useCharacterActions(): CharacterActions {
  const [characters, setCharacters] = useState<LibraryCharacter[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const errorTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showError = useCallback((msg: string) => {
    setError(msg);
    if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current);
    errorTimeoutRef.current = setTimeout(
      () => setError(null),
      ERROR_AUTO_DISMISS_MS
    );
  }, []);

  const refresh = useCallback(async (): Promise<LibraryCharacter[]> => {
    const result = await apiGet<CharacterLibraryResponse>("/api/characters");
    setCharacters(result.characters);
    return result.characters;
  }, []);

  const upsert = useCallback((updated: LibraryCharacter) => {
    setCharacters((prev) =>
      prev.map((c) => (c.id === updated.id ? updated : c))
    );
  }, []);

  const saveCharacter = useCallback(
    async (char: LibraryCharacter, form: CharacterEditForm) => {
      await apiPut(`/api/characters/${char.id}`, form);
      const updated: LibraryCharacter = { ...char, ...form };
      upsert(updated);
      return updated;
    },
    [upsert]
  );

  const deleteCharacter = useCallback(async (char: LibraryCharacter) => {
    await apiDelete(`/api/characters/${char.id}`);
    setCharacters((prev) => prev.filter((c) => c.id !== char.id));
  }, []);

  const regeneratePortrait = useCallback(
    async (char: LibraryCharacter) => {
      await apiPost(`/api/characters/${char.id}/regenerate-portrait`);
      const updated: LibraryCharacter = { ...char, has_portrait: true };
      upsert(updated);
      return updated;
    },
    [upsert]
  );

  const editPortrait = useCallback(
    async (char: LibraryCharacter, body: PortraitEditRequest) => {
      await apiPost(`/api/characters/${char.id}/edit-portrait`, body);
      const updated: LibraryCharacter = { ...char, has_portrait: true };
      upsert(updated);
      return updated;
    },
    [upsert]
  );

  const uploadReferenceImage = useCallback(
    async (
      char: LibraryCharacter,
      file: File,
      mode: ReferenceImageMode
    ): Promise<LibraryCharacter | null> => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("mode", mode);
      await apiPostForm(`/api/characters/${char.id}/reference-image`, formData);
      // Refresh so the updated reference_image_path is reflected.
      const chars = await refresh();
      return chars.find((c) => c.id === char.id) ?? null;
    },
    [refresh]
  );

  const removeReferenceImage = useCallback(
    async (char: LibraryCharacter) => {
      await apiDelete(`/api/characters/${char.id}/reference-image`);
      const updated: LibraryCharacter = {
        ...char,
        reference_image_path: null,
      };
      upsert(updated);
      return updated;
    },
    [upsert]
  );

  const createCharacter = useCallback(
    async (input: CreateCharacterInput): Promise<LibraryCharacter[]> => {
      const concept = input.concept.trim();
      const name = input.name.trim();
      if (input.referenceImage) {
        const formData = new FormData();
        formData.append("concept", concept);
        if (name) formData.append("name", name);
        formData.append("reference_image", input.referenceImage);
        await apiPostForm("/api/characters/create", formData);
      } else {
        await apiPost("/api/characters/create", {
          concept,
          ...(name ? { name } : {}),
        });
      }
      return refresh();
    },
    [refresh]
  );

  const importFromStory = useCallback(
    async (saveId: string, charIds: Set<string>) => {
      const body: StoryImportRequest = {
        save_id: saveId,
        character_ids: Array.from(charIds),
      };
      await apiPost("/api/characters/import-from-story", body);
      await refresh();
    },
    [refresh]
  );

  // Initial library load.
  useEffect(() => {
    async function load() {
      try {
        await refresh();
      } catch (err) {
        showError(
          err instanceof Error ? err.message : "Failed to load characters"
        );
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, [refresh, showError]);

  // Clear any pending error-dismiss timeout on unmount.
  useEffect(() => {
    return () => {
      if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current);
    };
  }, []);

  return {
    characters,
    isLoading,
    error,
    showError,
    refresh,
    saveCharacter,
    deleteCharacter,
    regeneratePortrait,
    editPortrait,
    uploadReferenceImage,
    removeReferenceImage,
    createCharacter,
    importFromStory,
  };
}
