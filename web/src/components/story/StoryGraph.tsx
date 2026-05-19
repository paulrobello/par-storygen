"use client";

import { useMemo, useState, useRef, useCallback } from "react";
import type { StoryNode } from "@/lib/api";
import { apiPost } from "@/lib/api";

export interface GraphEdge {
  parent_id: string;
  choice_text: string;
  child_id: string | null;
}

interface StoryGraphProps {
  edges: GraphEdge[];
  rootId: string;
  currentId: string;
  nodes: Record<string, StoryNode>;
  onNodeClick: (id: string) => void;
  onPrune?: (nodeId: string) => void;
  gameId?: string;
}

interface TreeNode {
  id: string;
  label: string;
  choiceText: string;
  x: number;
  y: number;
  isCurrent: boolean;
  isEnding: boolean;
  isRoot: boolean;
  isGhost: boolean; // unvisited choice — no real node yet
  children: TreeNode[];
}

const NODE_W = 160;
const NODE_H = 44;
const H_GAP = 100;
const V_GAP = 16;

/** Build a left-to-right tree from all choice edges, including ghosts for unvisited choices. */
function buildTree(
  edges: GraphEdge[],
  rootId: string,
  currentId: string,
  nodes: Record<string, StoryNode>,
): { tree: TreeNode; width: number; height: number } {
  // Build adjacency: parentId -> [{childId (or ghost id), choiceText, isGhost}]
  const childrenOf = new Map<string, { id: string; choice: string; ghost: boolean }[]>();
  for (const e of edges) {
    const list = childrenOf.get(e.parent_id) ?? [];
    if (e.child_id) {
      list.push({ id: e.child_id, choice: e.choice_text, ghost: false });
    } else {
      // Unvisited choice — create a ghost identifier
      list.push({ id: `__ghost_${e.parent_id}_${e.choice_text}`, choice: e.choice_text, ghost: true });
    }
    childrenOf.set(e.parent_id, list);
  }

  // Count leaves for column width
  let nextY = 0;
  const positions = new Map<string, { x: number; y: number }>();

  function assign(id: string, depth: number): void {
    const kids = childrenOf.get(id) ?? [];
    if (kids.length === 0) {
      // Leaf
      positions.set(id, { x: depth, y: nextY });
      nextY += 1;
      return;
    }
    // Assign children first
    for (const k of kids) {
      assign(k.id, depth + 1);
    }
    // Center parent vertically among children
    const firstY = positions.get(kids[0].id)!.y;
    const lastY = positions.get(kids[kids.length - 1].id)!.y;
    positions.set(id, { x: depth, y: (firstY + lastY) / 2 });
  }
  assign(rootId, 0);

  // Build tree structure
  function buildNode(id: string, choiceText: string): TreeNode {
    const isGhost = id.startsWith("__ghost_");
    const node = isGhost ? null : nodes[id];
    const pos = positions.get(id) ?? { x: 0, y: 0 };
    const kids = childrenOf.get(id) ?? [];

    return {
      id,
      label: isGhost
        ? choiceText.slice(0, 20)
        : node?.narration?.slice(0, 28) ?? id.slice(0, 8),
      choiceText,
      x: pos.x * (NODE_W + H_GAP),
      y: pos.y * (NODE_H + V_GAP),
      isCurrent: id === currentId,
      isEnding: node?.is_ending ?? false,
      isRoot: id === rootId,
      isGhost,
      children: kids.map((k) => buildNode(k.id, k.choice)),
    };
  }

  const tree = buildNode(rootId, "");

  const allNodes: TreeNode[] = [];
  function flatten(n: TreeNode) {
    allNodes.push(n);
    for (const c of n.children) flatten(c);
  }
  flatten(tree);

  const maxX = Math.max(...allNodes.map((n) => n.x));
  const maxY = Math.max(...allNodes.map((n) => n.y));

  return {
    tree,
    width: maxX + NODE_W + 40,
    height: maxY + NODE_H + 40,
  };
}

function TreeNodeBox({
  node,
  onClick,
  onPrune,
  canPrune,
}: {
  node: TreeNode;
  onClick: () => void;
  onPrune?: (nodeId: string) => void;
  canPrune: boolean;
}) {
  const W = NODE_W;
  const H = NODE_H;
  const x = node.x;
  const y = node.y;
  const [hovered, setHovered] = useState(false);

  let fill = "#1e293b";
  let stroke = "#334155";
  let textColor = "#e2e8f0";
  let strokeDasharray = "";

  if (node.isGhost) {
    fill = "#111827";
    stroke = "#4b5563";
    textColor = "#6b7280";
    strokeDasharray = "4 3";
  } else if (node.isCurrent) {
    fill = "#0e3a4a";
    stroke = "#06b6d4";
  } else if (node.isEnding) {
    fill = "#3b1f0b";
    stroke = "#f59e0b";
  } else if (node.isRoot) {
    fill = "#1a1a2e";
    stroke = "#6366f1";
  }

  const showPruneBtn = canPrune && onPrune && !node.isGhost && !node.isRoot && !node.isCurrent && hovered;

  return (
    <g
      onClick={node.isGhost ? undefined : onClick}
      className={node.isGhost ? "" : "cursor-pointer"}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <rect
        x={x}
        y={y - H / 2}
        width={W}
        height={H}
        rx={10}
        fill={fill}
        stroke={stroke}
        strokeWidth={node.isCurrent ? 2 : 1}
        strokeDasharray={strokeDasharray || undefined}
      />
      {node.isCurrent && (
        <circle cx={x + 10} cy={y} r={3} fill="#06b6d4" />
      )}
      {node.isEnding && (
        <text x={x + W - 10} y={y - H / 2 + 14} fontSize={9} fill="#f59e0b" textAnchor="end">
          END
        </text>
      )}
      <text
        x={x + W / 2}
        y={y + 4}
        textAnchor="middle"
        fontSize={11}
        fill={textColor}
        className="pointer-events-none select-none"
      >
        {node.label.length > 20 ? node.label.slice(0, 18) + "…" : node.label}
      </text>
      {/* Prune button on hover */}
      {showPruneBtn && (
        <g
          onClick={(e) => {
            e.stopPropagation();
            onPrune(node.id);
          }}
          className="cursor-pointer"
        >
          <rect
            x={x + W - 2}
            y={y - H / 2 - 2}
            width={18}
            height={18}
            rx={4}
            fill="#7f1d1d"
            stroke="#ef4444"
            strokeWidth={1}
          />
          <text
            x={x + W + 7}
            y={y - H / 2 + 12}
            textAnchor="middle"
            fontSize={11}
            fill="#fca5a5"
            className="pointer-events-none select-none"
          >
            &times;
          </text>
        </g>
      )}
    </g>
  );
}

