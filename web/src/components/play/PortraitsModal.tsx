"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. The portraits gallery
// modal: grid of characters → per-character detail with regen / edit / export
// actions + outfits management. Owns its own UI state (selected character,
// edit-prompt sub-modal, outfit form inputs); API actions come from the
// usePortraitActions hook. The toast is rendered by the page shell so it
// survives modal close.
import { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { PortraitEditModal } from "@/components/play/PortraitEditModal";
import { ArrowLeft, Pencil, User } from "lucide-react";
import { API_BASE as API } from "@/lib/config";
import { apiPost, apiDelete } from "@/lib/api";
import type { Character } from "@/lib/api";
import { useGameStore } from "@/stores/game-store";
import type { PortraitActions } from "@/hooks/usePortraitActions";

export function PortraitsModal({
  open,
  onClose,
  gameId,
  characters,
  actions,
}: {
  open: boolean;
  onClose: () => void;
  gameId: string;
  characters: Character[];
  actions: PortraitActions;
}) {
  const [portraitChar, setPortraitChar] = useState<Character | null>(null);
  const [portraitEditPrompt, setPortraitEditPrompt] = useState("");
  const [portraitEditModal, setPortraitEditModal] = useState(false);
  const [outfitName, setOutfitName] = useState("");
  const [outfitDesc, setOutfitDesc] = useState("");
  const [outfitLoading, setOutfitLoading] = useState(false);

  const handleClose = () => {
    setPortraitChar(null);
    onClose();
  };

  const handleEditSubmit = async () => {
    if (!portraitChar || !portraitEditPrompt.trim()) return;
    // Only close on success — on failure leave the prompt open so the user
    // can adjust and retry (matches the prior in-page behavior).
    const ok = await actions.edit(portraitChar.id, portraitEditPrompt);
    if (ok) setPortraitEditModal(false);
  };

  return (
    <>
      <Modal
        open={open}
        onClose={handleClose}
        title={portraitChar ? portraitChar.name : "Character Portraits"}
      >
        {portraitChar ? (
          /* Portrait detail / action panel */
          <div className="space-y-4">
            <button
              onClick={() => setPortraitChar(null)}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 transition-colors mb-1"
            >
              <ArrowLeft size={12} />
              Back to gallery
            </button>

            {/* Large portrait */}
            <div className="flex justify-center">
              <div
                className="w-48 h-48 rounded-xl border border-gray-700 flex items-center justify-center overflow-hidden"
                style={{ backgroundColor: "#828181" }}
              >
                {portraitChar.portrait_path && gameId ? (
                  <img
                    src={`${API}/api/images/${gameId}/portrait/${portraitChar.id}`}
                    alt={portraitChar.name}
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <User size={64} className="text-gray-500" />
                )}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex flex-col gap-2">
              <button
                onClick={() => actions.regen(portraitChar.id)}
                disabled={actions.regenLoading}
                className="w-full px-4 py-2.5 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center justify-center gap-2 text-sm"
              >
                {actions.regenLoading ? (
                  <>
                    <span className="inline-block w-3 h-3 rounded-full bg-white animate-pulse" />
                    Generating...
                  </>
                ) : (
                  "Regenerate Portrait"
                )}
              </button>

              <button
                onClick={() => {
                  setPortraitEditPrompt(
                    portraitChar.portrait_prompt ?? portraitChar.physical_description,
                  );
                  setPortraitEditModal(true);
                }}
                disabled={actions.regenLoading}
                className="w-full px-4 py-2.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-200 rounded-lg border border-gray-600/50 transition-colors flex items-center justify-center gap-2 text-sm"
              >
                <Pencil size={14} />
                Edit Portrait
              </button>

              <button
                onClick={() => actions.exportChar(portraitChar)}
                disabled={actions.exportLoading}
                className="w-full px-4 py-2.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-200 rounded-lg border border-gray-600/50 transition-colors flex items-center justify-center gap-2 text-sm"
              >
                {actions.exportLoading ? (
                  <>
                    <span className="inline-block w-3 h-3 rounded-full bg-cyan-400 animate-pulse" />
                    Exporting...
                  </>
                ) : (
                  "Export to Library"
                )}
              </button>
            </div>

            {/* Character info summary */}
            <div className="text-xs text-gray-500 space-y-1 pt-2 border-t border-gray-800">
              <p>
                <span className="text-gray-400">Personality:</span> {portraitChar.personality}
              </p>
              <p>
                <span className="text-gray-400">Appearance:</span>{" "}
                {portraitChar.physical_description}
              </p>
            </div>

            {/* Outfits section */}
            <div className="pt-2 border-t border-gray-800">
              <h4 className="text-xs text-gray-400 uppercase mb-2">Outfits</h4>
              {(portraitChar.outfits ?? []).length > 0 && (
                <div className="space-y-2 mb-3">
                  {(portraitChar.outfits ?? []).map((o) => (
                    <div
                      key={o.id}
                      className={`flex items-center gap-2 p-2 rounded-lg border ${
                        portraitChar.current_outfit_id === o.id
                          ? "border-cyan-500/50 bg-cyan-900/20"
                          : "border-gray-700/50 bg-gray-800/40"
                      }`}
                    >
                      <img
                        src={`${API}/api/games/${gameId}/images/${o.portrait_path}`}
                        alt={o.name}
                        className="w-10 h-10 rounded object-contain"
                        style={{ backgroundColor: "#828181" }}
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-gray-300 font-medium truncate">{o.name}</p>
                        <p className="text-[10px] text-gray-600 truncate">{o.description}</p>
                      </div>
                      <div className="flex items-center gap-1">
                        {portraitChar.current_outfit_id !== o.id && (
                          <button
                            onClick={async () => {
                              await apiPost(
                                `/api/images/${gameId}/portrait/${portraitChar.id}/outfit/${o.id}/set`,
                              );
                              await useGameStore.getState().refreshGame(gameId);
                              setPortraitChar({
                                ...portraitChar,
                                current_outfit_id: o.id,
                                portrait_path: o.portrait_path,
                                portrait_prompt: o.portrait_prompt,
                              });
                            }}
                            className="text-[10px] px-2 py-1 rounded bg-cyan-900/30 text-cyan-400 hover:bg-cyan-900/50 transition-colors"
                          >
                            Set
                          </button>
                        )}
                        <button
                          onClick={async () => {
                            await apiDelete(
                              `/api/images/${gameId}/portrait/${portraitChar.id}/outfit/${o.id}`,
                            );
                            await useGameStore.getState().refreshGame(gameId);
                            const updated = (portraitChar.outfits ?? []).filter(
                              (x) => x.id !== o.id,
                            );
                            const reverted =
                              portraitChar.current_outfit_id === o.id
                                ? { ...portraitChar, outfits: updated, current_outfit_id: null }
                                : { ...portraitChar, outfits: updated };
                            setPortraitChar(reverted);
                          }}
                          className="text-[10px] px-2 py-1 rounded bg-red-900/30 text-red-400 hover:bg-red-900/50 transition-colors"
                        >
                          Del
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {portraitChar.current_outfit_id && (
                <button
                  onClick={async () => {
                    await apiPost(
                      `/api/images/${gameId}/portrait/${portraitChar.id}/outfit/revert`,
                    );
                    await useGameStore.getState().refreshGame(gameId);
                    setPortraitChar({ ...portraitChar, current_outfit_id: null });
                  }}
                  className="text-[10px] px-2 py-1 mb-2 rounded bg-gray-800 text-gray-400 hover:text-gray-200 transition-colors"
                >
                  Revert to base
                </button>
              )}
              <div className="flex gap-2">
                <input
                  value={outfitName}
                  onChange={(e) => setOutfitName(e.target.value)}
                  placeholder="Name"
                  className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500/50"
                />
                <input
                  value={outfitDesc}
                  onChange={(e) => setOutfitDesc(e.target.value)}
                  placeholder="Description (e.g. wearing red armor)"
                  className="flex-[2] bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500/50"
                />
                <button
                  onClick={async () => {
                    if (!outfitName.trim() || !outfitDesc.trim()) return;
                    setOutfitLoading(true);
                    try {
                      await apiPost(
                        `/api/images/${gameId}/portrait/${portraitChar.id}/outfit`,
                        { name: outfitName, description: outfitDesc },
                      );
                      await useGameStore.getState().refreshGame(gameId);
                      setOutfitName("");
                      setOutfitDesc("");
                      actions.notify("Outfit created");
                    } catch (err) {
                      actions.notify(
                        `Failed: ${err instanceof Error ? err.message : "Unknown"}`,
                      );
                    } finally {
                      setOutfitLoading(false);
                    }
                  }}
                  disabled={outfitLoading || !outfitName.trim() || !outfitDesc.trim()}
                  className="px-3 py-1 text-xs bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded transition-colors"
                >
                  {outfitLoading ? "..." : "Add"}
                </button>
              </div>
            </div>
          </div>
        ) : (
          /* Character grid */
          <div className="grid grid-cols-3 gap-4">
            {characters.map((char) => (
              <button
                key={char.id}
                onClick={() => setPortraitChar(char)}
                className="flex flex-col items-center gap-2 p-3 rounded-lg hover:bg-gray-800/50 transition-colors"
              >
                <div
                  className="w-24 h-24 rounded-lg border border-gray-700 flex items-center justify-center overflow-hidden"
                  style={{ backgroundColor: "#828181" }}
                >
                  {char.portrait_path && gameId ? (
                    <img
                      src={`${API}/api/images/${gameId}/portrait/${char.id}`}
                      alt={char.name}
                      className="w-full h-full object-contain"
                    />
                  ) : (
                    <User size={28} className="text-gray-500" />
                  )}
                </div>
                <span className="text-xs text-gray-300 truncate">{char.name}</span>
              </button>
            ))}
          </div>
        )}
      </Modal>

      <PortraitEditModal
        open={portraitEditModal}
        onClose={() => setPortraitEditModal(false)}
        prompt={portraitEditPrompt}
        onPromptChange={setPortraitEditPrompt}
        onSubmit={handleEditSubmit}
        loading={actions.editLoading}
      />
    </>
  );
}
