"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { ImagePlus } from "lucide-react";
import type { LibraryCharacter } from "@/lib/api";
import type { CharacterActions } from "@/hooks/useCharacterActions";

interface CreateCharacterModalProps {
  onClose: () => void;
  /** Called with the newest character after a successful create (or null). */
  onCreated: (newest: LibraryCharacter | null) => void;
  actions: CharacterActions;
}

/**
 * "New Character" modal. Mounted only while open, so the name/concept/
 * reference-image form starts empty each time. The API call is delegated to
 * the shared character-actions hook.
 */
export function CreateCharacterModal({
  onClose,
  onCreated,
  actions,
}: CreateCharacterModalProps) {
  const [createName, setCreateName] = useState("");
  const [createConcept, setCreateConcept] = useState("");
  const [createRefFile, setCreateRefFile] = useState<File | null>(null);
  const [createRefPreview, setCreateRefPreview] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const createFileInputRef = useRef<HTMLInputElement>(null);

  const handleRefFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setCreateRefFile(file);
    if (file) {
      setCreateRefPreview(URL.createObjectURL(file));
    } else {
      setCreateRefPreview(null);
    }
  };

  const handleCreate = async () => {
    if (!createConcept.trim()) return;
    setIsCreating(true);
    try {
      const chars = await actions.createCharacter({
        name: createName,
        concept: createConcept,
        referenceImage: createRefFile,
      });
      onClose();
      // Auto-select the newest character (matches prior behavior).
      const newest =
        chars.length > 0
          ? chars.reduce((a, b) => (a.exported_at > b.exported_at ? a : b))
          : null;
      onCreated(newest);
    } catch (err) {
      actions.showError(
        err instanceof Error ? err.message : "Failed to create character"
      );
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="New Character" maxWidth="max-w-4xl">
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
            Concept <span className="text-red-400 normal-case">*</span>
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
            onChange={handleRefFileChange}
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
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleCreate}
            disabled={!createConcept.trim() || isCreating}
          >
            {isCreating ? "Creating..." : "Create Character"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
