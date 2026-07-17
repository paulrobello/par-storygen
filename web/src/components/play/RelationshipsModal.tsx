"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Renders the pairwise
// character relationships list. Self-contained — the page just passes the
// open/onClose pair + data.
import { Modal } from "@/components/ui/Modal";
import type { Character, Relationship } from "@/lib/api";

const REL_TYPE_COLORS: Record<string, string> = {
  ally: "bg-green-600/30 text-green-400 border-green-600/40",
  rival: "bg-red-600/30 text-red-400 border-red-600/40",
  romantic: "bg-pink-600/30 text-pink-400 border-pink-600/40",
  mentor: "bg-blue-600/30 text-blue-400 border-blue-600/40",
  family: "bg-amber-600/30 text-amber-400 border-amber-600/40",
  neutral: "bg-gray-600/30 text-gray-400 border-gray-600/40",
  stranger: "bg-gray-600/30 text-gray-400 border-gray-600/40",
  student: "bg-purple-600/30 text-purple-400 border-purple-600/40",
};

const NEUTRAL_COLOR = "bg-gray-600/30 text-gray-400 border-gray-600/40";

function StrengthBar({ strength }: { strength: number }) {
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <div
          key={i}
          className={`w-3 h-3 rounded-sm ${
            i < strength ? "bg-cyan-500" : "bg-gray-700"
          }`}
        />
      ))}
    </div>
  );
}

export function RelationshipsModal({
  open,
  onClose,
  relationships,
  characters,
}: {
  open: boolean;
  onClose: () => void;
  relationships: Relationship[];
  characters: Character[];
}) {
  const charMap = new Map(characters.map((c) => [c.id, c.name]));

  return (
    <Modal open={open} onClose={onClose} title="Character Relationships" maxWidth="max-w-lg">
      <div className="max-h-[60vh] overflow-y-auto space-y-3">
        {(relationships ?? []).length === 0 ? (
          <p className="text-gray-500 text-sm">No relationships discovered yet.</p>
        ) : (
          (relationships ?? []).map((rel, i) => {
            const colorClasses = REL_TYPE_COLORS[rel.type] ?? NEUTRAL_COLOR;
            return (
              <div
                key={`${rel.char_a_id}-${rel.char_b_id}-${i}`}
                className="p-3 rounded-lg bg-gray-800/40 border border-gray-700/50 space-y-2"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-gray-200">
                    <span>{charMap.get(rel.char_a_id) ?? rel.char_a_id.slice(0, 8)}</span>
                    <span className="text-gray-600">&harr;</span>
                    <span>{charMap.get(rel.char_b_id) ?? rel.char_b_id.slice(0, 8)}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <StrengthBar strength={rel.strength} />
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium border ${colorClasses}`}
                    >
                      {rel.type}
                    </span>
                  </div>
                </div>
                {rel.context && (
                  <p className="text-xs text-gray-500 leading-relaxed">{rel.context}</p>
                )}
              </div>
            );
          })
        )}
      </div>
    </Modal>
  );
}
