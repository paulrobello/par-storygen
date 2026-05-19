"use client";

import { Button } from "@/components/ui/Button";
import type { StoredChoice } from "@/lib/api";
import { Sparkles, CheckCircle2 } from "lucide-react";

interface ChoiceListProps {
  choices: StoredChoice[];
  onChoose: (choiceId: string) => void;
  disabled?: boolean;
}

export function ChoiceList({ choices, onChoose, disabled }: ChoiceListProps) {
  if (!choices || choices.length === 0) return null;

  return (
    <div className="flex-shrink-0 border-t border-gray-800 px-1.5 py-4 bg-gray-900/50">
      <div className="space-y-3">
        <p className="text-sm text-gray-400 mb-2 flex items-center gap-2">
          <Sparkles size={14} className="text-cyan-400" />
          What will you do?
        </p>
        {choices.map((choice, i) => {
          const visited = !!choice.child_node_id;
          return (
            <Button
              key={choice.id}
              variant={visited ? "secondary" : "neon"}
              className="w-full text-left justify-start gap-0"
              onClick={() => onChoose(choice.id)}
              disabled={disabled}
            >
              <span className={`mr-3 font-mono text-sm ${visited ? "text-gray-500" : "text-cyan-500"}`}>
                {i + 1}.
              </span>
              <span className={visited ? "text-gray-300" : ""}>{choice.text}</span>
              {visited && (
                <span className="ml-auto flex items-center gap-1 text-xs text-emerald-500 flex-shrink-0">
                  <CheckCircle2 size={12} />
                  visited
                </span>
              )}
            </Button>
          );
        })}
      </div>
    </div>
  );
}
