"use client";

import ReactMarkdown from "react-markdown";
import { LoadingOverlay } from "@/components/ui/Loading";

interface StoryPanelProps {
  narration: string;
  isStreaming: boolean;
}

export function StoryPanel({ narration, isStreaming }: StoryPanelProps) {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-1.5 py-4">
      <div>
        {narration ? (
          <div className="prose-story text-gray-200 text-lg leading-relaxed">
            <ReactMarkdown>{narration}</ReactMarkdown>
            {isStreaming && (
              <span className="inline-block w-2 h-5 bg-cyan-400 ml-1 neon-pulse" />
            )}
          </div>
        ) : (
          <div className="text-gray-500 italic">The story begins...</div>
        )}
      </div>
      {isStreaming && <LoadingOverlay text="Writing your story..." />}
    </div>
  );
}
