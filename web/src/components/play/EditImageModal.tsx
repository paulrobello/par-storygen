"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. The scene-image
// edit-prompt modal. Pure controlled component — prompt state is owned by
// the useSceneImage hook and threaded through.
import { Modal } from "@/components/ui/Modal";

export function EditImageModal({
  open,
  onClose,
  prompt,
  onPromptChange,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  prompt: string;
  onPromptChange: (p: string) => void;
  onSubmit: () => Promise<void>;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Edit Image Prompt">
      <textarea
        value={prompt}
        onChange={(e) => onPromptChange(e.target.value)}
        rows={6}
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
          className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors"
        >
          Regenerate
        </button>
      </div>
    </Modal>
  );
}
