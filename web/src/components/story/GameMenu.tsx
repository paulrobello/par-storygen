"use client";

import { useState } from "react";
import {
  Menu,
  X,
  RotateCcw,
  Image as ImageIcon,
  GitBranch,
  Flag,
  ArrowLeft,
  Volume2,
  Pencil,
  Eye,
  Download,
  Film,
  Users,
  BookOpen,
  FastForward,
} from "lucide-react";
import type { StoryNode } from "@/lib/api";

interface GameMenuProps {
  currentNode: StoryNode;
  isStreaming: boolean;
  autoPlay: boolean;
  onToggleAutoPlay: () => void;
  onRetryImage: () => void;
  onEditImage: () => void;
  onRegenerateNode: () => void;
  onGoBack: () => void;
  onViewGraph: () => void;
  onViewEndings: () => void;
  onViewPortraits: () => void;
  onReadAloud: () => void;
  onExportBook: () => void;
  onViewReplay: () => void;
  onViewRelationships: () => void;
  onViewRecap: () => void;
}

export function GameMenu({
  currentNode,
  isStreaming,
  autoPlay,
  onToggleAutoPlay,
  onRetryImage,
  onEditImage,
  onRegenerateNode,
  onGoBack,
  onViewGraph,
  onViewEndings,
  onViewPortraits,
  onReadAloud,
  onExportBook,
  onViewReplay,
  onViewRelationships,
  onViewRecap,
}: GameMenuProps) {
  const [open, setOpen] = useState(false);

  const canGoBack = !!currentNode.parent_id;
  const hasDescendants = (currentNode.choices ?? []).some((c) => !!c.child_node_id);
  const canRegenNode = !!currentNode.parent_id && !!currentNode.chosen_choice_id && !hasDescendants;
  const hasImage = !!currentNode.image_prompt;
  const hasRecap = !!currentNode.recap_text;

  const items = [
    {
      label: "Go Back",
      icon: ArrowLeft,
      action: onGoBack,
      disabled: !canGoBack || isStreaming,
      hint: "Return to previous node",
    },
    {
      label: "Recap",
      icon: BookOpen,
      action: onViewRecap,
      disabled: !hasRecap || isStreaming,
      hint: "Previously on...",
    },
    {
      label: "Regenerate Node",
      icon: RotateCcw,
      action: onRegenerateNode,
      disabled: !canRegenNode || isStreaming,
      hint: "Re-roll this beat from the parent choice",
      danger: true,
    },
    { type: "divider" as const },
    {
      label: "Retry Image",
      icon: ImageIcon,
      action: onRetryImage,
      disabled: !hasImage || isStreaming,
      hint: "Regenerate the scene illustration",
    },
    {
      label: "Edit Image",
      icon: Pencil,
      action: onEditImage,
      disabled: !hasImage || isStreaming,
      hint: "Edit the image prompt and regenerate",
    },
    { type: "divider" as const },
    {
      label: "Read Aloud",
      icon: Volume2,
      action: onReadAloud,
      disabled: isStreaming,
      hint: "TTS narration",
    },
    {
      label: "Portraits",
      icon: Eye,
      action: onViewPortraits,
      disabled: isStreaming,
      hint: "View and manage character portraits",
    },
    {
      label: "Relationships",
      icon: Users,
      action: onViewRelationships,
      disabled: isStreaming,
      hint: "View character relationships",
    },
    {
      label: "Story Graph",
      icon: GitBranch,
      action: onViewGraph,
      disabled: isStreaming,
      hint: "Visualize the story tree",
    },
    {
      label: "Endings",
      icon: Flag,
      action: onViewEndings,
      disabled: isStreaming,
      hint: "View all reached endings",
    },
    {
      label: "Export Book",
      icon: Download,
      action: onExportBook,
      disabled: isStreaming,
      hint: "Export as HTML book",
    },
    {
      label: "Replay",
      icon: Film,
      action: onViewReplay,
      disabled: isStreaming,
      hint: "Replay story from the beginning",
    },
    { type: "divider" as const },
    {
      label: autoPlay ? "Stop Auto-Play" : "Auto-Play",
      icon: FastForward,
      action: onToggleAutoPlay,
      disabled: isStreaming,
      hint: autoPlay ? "Stop automatic play" : "Auto-pick choices",
      toggle: true,
      toggleActive: autoPlay,
    },
  ];

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="p-2 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800/60 transition-colors"
        title="Game menu"
      >
        {open ? <X size={18} /> : <Menu size={18} />}
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />

          {/* Dropdown */}
          <div className="absolute right-0 top-full mt-1 w-64 bg-gray-900 border border-gray-700/60 rounded-xl shadow-2xl z-50 py-1 overflow-hidden">
            {items.map((item, i) => {
              if ("type" in item && item.type === "divider") {
                return <div key={`d${i}`} className="my-1 border-t border-gray-800" />;
              }
              const mi = item as {
                label: string;
                icon: React.ComponentType<{ size?: number; className?: string }>;
                action: () => void;
                disabled: boolean;
                hint?: string;
                danger?: boolean;
                toggle?: boolean;
                toggleActive?: boolean;
              };
              const Icon = mi.icon;
              return (
                <button
                  key={mi.label}
                  onClick={() => {
                    setOpen(false);
                    mi.action();
                  }}
                  disabled={mi.disabled}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                    mi.disabled
                      ? "text-gray-600 cursor-not-allowed"
                      : mi.toggle && mi.toggleActive
                        ? "text-cyan-300 bg-cyan-900/20 hover:bg-cyan-900/30"
                        : mi.danger
                          ? "text-amber-300 hover:bg-amber-900/20"
                          : "text-gray-300 hover:bg-gray-800/60"
                  }`}
                  title={mi.hint}
                >
                  <Icon
                    size={16}
                    className={
                      mi.toggle && mi.toggleActive && !mi.disabled
                        ? "text-cyan-400"
                        : mi.danger && !mi.disabled
                          ? "text-amber-400"
                          : ""
                    }
                  />
                  <span className="flex-1 text-left">{mi.label}</span>
                  {mi.hint && !mi.disabled && (
                    <span className="text-[10px] text-gray-600">{mi.hint}</span>
                  )}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