function TreeEdge({ parent, child }: { parent: TreeNode; child: TreeNode }) {
  const x1 = parent.x + NODE_W;
  const y1 = parent.y;
  const x2 = child.x;
  const y2 = child.y;
  const midX = (x1 + x2) / 2;

  const isActive = child.isCurrent;
  const isGhost = child.isGhost;

  return (
    <g>
      <path
        d={`M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`}
        fill="none"
        stroke={isActive ? "#06b6d4" : isGhost ? "#374151" : "#334155"}
        strokeWidth={isActive ? 2 : 1}
        strokeDasharray={isGhost ? "4 3" : undefined}
        opacity={isGhost ? 0.5 : 1}
      />
      {/* Choice label */}
      <text
        x={midX}
        y={(y1 + y2) / 2 - 6}
        textAnchor="middle"
        fontSize={9}
        fill={isActive ? "#06b6d4" : isGhost ? "#4b5563" : "#64748b"}
        className="pointer-events-none select-none"
      >
        {child.choiceText.length > 16 ? child.choiceText.slice(0, 14) + "…" : child.choiceText}
      </text>
    </g>
  );
}

function renderTree(
  node: TreeNode,
  onNodeClick: (id: string) => void,
  onPrune?: (nodeId: string) => void,
): React.ReactNode[] {
  const elements: React.ReactNode[] = [];

  for (const child of node.children) {
    elements.push(<TreeEdge key={`e-${node.id}-${child.id}`} parent={node} child={child} />);
  }
  elements.push(
    <TreeNodeBox
      key={`n-${node.id}`}
      node={node}
      onClick={() => onNodeClick(node.id)}
      onPrune={onPrune}
      canPrune
    />,
  );
  for (const child of node.children) {
    elements.push(...renderTree(child, onNodeClick, onPrune));
  }

  return elements;
}

export function StoryGraph({
  edges,
  rootId,
  currentId,
  nodes,
  onNodeClick,
  onPrune,
  gameId,
}: StoryGraphProps) {
  const { tree } = useMemo(
    () => buildTree(edges, rootId, currentId, nodes),
    [edges, rootId, currentId, nodes],
  );

  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragging = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });

  // Prune confirmation state
  const [pruneTarget, setPruneTarget] = useState<string | null>(null);
  const [pruning, setPruning] = useState(false);

  const handlePruneRequest = useCallback((nodeId: string) => {
    setPruneTarget(nodeId);
  }, []);

  const handlePruneConfirm = useCallback(async () => {
    if (!pruneTarget || !gameId) return;
    setPruning(true);
    try {
      await apiPost<{ removed_count: number }>(`/api/games/${gameId}/prune`, {
        node_id: pruneTarget,
      });
      setPruneTarget(null);
      onPrune?.(pruneTarget);
    } catch {
      // Silently close on error; parent can show toast
      setPruneTarget(null);
    } finally {
      setPruning(false);
    }
  }, [pruneTarget, gameId, onPrune]);

  const onPointerDown = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    dragging.current = true;
    lastPos.current = { x: e.clientX, y: e.clientY };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    if (!dragging.current) return;
    const dx = e.clientX - lastPos.current.x;
    const dy = e.clientY - lastPos.current.y;
    lastPos.current = { x: e.clientX, y: e.clientY };
    setOffset((o) => ({ x: o.x + dx, y: o.y + dy }));
  }, []);

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  return (
    <>
      <svg
        width="100%"
        height="100%"
        className="cursor-grab active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <g transform={`translate(${offset.x}, ${offset.y})`}>
          {renderTree(tree, onNodeClick, onPrune ? handlePruneRequest : undefined)}
        </g>
      </svg>

      {/* Prune confirmation dialog */}
      {pruneTarget && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60">
          <div className="bg-gray-900 border border-gray-700/60 rounded-xl shadow-2xl max-w-sm w-full p-6 text-gray-100">
            <h3 className="text-lg font-semibold text-gray-100 mb-2">Prune Branch</h3>
            <p className="text-gray-400 text-sm mb-1">
              Prune this branch and all its descendants?
            </p>
            <p className="text-amber-400/80 text-xs mb-5">
              This cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setPruneTarget(null)}
                disabled={pruning}
                className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handlePruneConfirm}
                disabled={pruning}
                className="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors disabled:opacity-50"
              >
                {pruning ? "Pruning…" : "Prune"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
