"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import type { LibraryCharacter, PortraitEditRequest } from "@/lib/api";

interface PortraitEditModalProps {
  onClose: () => void;
  character: LibraryCharacter | null;
  /** Invoked with the edit payload; the parent owns loading state. */
  onSubmit: (body: PortraitEditRequest) => void;
}

/**
 * Portrait-edit sub-modal rendered above the character detail modal. Mounted
 * only while open, so prompt/mode/reference state starts at its default each
 * time. The actual API call + loading overlay are delegated to the parent via
 * `onSubmit`.
 */
export function PortraitEditModal({
  onClose,
  character,
  onSubmit,
}: PortraitEditModalProps) {
  const [pePrompt, setPePrompt] = useState("");
  const [peMode, setPeMode] = useState<"edit" | "full">("edit");
  const [peUseRef, setPeUseRef] = useState(false);

  return (
    <Modal open onClose={onClose} title="Edit Portrait">
      {character && (
        <div className="space-y-4">
          {/* Current prompt */}
          <div>
            <label className="text-xs text-gray-500 uppercase block mb-1">
              Current Portrait Prompt
            </label>
            <p className="text-gray-400 text-xs bg-gray-800 rounded-lg p-3 max-h-24 overflow-y-auto">
              {character.portrait_prompt || "No prompt available"}
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
            <Button variant="secondary" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() =>
                onSubmit({
                  prompt: pePrompt.trim(),
                  mode: peMode,
                  use_current_as_ref: peUseRef,
                })
              }
              disabled={!pePrompt.trim()}
            >
              Generate
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
