"use client";

import { useCallback, useState } from "react";
import { GameLayout } from "@/components/layout/GameLayout";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { CharacterDetailModal } from "@/components/characters/CharacterDetailModal";
import { CreateCharacterModal } from "@/components/characters/CreateCharacterModal";
import { ImportFromStoryModal } from "@/components/characters/ImportFromStoryModal";
import { useCharacterActions } from "@/hooks/useCharacterActions";
import type { LibraryCharacter } from "@/lib/api";
import { API_BASE } from "@/lib/config";
import { Download, Plus, User, AlertTriangle } from "lucide-react";

export default function CharactersPage() {
  const actions = useCharacterActions();
  const { characters, isLoading, error } = actions;

  // Page-level (routing) state: which character is open, which modal is up,
  // and the pending delete confirmation. All detail/form state lives in the
  // composed modals, which are conditionally mounted so each open starts fresh.
  const [selectedCharacter, setSelectedCharacter] =
    useState<LibraryCharacter | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<LibraryCharacter | null>(
    null
  );

  const openDetail = useCallback((char: LibraryCharacter) => {
    setSelectedCharacter(char);
  }, []);

  const closeDetail = useCallback(() => {
    setSelectedCharacter(null);
  }, []);

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    try {
      await actions.deleteCharacter(deleteTarget);
      if (selectedCharacter?.id === deleteTarget.id) closeDetail();
    } catch (err) {
      actions.showError(
        err instanceof Error ? err.message : "Failed to delete"
      );
    } finally {
      setDeleteTarget(null);
    }
  };

  return (
    <GameLayout>
      <div className="flex-1 px-4 py-8 max-w-5xl mx-auto w-full">
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <h1 className="text-2xl font-bold text-gray-100">
            👤 Character Library
          </h1>
          <div className="flex items-center gap-3">
            <Button variant="secondary" size="sm" onClick={() => setShowCreate(true)}>
              <Plus size={16} className="mr-1.5" />
              New Character
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setShowImport(true)}>
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
              <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
                <Plus size={16} className="mr-1.5" />
                New Character
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowImport(true)}
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
      {/* CHARACTER DETAIL (with portrait-edit + reference-image sub-modals) */}
      {/* Keyed on id so switching characters mounts a fresh, reset instance. */}
      {/* ================================================================== */}
      {selectedCharacter && (
        <CharacterDetailModal
          key={selectedCharacter.id}
          character={selectedCharacter}
          onClose={closeDetail}
          onCharacterChange={setSelectedCharacter}
          onRequestDelete={setDeleteTarget}
          actions={actions}
        />
      )}

      {/* ================================================================== */}
      {/* CREATE CHARACTER (mounted only while open)                         */}
      {/* ================================================================== */}
      {showCreate && (
        <CreateCharacterModal
          onClose={() => setShowCreate(false)}
          onCreated={(newest) => {
            if (newest) openDetail(newest);
          }}
          actions={actions}
        />
      )}

      {/* ================================================================== */}
      {/* IMPORT FROM STORY (mounted only while open)                        */}
      {/* ================================================================== */}
      {showImport && (
        <ImportFromStoryModal
          onClose={() => setShowImport(false)}
          onImported={() => {}}
          actions={actions}
        />
      )}

      {/* ================================================================== */}
      {/* DELETE CONFIRMATION                                                */}
      {/* ================================================================== */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Remove Character"
        message={`Remove ${deleteTarget?.name ?? "this character"} from your library? This cannot be undone.`}
        confirmLabel="Remove"
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
      />
    </GameLayout>
  );
}
