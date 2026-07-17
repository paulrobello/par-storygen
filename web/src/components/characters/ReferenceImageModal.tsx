"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { ImagePlus } from "lucide-react";
import type { LibraryCharacter } from "@/lib/api";
import type { ReferenceImageMode } from "@/hooks/useCharacterActions";

interface ReferenceImageModalProps {
  onClose: () => void;
  character: LibraryCharacter | null;
  /** Invoked with the chosen file + mode; the parent owns loading state. */
  onSubmit: (file: File, mode: ReferenceImageMode) => void;
}

/**
 * Reference-image upload sub-modal rendered above the character detail modal.
 * Mounted only while open, so file/preview/mode state starts at its default
 * each time. The upload + loading overlay are delegated to the parent via
 * `onSubmit`.
 */
export function ReferenceImageModal({
  onClose,
  character,
  onSubmit,
}: ReferenceImageModalProps) {
  const [refFile, setRefFile] = useState<File | null>(null);
  const [refPreview, setRefPreview] = useState<string | null>(null);
  const [refMode, setRefMode] = useState<ReferenceImageMode>("use_as_is");
  const refFileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setRefFile(file);
    if (file) {
      setRefPreview(URL.createObjectURL(file));
    } else {
      setRefPreview(null);
    }
  };

  return (
    <Modal open onClose={onClose} title="Set Reference Image">
      {character && (
        <div className="space-y-4">
          {/* File input */}
          <div>
            <input
              ref={refFileInputRef}
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              onChange={handleFileChange}
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
              <span className="ml-3 text-sm text-gray-400">{refFile.name}</span>
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
            <Button variant="secondary" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => refFile && onSubmit(refFile, refMode)}
              disabled={!refFile}
            >
              Upload
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
