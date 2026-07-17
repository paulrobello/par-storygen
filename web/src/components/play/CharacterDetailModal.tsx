"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Character detail + edit
// form modal. Owns the edit-mode state (editing flag + draft fields) so the
// page no longer needs the charEdit* useState cluster. Reset to read-only on
// close, matching the prior in-page behavior.
import { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Pencil, User } from "lucide-react";
import { API_BASE as API } from "@/lib/config";
import { useGameStore } from "@/stores/game-store";
import type { Character } from "@/lib/api";

export function CharacterDetailModal({
  open,
  character,
  gameId,
  onClose,
  onCharacterUpdated,
}: {
  open: boolean;
  character: Character | null;
  gameId: string;
  onClose: () => void;
  // After a save, the page refreshes its selectedCharacter from the store so
  // the title + read-only view reflect the new name/fields without a reopen.
  onCharacterUpdated: (updated: Character) => void;
}) {
  const [charEditing, setCharEditing] = useState(false);
  const [charEditName, setCharEditName] = useState("");
  const [charEditPersonality, setCharEditPersonality] = useState("");
  const [charEditPhysical, setCharEditPhysical] = useState("");
  const [charEditBackstory, setCharEditBackstory] = useState("");

  const handleClose = () => {
    setCharEditing(false);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={charEditing ? "Edit Character" : (character?.name ?? "Character")}
    >
      {character && (
        <>
          {/* Portrait */}
          <div className="flex justify-center mb-4">
            <div
              className="w-24 h-24 rounded-xl border border-gray-700 flex items-center justify-center overflow-hidden"
              style={{ backgroundColor: "#828181" }}
            >
              {character.portrait_path && gameId ? (
                <img
                  src={`${API}/api/images/${gameId}/portrait/${character.id}`}
                  alt={character.name}
                  className="w-full h-full object-contain"
                />
              ) : (
                <User size={32} className="text-gray-500" />
              )}
            </div>
          </div>

          {charEditing ? (
            /* Edit form */
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 uppercase mb-1">Name</label>
                <input
                  type="text"
                  value={charEditName}
                  onChange={(e) => setCharEditName(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-cyan-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 uppercase mb-1">Personality</label>
                <textarea
                  value={charEditPersonality}
                  onChange={(e) => setCharEditPersonality(e.target.value)}
                  rows={3}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 resize-none focus:outline-none focus:border-cyan-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 uppercase mb-1">Appearance</label>
                <textarea
                  value={charEditPhysical}
                  onChange={(e) => setCharEditPhysical(e.target.value)}
                  rows={3}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 resize-none focus:outline-none focus:border-cyan-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 uppercase mb-1">Backstory</label>
                <textarea
                  value={charEditBackstory}
                  onChange={(e) => setCharEditBackstory(e.target.value)}
                  rows={3}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 resize-none focus:outline-none focus:border-cyan-500"
                />
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button
                  onClick={() => setCharEditing(false)}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    useGameStore.getState().updateCharacter(character.id, {
                      name: charEditName,
                      personality: charEditPersonality,
                      physical_description: charEditPhysical,
                      backstory: charEditBackstory,
                    });
                    // Refresh selectedCharacter from the updated store (matches
                    // the prior in-page behavior so the title/view update live).
                    const updated = useGameStore
                      .getState()
                      .characters.find((c) => c.id === character.id);
                    if (updated) onCharacterUpdated(updated);
                    setCharEditing(false);
                  }}
                  className="px-4 py-2 text-sm bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors"
                >
                  Save
                </button>
              </div>
            </div>
          ) : (
            /* Read-only view */
            <div className="space-y-3">
              <div>
                <span className="text-xs text-gray-500 uppercase">Personality</span>
                <p className="text-gray-300 text-sm">{character.personality}</p>
              </div>
              <div>
                <span className="text-xs text-gray-500 uppercase">Appearance</span>
                <p className="text-gray-300 text-sm">
                  {character.physical_description}
                </p>
              </div>
              <div>
                <span className="text-xs text-gray-500 uppercase">Backstory</span>
                <p className="text-gray-400 text-sm">{character.backstory}</p>
              </div>
              <div className="flex justify-end pt-2">
                <button
                  onClick={() => {
                    setCharEditName(character.name);
                    setCharEditPersonality(character.personality);
                    setCharEditPhysical(character.physical_description);
                    setCharEditBackstory(character.backstory);
                    setCharEditing(true);
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-cyan-400 border border-cyan-400/50 hover:bg-cyan-400/10 rounded-lg transition-colors"
                >
                  <Pencil size={14} />
                  Edit
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
