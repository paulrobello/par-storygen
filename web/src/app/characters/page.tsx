"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { GameLayout } from "@/components/layout/GameLayout";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { Modal } from "@/components/ui/Modal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  apiGet,
  apiPost,
  apiPut,
  apiDelete,
  apiPostForm,
} from "@/lib/api";
import type {
  LibraryCharacter,
  CharacterLibraryResponse,
  GameSave,
  GameSummary,
  PortraitEditRequest,
  StoryImportRequest,
} from "@/lib/api";
import {
  Trash2,
  User,
  Plus,
  Download,
  RefreshCw,
  Pencil,
  ImagePlus,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Save,
} from "lucide-react";
import { API_BASE } from "@/lib/config";

// ---------------------------------------------------------------------------
// Local form state type
// ---------------------------------------------------------------------------

interface EditForm {
  name: string;
  personality: string;
  physical_description: string;
  backstory: string;
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function CharactersPage() {
  // ---- Character list state ----
  const [characters, setCharacters] = useState<LibraryCharacter[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const errorTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- Character detail modal ----
  const [selectedCharacter, setSelectedCharacter] =
    useState<LibraryCharacter | null>(null);
  const [editForm, setEditForm] = useState<EditForm>({
    name: "",
    personality: "",
    physical_description: "",
    backstory: "",
  });
  const [originalPhysicalDesc, setOriginalPhysicalDesc] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  // ---- Portrait loading ----
  const [portraitLoading, setPortraitLoading] = useState(false);
  const [portraitLoadingText, setPortraitLoadingText] = useState("");
  const [portraitVersion, setPortraitVersion] = useState(0);

  // ---- Portrait edit sub-modal ----
  const [showPortraitEdit, setShowPortraitEdit] = useState(false);
  const [pePrompt, setPePrompt] = useState("");
  const [peMode, setPeMode] = useState<"edit" | "full">("edit");
  const [peUseRef, setPeUseRef] = useState(false);

  // ---- Reference image sub-modal ----
  const [showRefImage, setShowRefImage] = useState(false);
  const [refFile, setRefFile] = useState<File | null>(null);
  const [refPreview, setRefPreview] = useState<string | null>(null);
  const [refMode, setRefMode] = useState<"use_as_is" | "style_transfer">(
    "use_as_is"
  );
  const refFileInputRef = useRef<HTMLInputElement>(null);

  // ---- Create character modal ----
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createConcept, setCreateConcept] = useState("");
  const [createRefFile, setCreateRefFile] = useState<File | null>(null);
  const [createRefPreview, setCreateRefPreview] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const createFileInputRef = useRef<HTMLInputElement>(null);

  // ---- Import from story modal ----
  const [showImport, setShowImport] = useState(false);
  const [games, setGames] = useState<GameSummary[]>([]);
  const [expandedGameId, setExpandedGameId] = useState<string | null>(null);
  const [gameCharsMap, setGameCharsMap] = useState<
    Map<string, LibraryCharacter[]>
  >(new Map());
  const [isLoadingGames, setIsLoadingGames] = useState(false);
  const [loadingGameChars, setLoadingGameChars] = useState(false);
  const [selectedImportIds, setSelectedImportIds] = useState<Set<string>>(
    new Set()
  );
  const [isImporting, setIsImporting] = useState(false);

  // ---- Delete confirmation ----
  const [deleteTarget, setDeleteTarget] = useState<LibraryCharacter | null>(
    null
  );

  // =========================================================================
  // Helpers
  // =========================================================================

  const showError = useCallback((msg: string) => {
    setError(msg);
    if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current);
    errorTimeoutRef.current = setTimeout(() => setError(null), 5000);
  }, []);

  const refreshCharacters = useCallback(async (): Promise<LibraryCharacter[]> => {
    const result = await apiGet<CharacterLibraryResponse>("/api/characters");
    setCharacters(result.characters);
    return result.characters;
  }, []);

  const openDetail = useCallback((char: LibraryCharacter) => {
    setSelectedCharacter(char);
    setEditForm({
      name: char.name,
      personality: char.personality,
      physical_description: char.physical_description,
      backstory: char.backstory,
    });
    setOriginalPhysicalDesc(char.physical_description);
  }, []);

  const closeDetail = useCallback(() => {
    setSelectedCharacter(null);
    setShowPortraitEdit(false);
    setShowRefImage(false);
  }, []);

