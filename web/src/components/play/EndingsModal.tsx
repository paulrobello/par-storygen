"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Lists ending node ids
// with a narration preview; clicking jumps to that ending.
import { Modal } from "@/components/ui/Modal";
import type { StoryNode } from "@/lib/api";

export function EndingsModal({
  open,
  onClose,
  endingsList,
  nodes,
  onJumpTo,
}: {
  open: boolean;
  onClose: () => void;
  endingsList: string[];
  nodes: Record<string, StoryNode>;
  onJumpTo: (nodeId: string) => void;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Endings Reached">
      <div className="max-h-[60vh] overflow-y-auto space-y-2">
        {endingsList.length === 0 ? (
          <p className="text-gray-500 text-sm">No endings reached yet.</p>
        ) : (
          endingsList.map((nodeId) => {
            const node = nodes[nodeId];
            return (
              <button
                key={nodeId}
                onClick={() => onJumpTo(nodeId)}
                className="w-full text-left p-3 rounded-lg bg-gray-800/40 hover:bg-gray-800/70 border border-gray-700/50 transition-colors"
              >
                <p className="text-xs text-gray-500 font-mono mb-1">{nodeId.slice(0, 8)}</p>
                <p className="text-sm text-gray-300 line-clamp-2">
                  {node?.narration?.slice(0, 120) ?? "Unknown node"}…
                </p>
              </button>
            );
          })
        )}
      </div>
    </Modal>
  );
}
