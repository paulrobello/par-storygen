"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Loading } from "@/components/ui/Loading";
import { apiGet } from "@/lib/api";
import type {
  GameSave,
  GameSummary,
  LibraryCharacter,
} from "@/lib/api";
import type { CharacterActions } from "@/hooks/useCharacterActions";
import { ChevronDown, ChevronRight } from "lucide-react";

interface ImportFromStoryModalProps {
  onClose: () => void;
  /** Called after a successful import (the hook has already refreshed the list). */
  onImported: () => void;
  actions: CharacterActions;
}

/**
 * "Import from Story" modal. Mounted only while open, so the game list,
 * expansion state, per-game character cache, and selection set all start fresh
 * each time. The actual import + library refresh are delegated to the shared
 * character-actions hook.
 */
export function ImportFromStoryModal({
  onClose,
  onImported,
  actions,
}: ImportFromStoryModalProps) {
  // Pull the stable action callbacks out of the bundle (its members are
  // useCallback-stable even though the bundle object is a new ref per render).
  const { showError, importFromStory } = actions;

  const [games, setGames] = useState<GameSummary[]>([]);
  const [expandedGameId, setExpandedGameId] = useState<string | null>(null);
  const [gameCharsMap, setGameCharsMap] = useState<
    Map<string, LibraryCharacter[]>
  >(new Map());
  // Starts true: the save list is fetched on mount, so render the spinner
  // immediately rather than flipping it on synchronously inside the effect.
  const [isLoadingGames, setIsLoadingGames] = useState(true);
  const [loadingGameChars, setLoadingGameChars] = useState(false);
  const [selectedImportIds, setSelectedImportIds] = useState<Set<string>>(
    new Set()
  );
  const [isImporting, setIsImporting] = useState(false);

  // Load the save list once when the modal mounts (= each time it opens).
  useEffect(() => {
    apiGet<GameSummary[]>("/api/games")
      .then((result) => setGames(result))
      .catch((err) =>
        showError(
          err instanceof Error ? err.message : "Failed to load story saves"
        )
      )
      .finally(() => setIsLoadingGames(false));
  }, [showError]);

  const toggleGameExpansion = async (gameId: string) => {
    if (expandedGameId === gameId) {
      setExpandedGameId(null);
      return;
    }
    setExpandedGameId(gameId);

    // Lazy-load characters if not cached.
    if (!gameCharsMap.has(gameId)) {
      setLoadingGameChars(true);
      try {
        const save = await apiGet<GameSave>(`/api/games/${gameId}`);
        const chars: LibraryCharacter[] = save.characters.map((c) => ({
          id: c.id,
          name: c.name,
          backstory: c.backstory,
          personality: c.personality,
          physical_description: c.physical_description,
          portrait_prompt: c.portrait_prompt ?? "",
          exported_at: save.updated_at,
          source: save.theme?.title ?? "",
          has_portrait: !!c.portrait_path,
        }));
        setGameCharsMap((prev) => new Map(prev).set(gameId, chars));
      } catch (err) {
        showError(
          err instanceof Error ? err.message : "Failed to load game characters"
        );
      } finally {
        setLoadingGameChars(false);
      }
    }
  };

  const toggleImportId = (charId: string) => {
    setSelectedImportIds((prev) => {
      const next = new Set(prev);
      if (next.has(charId)) next.delete(charId);
      else next.add(charId);
      return next;
    });
  };

  const handleImportSelected = async () => {
    if (!expandedGameId || selectedImportIds.size === 0) return;
    setIsImporting(true);
    try {
      await importFromStory(expandedGameId, selectedImportIds);
      onClose();
      onImported();
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to import characters"
      );
    } finally {
      setIsImporting(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="Import from Story">
      <div className="space-y-4">
        {isLoadingGames ? (
          <Loading text="Loading saves..." />
        ) : games.length === 0 ? (
          <p className="text-center py-8 text-gray-500">
            No story saves found.
          </p>
        ) : (
          <div className="max-h-[50vh] overflow-y-auto space-y-2 pr-1">
            {games.map((game) => {
              const isExpanded = expandedGameId === game.id;
              const gameChars = gameCharsMap.get(game.id);
              return (
                <div
                  key={game.id}
                  className="border border-gray-700/50 rounded-lg overflow-hidden"
                >
                  {/* Game header */}
                  <button
                    onClick={() => toggleGameExpansion(game.id)}
                    className="w-full flex items-center justify-between p-3 text-left hover:bg-gray-800/50 transition-colors"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      {isExpanded ? (
                        <ChevronDown
                          size={16}
                          className="text-gray-500 flex-shrink-0"
                        />
                      ) : (
                        <ChevronRight
                          size={16}
                          className="text-gray-500 flex-shrink-0"
                        />
                      )}
                      <span className="text-gray-200 font-medium truncate">
                        {game.title || `Save ${game.id.slice(0, 8)}...`}
                      </span>
                    </div>
                    <span className="text-gray-500 text-xs flex-shrink-0 ml-2">
                      {game.node_count} nodes
                    </span>
                  </button>

                  {/* Expanded: character list */}
                  {isExpanded && (
                    <div className="px-3 pb-3 pt-1 border-t border-gray-800">
                      {loadingGameChars && !gameChars ? (
                        <Loading text="Loading characters..." />
                      ) : gameChars && gameChars.length > 0 ? (
                        <div className="space-y-1">
                          {gameChars.map((char) => (
                            <label
                              key={char.id}
                              className="flex items-center gap-3 p-2 hover:bg-gray-800/30 rounded cursor-pointer"
                            >
                              <input
                                type="checkbox"
                                checked={selectedImportIds.has(char.id)}
                                onChange={() => toggleImportId(char.id)}
                                className="rounded border-gray-600 bg-gray-800 text-cyan-500 focus:ring-cyan-500/50"
                              />
                              <div className="min-w-0">
                                <span className="text-gray-200 text-sm">
                                  {char.name}
                                </span>
                                <p className="text-gray-500 text-xs line-clamp-1">
                                  {char.personality}
                                </p>
                              </div>
                            </label>
                          ))}
                        </div>
                      ) : (
                        <p className="text-gray-500 text-sm py-2 text-center">
                          No characters in this save.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-2 border-t border-gray-800">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleImportSelected}
            disabled={selectedImportIds.size === 0 || isImporting}
          >
            {isImporting
              ? "Importing..."
              : `Import Selected (${selectedImportIds.size})`}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