  // =========================================================================
  // Initial data load
  // =========================================================================

  useEffect(() => {
    async function load() {
      try {
        await refreshCharacters();
      } catch (err) {
        showError(
          err instanceof Error ? err.message : "Failed to load characters"
        );
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, [refreshCharacters, showError]);

  // Cleanup error timeout on unmount
  useEffect(() => {
    return () => {
      if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current);
    };
  }, []);

  // =========================================================================
  // Character detail handlers
  // =========================================================================

  const handleSave = async () => {
    if (!selectedCharacter) return;
    setIsSaving(true);
    try {
      await apiPut(`/api/characters/${selectedCharacter.id}`, editForm);
      const updated: LibraryCharacter = {
        ...selectedCharacter,
        ...editForm,
      };
      setSelectedCharacter(updated);
      setCharacters((prev) =>
        prev.map((c) => (c.id === updated.id ? updated : c))
      );
      setOriginalPhysicalDesc(editForm.physical_description);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await apiDelete(`/api/characters/${deleteTarget.id}`);
      setCharacters((prev) => prev.filter((c) => c.id !== deleteTarget.id));
      if (selectedCharacter?.id === deleteTarget.id) closeDetail();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setDeleteTarget(null);
    }
  };

  // =========================================================================
  // Portrait handlers
  // =========================================================================

  const handleRegeneratePortrait = async () => {
    if (!selectedCharacter) return;
    setPortraitLoading(true);
    setPortraitLoadingText("Regenerating...");
    try {
      await apiPost(`/api/characters/${selectedCharacter.id}/regenerate-portrait`);
      setPortraitVersion((v) => v + 1);
      const updated: LibraryCharacter = {
        ...selectedCharacter,
        has_portrait: true,
      };
      setSelectedCharacter(updated);
      setCharacters((prev) =>
        prev.map((c) => (c.id === updated.id ? updated : c))
      );
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to regenerate portrait"
      );
    } finally {
      setPortraitLoading(false);
      setPortraitLoadingText("");
    }
  };

  const openPortraitEdit = () => {
    if (!selectedCharacter) return;
    setPePrompt("");
    setPeMode("edit");
    setPeUseRef(false);
    setShowPortraitEdit(true);
  };

  const handleSubmitPortraitEdit = async () => {
    if (!selectedCharacter || !pePrompt.trim()) return;
    setPortraitLoading(true);
    setPortraitLoadingText("Generating...");
    setShowPortraitEdit(false);
    try {
      const body: PortraitEditRequest = {
        prompt: pePrompt.trim(),
        mode: peMode,
        use_current_as_ref: peUseRef,
      };
      await apiPost(
        `/api/characters/${selectedCharacter.id}/edit-portrait`,
        body
      );
      setPortraitVersion((v) => v + 1);
      const updated: LibraryCharacter = {
        ...selectedCharacter,
        has_portrait: true,
      };
      setSelectedCharacter(updated);
      setCharacters((prev) =>
        prev.map((c) => (c.id === updated.id ? updated : c))
      );
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to edit portrait"
      );
    } finally {
      setPortraitLoading(false);
      setPortraitLoadingText("");
    }
  };

  // =========================================================================
  // Reference image handlers
  // =========================================================================

  const openRefImageModal = () => {
    setRefFile(null);
    setRefPreview(null);
    setRefMode("use_as_is");
    setShowRefImage(true);
  };

