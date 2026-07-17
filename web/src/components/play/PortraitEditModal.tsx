"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. The portrait edit-prompt
// modal, opened from inside PortraitsModal. Controlled — prompt state is
// owned by the parent (PortraitsModal) so it can pre-fill from the
// character's portrait_prompt / physical_description.
import { Modal } from "@/components/ui/Modal";

export function PortraitEditModal({
  open,
  onClose,
  prompt,
  onPromptChange,
  onSubmit,
  loading,
}: {
  open: boolean;
  onClose: () => void;
  prompt: string;
  onPromptChange: (p: string) => void;
  onSubmit: () => Promise<void>;
  loading: boolean;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Edit Portrait Prompt">
      <textarea
        value={prompt}
        onChange={(e) => onPromptChange(e.target.value)}
        rows={5}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm text-gray-200 resize-none focus:outline-none focus:border-cyan-500"
      />
      <div className="flex justify-end gap-3 mt-4">
        <button
          onClick={onClose}
          className="px-4 py-2 text-gray-400 hover:text-gray-200 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={onSubmit}
          disabled={loading || !prompt.trim()}
          className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center gap-2"
        >
          {loading && (
            <span className="inline-block w-3 h-3 rounded-full bg-white animate-pulse" />
          )}
          Regenerate
        </button>
      </div>
    </Modal>
  );
}
