"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { PortraitEditModal } from "./PortraitEditModal";
import { ReferenceImageModal } from "./ReferenceImageModal";
import {
  AlertTriangle,
  Pencil,
  RefreshCw,
  Save,
  Trash2,
  User,
  XCircle,
  ImagePlus,
} from "lucide-react";
import { API_BASE } from "@/lib/config";
import type { LibraryCharacter, PortraitEditRequest } from "@/lib/api";
import type {
  CharacterActions,
  CharacterEditForm,
  ReferenceImageMode,
} from "@/hooks/useCharacterActions";

interface CharacterDetailModalProps {
  character: LibraryCharacter | null;
  onClose: () => void;
  /** Sync the shell's selected character after any mutation. */
  onCharacterChange: (updated: LibraryCharacter) => void;
  /** Request the shell to show the delete confirmation for this character. */
  onRequestDelete: (char: LibraryCharacter) => void;
  actions: CharacterActions;
}

/**
 * Character detail / edit modal. The shell mounts this keyed on the selected
 * character's id, so the edit form and sub-modal flags reset on each open /
 * character switch via lazy state initializers (no reset effects needed).
 *
 * Owns the edit form, the shared portrait-loading overlay, and the portrait-
 * edit + reference-image sub-modals. All list mutations flow through the
 * shared character-actions hook; `onCharacterChange` keeps the shell's
 * selected-character state in sync so the portrait re-renders.
 */
export function CharacterDetailModal({
  character,
  onClose,
  onCharacterChange,
  onRequestDelete,
  actions,
}: CharacterDetailModalProps) {
  const [editForm, setEditForm] = useState<CharacterEditForm>(() =>
    character
      ? {
          name: character.name,
          personality: character.personality,
          physical_description: character.physical_description,
          backstory: character.backstory,
        }
      : { name: "", personality: "", physical_description: "", backstory: "" }
  );
  const [originalPhysicalDesc, setOriginalPhysicalDesc] = useState(
    () => character?.physical_description ?? ""
  );
  const [isSaving, setIsSaving] = useState(false);

  // Portrait loading overlay state (shared across regen / edit / upload / remove).
  const [portraitLoading, setPortraitLoading] = useState(false);
  const [portraitLoadingText, setPortraitLoadingText] = useState("");
  const [portraitVersion, setPortraitVersion] = useState(0);

  // Sub-modal open flags; the sub-modals are mounted only while open.
  const [showPortraitEdit, setShowPortraitEdit] = useState(false);
  const [showRefImage, setShowRefImage] = useState(false);

  const showError = actions.showError;

  const handleSave = async () => {
    if (!character) return;
    setIsSaving(true);
    try {
      const updated = await actions.saveCharacter(character, editForm);
      onCharacterChange(updated);
      setOriginalPhysicalDesc(editForm.physical_description);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setIsSaving(false);
    }
  };

  const handleRegeneratePortrait = async () => {
    if (!character) return;
    setPortraitLoading(true);
    setPortraitLoadingText("Regenerating...");
    try {
      const updated = await actions.regeneratePortrait(character);
      setPortraitVersion((v) => v + 1);
      onCharacterChange(updated);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to regenerate portrait"
      );
    } finally {
      setPortraitLoading(false);
      setPortraitLoadingText("");
    }
  };

  const handleSubmitPortraitEdit = async (body: PortraitEditRequest) => {
    if (!character) return;
    setShowPortraitEdit(false);
    setPortraitLoading(true);
    setPortraitLoadingText("Generating...");
    try {
      const updated = await actions.editPortrait(character, body);
      setPortraitVersion((v) => v + 1);
      onCharacterChange(updated);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to edit portrait"
      );
    } finally {
      setPortraitLoading(false);
      setPortraitLoadingText("");
    }
  };

  const handleUploadRefImage = async (
    file: File,
    mode: ReferenceImageMode
  ) => {
    if (!character) return;
    setShowRefImage(false);
    setPortraitLoading(true);
    setPortraitLoadingText("Uploading...");
    try {
      const fresh = await actions.uploadReferenceImage(character, file, mode);
      if (fresh) onCharacterChange(fresh);
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
    if (!character) return;
    setPortraitLoading(true);
    setPortraitLoadingText("Removing...");
    try {
      const updated = await actions.removeReferenceImage(character);
      onCharacterChange(updated);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to remove reference image"
      );
    } finally {
      setPortraitLoading(false);
      setPortraitLoadingText("");
    }
  };

  return (
    <>
      <Modal
        open={!!character}
        onClose={onClose}
        title={character?.name ?? "Character"}
        maxWidth="max-w-5xl"
      >
        {character && (
          <div className="flex gap-8 max-h-[80vh] overflow-y-auto pr-2">
            {/* ---- Left column: Portrait + actions ---- */}
            <div className="flex-shrink-0 flex flex-col items-center gap-3">
              <div
                className="relative w-[280px] h-[280px] rounded-xl flex items-center justify-center overflow-hidden"
                style={{ backgroundColor: "#828181" }}
              >
                {character.has_portrait ? (
                  <img
                    key={portraitVersion}
                    src={`${API_BASE}/api/characters/${character.id}/portrait?v=${portraitVersion}`}
                    alt={character.name}
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
                  onClick={() => setShowPortraitEdit(true)}
                  disabled={portraitLoading}
                >
                  <Pencil size={14} className="mr-1.5" />
                  Edit Portrait
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setShowRefImage(true)}
                  disabled={portraitLoading}
                >
                  <ImagePlus size={14} className="mr-1.5" />
                  Set Reference Image
                </Button>
                {character.reference_image_path && (
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
                  onClick={() => onRequestDelete(character)}
                >
                  <Trash2 size={14} className="mr-1.5" />
                  Remove from Library
                </Button>
                <Button size="sm" onClick={handleSave} disabled={isSaving}>
                  <Save size={14} className="mr-1.5" />
                  {isSaving ? "Saving..." : "Save Changes"}
                </Button>
              </div>
            </div>
          </div>
        )}
      </Modal>

      {showPortraitEdit && (
        <PortraitEditModal
          character={character}
          onClose={() => setShowPortraitEdit(false)}
          onSubmit={handleSubmitPortraitEdit}
        />
      )}

      {showRefImage && (
        <ReferenceImageModal
          character={character}
          onClose={() => setShowRefImage(false)}
          onSubmit={handleUploadRefImage}
        />
      )}
    </>
  );
}