  const handleRefFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setRefFile(file);
    if (file) {
      const url = URL.createObjectURL(file);
      setRefPreview(url);
    } else {
      setRefPreview(null);
    }
  };

  const handleUploadRefImage = async () => {
    if (!selectedCharacter || !refFile) return;
    setPortraitLoading(true);
    setPortraitLoadingText("Uploading...");
    setShowRefImage(false);
    try {
      const formData = new FormData();
      formData.append("file", refFile);
      formData.append("mode", refMode);
      await apiPostForm(
        `/api/characters/${selectedCharacter.id}/reference-image`,
        formData
      );
      // Refresh character to get updated reference_image_path
      const chars = await refreshCharacters();
      const fresh = chars.find((c) => c.id === selectedCharacter.id);
      if (fresh) {
        setSelectedCharacter(fresh);
      }
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to upload reference image"
      );
    } finally {
      setPortraitLoading(false);
      setPortraitLoadingText("");
    }
  };

  const handleRemoveRefImage = async () => {
    if (!selectedCharacter) return;
    setPortraitLoading(true);
    setPortraitLoadingText("Removing...");
    try {
      await apiDelete(
        `/api/characters/${selectedCharacter.id}/reference-image`
      );
      const updated: LibraryCharacter = {
        ...selectedCharacter,
        reference_image_path: null,
      };
      setSelectedCharacter(updated);
      setCharacters((prev) =>
        prev.map((c) => (c.id === updated.id ? updated : c))
      );
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to remove reference image"
      );
    } finally {
      setPortraitLoading(false);
      setPortraitLoadingText("");
    }
  };

  // =========================================================================
  // Create character handlers
  // =========================================================================

  const openCreateModal = () => {
    setCreateName("");
    setCreateConcept("");
    setCreateRefFile(null);
    setCreateRefPreview(null);
    setShowCreate(true);
  };

  const handleCreateRefFileChange = (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = e.target.files?.[0] ?? null;
    setCreateRefFile(file);
    if (file) {
      setCreateRefPreview(URL.createObjectURL(file));
    } else {
      setCreateRefPreview(null);
    }
  };

  const handleCreateCharacter = async () => {
    if (!createConcept.trim()) return;
    setIsCreating(true);
    try {
      if (createRefFile) {
        const formData = new FormData();
        formData.append("concept", createConcept.trim());
        if (createName.trim()) formData.append("name", createName.trim());
        formData.append("reference_image", createRefFile);
        await apiPostForm("/api/characters/create", formData);
      } else {
        await apiPost("/api/characters/create", {
          concept: createConcept.trim(),
          ...(createName.trim() ? { name: createName.trim() } : {}),
        });
      }

      const chars = await refreshCharacters();
      setShowCreate(false);

      // Auto-select newest character
      if (chars.length > 0) {
        const newest = chars.reduce((a, b) =>
          a.exported_at > b.exported_at ? a : b
        );
        openDetail(newest);
      }
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to create character"
      );
    } finally {
      setIsCreating(false);
    }
  };

  // =========================================================================
  // Import from story handlers
  // =========================================================================

  const openImportModal = async () => {
    setShowImport(true);
    setSelectedImportIds(new Set());
    setExpandedGameId(null);
    setGameCharsMap(new Map());
    setIsLoadingGames(true);
    try {
      const result = await apiGet<GameSummary[]>("/api/games");
      setGames(result);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to load story saves"
      );
    } finally {
      setIsLoadingGames(false);
    }
  };

  const toggleGameExpansion = async (gameId: string) => {
    if (expandedGameId === gameId) {
      setExpandedGameId(null);
      return;
    }
    setExpandedGameId(gameId);

    // Lazy-load characters if not cached
    if (!gameCharsMap.has(gameId)) {
      setLoadingGameChars(true);
      try {
        const save = await apiGet<GameSave>(`/api/games/${gameId}`);
        // Convert GameSave characters to a lighter format for display
        const chars: LibraryCharacter[] = save.characters.map((c) => ({
          id: c.id,
          name: c.name,
          backstory: c.backstory,
          personality: c.personality,
          physical_description: c.physical_description,
          portrait_prompt: c.portrait_prompt ?? "",
          exported_at: save.updated_at,
          source: save.theme?.title ?? "",
          has_portrait: !!c.portrait_path,
        }));
        setGameCharsMap((prev) => new Map(prev).set(gameId, chars));
      } catch (err) {
        showError(
          err instanceof Error ? err.message : "Failed to load game characters"
        );
      } finally {
        setLoadingGameChars(false);
      }
    }
  };

  const toggleImportId = (charId: string) => {
    setSelectedImportIds((prev) => {
      const next = new Set(prev);
      if (next.has(charId)) next.delete(charId);
      else next.add(charId);
      return next;
    });
  };

  const handleImportSelected = async () => {
    if (!expandedGameId || selectedImportIds.size === 0) return;
    setIsImporting(true);
    try {
      const body: StoryImportRequest = {
        save_id: expandedGameId,
        character_ids: Array.from(selectedImportIds),
      };
      await apiPost("/api/characters/import-from-story", body);
      await refreshCharacters();
      setShowImport(false);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to import characters"
      );
    } finally {
      setIsImporting(false);
    }
  };

  // =========================================================================
  // Render
  // =========================================================================

  return (
    <GameLayout>
      <div className="flex-1 px-4 py-8 max-w-5xl mx-auto w-full">
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <h1 className="text-2xl font-bold text-gray-100">
            👤 Character Library
          </h1>
          <div className="flex items-center gap-3">
            <Button variant="secondary" size="sm" onClick={openCreateModal}>
              <Plus size={16} className="mr-1.5" />
              New Character
            </Button>
            <Button variant="secondary" size="sm" onClick={openImportModal}>
              <Download size={16} className="mr-1.5" />
              Import from Story
            </Button>
          </div>
        </div>

        {/* ---- Error banner ---- */}
        {error && (
          <div className="mb-4 px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/50 text-red-300 text-sm flex items-center gap-2">
            <AlertTriangle size={16} className="flex-shrink-0" />
            {error}
          </div>
        )}

        {/* ---- Loading ---- */}
        {isLoading && <Loading text="Loading characters..." />}

        {/* ---- Empty state ---- */}
        {!isLoading && characters.length === 0 && (
          <div className="text-center py-16 text-gray-500">
            <User size={48} className="mx-auto mb-4 opacity-30" />
            <p className="text-lg mb-2">No characters yet</p>
            <p className="text-sm mb-6">
              Create a new character or import from a story.
            </p>
            <div className="flex items-center justify-center gap-3">
              <Button variant="primary" size="sm" onClick={openCreateModal}>
                <Plus size={16} className="mr-1.5" />
                New Character
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={openImportModal}
              >
                <Download size={16} className="mr-1.5" />
                Import from Story
              </Button>
            </div>
          </div>
        )}

        {/* ---- Character grid ---- */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {characters.map((char) => (
            <Card key={char.id} onClick={() => openDetail(char)} neon>
              <div className="flex items-start gap-3">
                <div
                  className="w-12 h-12 rounded-lg border border-gray-700 flex items-center justify-center flex-shrink-0 overflow-hidden"
                  style={{ backgroundColor: "#828181" }}
                >
                  {char.has_portrait ? (
                    <img
                      src={`${API_BASE}/api/characters/${char.id}/portrait`}
                      alt={char.name}
                      className="w-full h-full object-contain"
                    />
                  ) : (
                    <User size={20} className="text-gray-500" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-cyan-400 font-semibold truncate">
                    {char.name}
                  </h3>
                  <p className="text-gray-400 text-xs mt-1 line-clamp-2">
                    {char.personality}
                  </p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>

      {/* ================================================================== */}
      {/* CHARACTER DETAIL MODAL                                             */}
      {/* ================================================================== */}
      <Modal
        open={!!selectedCharacter}
        onClose={closeDetail}
        title={selectedCharacter?.name ?? "Character"}
        maxWidth="max-w-5xl"
      >
        {selectedCharacter && (
          <div className="flex gap-8 max-h-[80vh] overflow-y-auto pr-2">
            {/* ---- Left column: Portrait + actions ---- */}
            <div className="flex-shrink-0 flex flex-col items-center gap-3">
              <div
                className="relative w-[280px] h-[280px] rounded-xl flex items-center justify-center overflow-hidden"
                style={{ backgroundColor: "#828181" }}
              >
                {selectedCharacter.has_portrait ? (
                  <img
                    key={portraitVersion}
                    src={`${API_BASE}/api/characters/${selectedCharacter.id}/portrait?v=${portraitVersion}`}
                    alt={selectedCharacter.name}
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <User size={64} className="text-gray-500" />
                )}
                {portraitLoading && (
                  <div className="absolute inset-0 bg-black/70 flex items-center justify-center rounded-lg">
                    <div className="flex flex-col items-center gap-2">
                      <div className="relative h-10 w-10">
                        <div className="absolute inset-0 rounded-full border-2 border-cyan-400/20" />
                        <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-cyan-400 animate-spin" />
                      </div>
                      <span className="text-xs text-cyan-300">
                        {portraitLoadingText || "Generating..."}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-2 w-[280px]">
                <Button
                  size="sm"
                  onClick={handleRegeneratePortrait}
                  disabled={portraitLoading}
                >
                  <RefreshCw size={14} className="mr-1.5" />
                  {portraitLoadingText === "Regenerating..."
                    ? "Regenerating..."
                    : "Regenerate Portrait"}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={openPortraitEdit}
                  disabled={portraitLoading}
                >
                  <Pencil size={14} className="mr-1.5" />
                  Edit Portrait
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={openRefImageModal}
                  disabled={portraitLoading}
                >
                  <ImagePlus size={14} className="mr-1.5" />
                  Set Reference Image
                </Button>
                {selectedCharacter.reference_image_path && (
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={handleRemoveRefImage}
                    disabled={portraitLoading}
                  >
                    <XCircle size={14} className="mr-1.5" />
                    Remove Reference
                  </Button>
                )}
              </div>
            </div>

            {/* ---- Right column: Editable fields ---- */}
            <div className="flex-1 min-w-0 space-y-4">
              {/* Name */}
              <div>
                <label className="text-xs text-gray-500 uppercase block mb-1">
                  Name
                </label>
                <input
                  type="text"
                  value={editForm.name}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, name: e.target.value }))
                  }
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50"
                />
              </div>

              {/* Personality */}
              <div>
                <label className="text-xs text-gray-500 uppercase block mb-1">
                  Personality
                </label>
                <textarea
                  value={editForm.personality}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, personality: e.target.value }))
                  }
                  rows={5}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 resize-y focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50"
                />
              </div>

              {/* Physical Description (with warning) */}
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <label className="text-xs text-gray-500 uppercase">
                    Physical Description
                  </label>
                  {editForm.physical_description !== originalPhysicalDesc && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] bg-amber-900/30 text-amber-400 rounded-full border border-amber-700/50">
                      <AlertTriangle size={10} />
                      Portrait may not match
                    </span>
                  )}
                </div>
                <textarea
                  value={editForm.physical_description}
                  onChange={(e) =>
                    setEditForm((f) => ({
                      ...f,
                      physical_description: e.target.value,
                    }))
                  }
                  rows={5}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 resize-y focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50"
                />
              </div>

              {/* Backstory */}
              <div>
                <label className="text-xs text-gray-500 uppercase block mb-1">
                  Backstory
                </label>
                <textarea
                  value={editForm.backstory}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, backstory: e.target.value }))
                  }
                  rows={6}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 resize-y focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50"
                />
              </div>

              {/* Actions */}
              <div className="flex items-center justify-between pt-3 border-t border-gray-800">
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => {
                    setDeleteTarget(selectedCharacter);
                  }}
                >
                  <Trash2 size={14} className="mr-1.5" />
                  Remove from Library
                </Button>
                <Button
                  size="sm"
                  onClick={handleSave}
                  disabled={isSaving}
                >
                  <Save size={14} className="mr-1.5" />
                  {isSaving ? "Saving..." : "Save Changes"}
                </Button>
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* ================================================================== */}
      {/* PORTRAIT EDIT SUB-MODAL                                            */}
      {/* ================================================================== */}
      <Modal
        open={showPortraitEdit}
        onClose={() => setShowPortraitEdit(false)}
        title="Edit Portrait"
      >
        {selectedCharacter && (
          <div className="space-y-4">
            {/* Current prompt */}
            <div>
              <label className="text-xs text-gray-500 uppercase block mb-1">
                Current Portrait Prompt
              </label>
              <p className="text-gray-400 text-xs bg-gray-800 rounded-lg p-3 max-h-24 overflow-y-auto">
                {selectedCharacter.portrait_prompt || "No prompt available"}
              </p>
            </div>

            {/* Mode toggle */}
            <div>
              <label className="text-xs text-gray-500 uppercase block mb-2">
                Mode
              </label>
              <div className="flex gap-2">
                <button
                  onClick={() => setPeMode("edit")}
                  className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    peMode === "edit"
                      ? "bg-cyan-600/20 border-cyan-500/50 text-cyan-400"
                      : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600"
                  }`}
                >
                  Edit Mode
                  <span className="block text-[10px] font-normal text-gray-500 mt-0.5">
                    Append instructions
                  </span>
                </button>
                <button
                  onClick={() => setPeMode("full")}
                  className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    peMode === "full"
                      ? "bg-cyan-600/20 border-cyan-500/50 text-cyan-400"
                      : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600"
                  }`}
                >
                  Full Prompt
                  <span className="block text-[10px] font-normal text-gray-500 mt-0.5">
                    Rewrite entirely
                  </span>
                </button>
              </div>
            </div>

            {/* Prompt text */}
            <div>
              <label className="text-xs text-gray-500 uppercase block mb-1">
                {peMode === "edit" ? "Edit Instructions" : "New Prompt"}
              </label>
              <textarea
                value={pePrompt}
                onChange={(e) => setPePrompt(e.target.value)}
                rows={4}
                placeholder={
                  peMode === "edit"
                    ? "e.g. Make the hair longer and darker..."
                    : "Write the full portrait generation prompt..."
                }
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 resize-none focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50"
              />
            </div>

            {/* Use current as ref checkbox */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={peUseRef}
                onChange={(e) => setPeUseRef(e.target.checked)}
                className="rounded border-gray-600 bg-gray-800 text-cyan-500 focus:ring-cyan-500/50"
              />
              <span className="text-sm text-gray-300">
                Use current image as reference
              </span>
            </label>

            {/* Actions */}
            <div className="flex justify-end gap-3 pt-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowPortraitEdit(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleSubmitPortraitEdit}
                disabled={!pePrompt.trim()}
              >
                Generate
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* ================================================================== */}
      {/* REFERENCE IMAGE SUB-MODAL                                          */}
      {/* ================================================================== */}
      <Modal
        open={showRefImage}
        onClose={() => setShowRefImage(false)}
        title="Set Reference Image"
      >
        {selectedCharacter && (
          <div className="space-y-4">
            {/* File input */}
            <div>
              <input
                ref={refFileInputRef}
                type="file"
                accept=".png,.jpg,.jpeg,.webp"
                onChange={handleRefFileChange}
                className="hidden"
              />
              <Button
                variant="secondary"
                size="sm"
                onClick={() => refFileInputRef.current?.click()}
              >
                <ImagePlus size={14} className="mr-1.5" />
                Choose File
              </Button>
              {refFile && (
                <span className="ml-3 text-sm text-gray-400">
                  {refFile.name}
                </span>
              )}
            </div>

            {/* Preview */}
            {refPreview && (
              <div
                className="w-32 h-32 rounded-lg border border-gray-700 flex items-center justify-center overflow-hidden"
                style={{ backgroundColor: "#828181" }}
              >
                <img
                  src={refPreview}
                  alt="Preview"
                  className="w-full h-full object-contain"
                />
              </div>
            )}

            {/* Mode selection */}
            <div>
              <label className="text-xs text-gray-500 uppercase block mb-2">
                Mode
              </label>
              <div className="flex gap-3">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="refMode"
                    checked={refMode === "use_as_is"}
                    onChange={() => setRefMode("use_as_is")}
                    className="text-cyan-500 focus:ring-cyan-500/50"
                  />
                  <span className="text-sm text-gray-300">Use as-is</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="refMode"
                    checked={refMode === "style_transfer"}
                    onChange={() => setRefMode("style_transfer")}
                    className="text-cyan-500 focus:ring-cyan-500/50"
                  />
                  <span className="text-sm text-gray-300">Style transfer</span>
                </label>
              </div>
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-3 pt-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowRefImage(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleUploadRefImage}
                disabled={!refFile}
              >
                Upload
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* ================================================================== */}
      {/* CREATE CHARACTER MODAL                                             */}
      {/* ================================================================== */}
      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="New Character"
        maxWidth="max-w-4xl"
      >
        <div className="space-y-4">
          {/* Name */}
          <div>
            <label className="text-xs text-gray-500 uppercase block mb-1">
              Name{" "}
              <span className="text-gray-600 normal-case">(optional)</span>
            </label>
            <input
              type="text"
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="e.g. Elara the Wanderer"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50"
            />
          </div>

          {/* Concept */}
          <div>
            <label className="text-xs text-gray-500 uppercase block mb-1">
              Concept{" "}
              <span className="text-red-400 normal-case">*</span>
            </label>
            <textarea
              value={createConcept}
              onChange={(e) => setCreateConcept(e.target.value)}
              rows={8}
              placeholder='e.g. "A brave knight who lost their memory"'
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 resize-y focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50"
            />
          </div>

          {/* Optional reference image */}
          <div>
            <label className="text-xs text-gray-500 uppercase block mb-1">
              Reference Image{" "}
              <span className="text-gray-600 normal-case">(optional)</span>
            </label>
            <input
              ref={createFileInputRef}
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              onChange={handleCreateRefFileChange}
              className="hidden"
            />
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => createFileInputRef.current?.click()}
              >
                <ImagePlus size={14} className="mr-1.5" />
                Choose File
              </Button>
              {createRefFile && (
                <span className="text-sm text-gray-400">
                  {createRefFile.name}
                </span>
              )}
            </div>
            {createRefPreview && (
              <div
                className="mt-2 w-24 h-24 rounded-lg border border-gray-700 flex items-center justify-center overflow-hidden"
                style={{ backgroundColor: "#828181" }}
              >
                <img
                  src={createRefPreview}
                  alt="Preview"
                  className="w-full h-full object-contain"
                />
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleCreateCharacter}
              disabled={!createConcept.trim() || isCreating}
            >
              {isCreating ? "Creating..." : "Create Character"}
            </Button>
          </div>
        </div>
      </Modal>

      {/* ================================================================== */}
      {/* IMPORT FROM STORY MODAL                                            */}
      {/* ================================================================== */}
      <Modal
        open={showImport}
        onClose={() => setShowImport(false)}
        title="Import from Story"
      >
        <div className="space-y-4">
          {isLoadingGames ? (
            <Loading text="Loading saves..." />
          ) : games.length === 0 ? (
            <p className="text-center py-8 text-gray-500">
              No story saves found.
            </p>
          ) : (
            <div className="max-h-[50vh] overflow-y-auto space-y-2 pr-1">
              {games.map((game) => {
                const isExpanded = expandedGameId === game.id;
                const gameChars = gameCharsMap.get(game.id);
                return (
                  <div
                    key={game.id}
                    className="border border-gray-700/50 rounded-lg overflow-hidden"
                  >
                    {/* Game header */}
                    <button
                      onClick={() => toggleGameExpansion(game.id)}
                      className="w-full flex items-center justify-between p-3 text-left hover:bg-gray-800/50 transition-colors"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        {isExpanded ? (
                          <ChevronDown
                            size={16}
                            className="text-gray-500 flex-shrink-0"
                          />
                        ) : (
                          <ChevronRight
                            size={16}
                            className="text-gray-500 flex-shrink-0"
                          />
                        )}
                        <span className="text-gray-200 font-medium truncate">
                          {game.title || `Save ${game.id.slice(0, 8)}...`}
                        </span>
                      </div>
                      <span className="text-gray-500 text-xs flex-shrink-0 ml-2">
                        {game.node_count} nodes
                      </span>
                    </button>

                    {/* Expanded: character list */}
                    {isExpanded && (
                      <div className="px-3 pb-3 pt-1 border-t border-gray-800">
                        {loadingGameChars && !gameChars ? (
                          <Loading text="Loading characters..." />
                        ) : gameChars && gameChars.length > 0 ? (
                          <div className="space-y-1">
                            {gameChars.map((char) => (
                              <label
                                key={char.id}
                                className="flex items-center gap-3 p-2 hover:bg-gray-800/30 rounded cursor-pointer"
                              >
                                <input
                                  type="checkbox"
                                  checked={selectedImportIds.has(char.id)}
                                  onChange={() => toggleImportId(char.id)}
                                  className="rounded border-gray-600 bg-gray-800 text-cyan-500 focus:ring-cyan-500/50"
                                />
                                <div className="min-w-0">
                                  <span className="text-gray-200 text-sm">
                                    {char.name}
                                  </span>
                                  <p className="text-gray-500 text-xs line-clamp-1">
                                    {char.personality}
                                  </p>
                                </div>
                              </label>
                            ))}
                          </div>
                        ) : (
                          <p className="text-gray-500 text-sm py-2 text-center">
                            No characters in this save.
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2 border-t border-gray-800">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setShowImport(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleImportSelected}
              disabled={selectedImportIds.size === 0 || isImporting}
            >
              {isImporting
                ? "Importing..."
                : `Import Selected (${selectedImportIds.size})`}
            </Button>
          </div>
        </div>
      </Modal>

      {/* ================================================================== */}
      {/* DELETE CONFIRMATION                                                */}
      {/* ================================================================== */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Remove Character"
        message={`Remove ${deleteTarget?.name ?? "this character"} from your library? This cannot be undone.`}
        confirmLabel="Remove"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </GameLayout>
  );
}
