"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. The "Previously on..."
// recap modal. Pure presentational — recap text + read-aloud (TTS) + close.
import ReactMarkdown from "react-markdown";
import { Modal } from "@/components/ui/Modal";

export function RecapModal({
  open,
  onClose,
  recapText,
  onReadAloud,
  ttsLoading,
}: {
  open: boolean;
  onClose: () => void;
  recapText: string;
  onReadAloud: () => Promise<void>;
  ttsLoading: boolean;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Previously on...">
      <div className="max-h-[60vh] overflow-y-auto">
        <div className="prose-story text-gray-200 leading-relaxed">
          <ReactMarkdown>{recapText}</ReactMarkdown>
        </div>
      </div>
      <div className="flex justify-end gap-3 mt-4">
        <button
          onClick={onReadAloud}
          disabled={ttsLoading || !recapText}
          className="flex items-center gap-2 px-4 py-2 text-sm text-cyan-400 border border-cyan-400/50 hover:bg-cyan-400/10 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {ttsLoading ? (
            <span className="inline-block w-3 h-3 rounded-full bg-cyan-400 animate-pulse" />
          ) : (
            <span>Read Aloud</span>
          )}
        </button>
        <button
          onClick={onClose}
          className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg border border-gray-600/50 transition-colors"
        >
          Close
        </button>
      </div>
    </Modal>
  );
}
