"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Full-screen replay
// viewer with arrow-key / space navigation (handled by useReplay). Image is
// built via the shared sceneImageUrl helper (QA-013 fold) so it returns null
// unless the node's image_status is "done" — no more speculative 404s on
// nodes with image_path but no committed image.
import { Film } from "lucide-react";
import { sceneImageUrl } from "@/lib/api";
import type { StoryNode } from "@/lib/api";
import { useGameStore } from "@/stores/game-store";

export function ReplayModal({
  open,
  onClose,
  gameId,
  nodes,
  index,
  setIndex,
}: {
  open: boolean;
  onClose: () => void;
  gameId: string;
  nodes: StoryNode[];
  index: number;
  setIndex: React.Dispatch<React.SetStateAction<number>>;
}) {
  if (!open || nodes.length === 0) return null;

  const node = nodes[index];
  const sceneUrl = sceneImageUrl(gameId, node);

  return (
    <div className="fixed inset-0 z-50 bg-gray-950 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-3">
          <Film size={16} className="text-cyan-400" />
          <h2 className="text-sm font-medium text-gray-300">Replay</h2>
          <span className="text-xs text-gray-500">
            Beat {index + 1} of {nodes.length}
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
        >
          ✕
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto flex flex-col items-center justify-center p-6 gap-6">
        <div className="max-w-2xl w-full">
          <p className="text-gray-200 leading-relaxed whitespace-pre-wrap text-sm">
            {node.narration}
          </p>
        </div>
        {sceneUrl && (
          <div className="max-w-lg w-full">
            <img
              src={sceneUrl}
              alt="Scene illustration"
              className="w-full rounded-lg border border-gray-700"
            />
          </div>
        )}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-center gap-4 px-4 py-3 border-t border-gray-800">
        <button
          onClick={() => setIndex((i) => Math.max(i - 1, 0))}
          disabled={index === 0}
          className="px-4 py-2 text-sm text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg border border-gray-700/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          Previous
        </button>
        <button
          onClick={() => {
            const target = nodes[index];
            onClose();
            useGameStore.getState().jumpToNode(target.id);
          }}
          className="px-4 py-2 text-sm text-cyan-400 border border-cyan-400/50 hover:bg-cyan-400/10 rounded-lg transition-colors"
        >
          Jump to Live
        </button>
        <button
          onClick={() => setIndex((i) => Math.min(i + 1, nodes.length - 1))}
          disabled={index === nodes.length - 1}
          className="px-4 py-2 text-sm text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg border border-gray-700/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          Next
        </button>
      </div>
    </div>
  );
}
