"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Full-screen graph overlay
// (not a Modal — covers the viewport). Renders the StoryGraph and forwards
// node clicks + prune to the parent.
import { StoryGraph } from "@/components/story/StoryGraph";
import type { StoryNode } from "@/lib/api";
import type { GraphEdge } from "@/hooks/useGameViews";

export function StoryGraphModal({
  open,
  onClose,
  edges,
  gameId,
  rootId,
  currentId,
  nodes,
  onPrune,
  onNodeClick,
}: {
  open: boolean;
  onClose: () => void;
  edges: GraphEdge[];
  gameId: string;
  rootId: string;
  currentId: string;
  nodes: Record<string, StoryNode>;
  onPrune: () => Promise<void>;
  onNodeClick: (id: string) => void;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 bg-gray-950 flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-medium text-gray-300">Story Graph</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">{edges.length} edges</span>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
          >
            ✕
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-auto p-6">
        {edges.length === 0 ? (
          <p className="text-gray-500 text-sm">No edges found.</p>
        ) : (
          <StoryGraph
            edges={edges}
            rootId={rootId}
            currentId={currentId}
            nodes={nodes}
            onNodeClick={onNodeClick}
            onPrune={onPrune}
            gameId={gameId}
          />
        )}
      </div>
    </div>
  );
}
