"use client";

import { useParams, useRouter } from "next/navigation";
import { GameLayout } from "@/components/layout/GameLayout";
import { StoryPanel } from "@/components/story/StoryPanel";
import { ChoiceList } from "@/components/story/ChoiceList";
import { ImagePanel } from "@/components/story/ImagePanel";
import { CharacterSidebar } from "@/components/story/CharacterSidebar";
import { Loading } from "@/components/ui/Loading";
import { Modal } from "@/components/ui/Modal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useGame } from "@/hooks/useGame";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useGameStore } from "@/stores/game-store";
import { useState, useCallback } from "react";
import type { Character } from "@/lib/api";
import { ArrowLeft, GitBranch, User } from "lucide-react";
import { AudioPlayer } from "@/components/story/AudioPlayer";
import { GameMenu } from "@/components/story/GameMenu";
import { StoryGraph } from "@/components/story/StoryGraph";

const API = "http://localhost:8101";

export default function PlayPage() {
  const params = useParams<{ gameId: string }>();
  const gameId = params.gameId;
  const router = useRouter();
  const {
    currentGame,
    currentNode,
    isLoading,
    error,
    characters,
    narrationDelta,
    currentImageUrl,
    advanceChoice,
  } = useGame(gameId);

  const isStreaming = useGameStore((s) => s.isLoading);
  const imageStatus = currentNode?.image_status ?? "not_planned";

  useWebSocket({ gameId, enabled: !!currentGame });

  const [selectedCharacter, setSelectedCharacter] = useState<Character | null>(null);

  // Modal states
  const [graphModal, setGraphModal] = useState(false);
  const [endingsModal, setEndingsModal] = useState(false);
  const [editImageModal, setEditImageModal] = useState(false);
  const [portraitsModal, setPortraitsModal] = useState(false);
  const [regenConfirm, setRegenConfirm] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);

  // Modal data
  const [graphEdges, setGraphEdges] = useState<{ parent_id: string; choice_text: string; child_id: string | null }[]>([]);
  const [endingsList, setEndingsList] = useState<string[]>([]);
  const [editPrompt, setEditPrompt] = useState("");
  const [ttsLoading, setTtsLoading] = useState(false);

  const handleChoice = async (choiceId: string) => {
    await advanceChoice(choiceId);
  };

  const handleRetryImage = useCallback(async () => {
    await useGameStore.getState().retryImage(gameId);
  }, [gameId]);

  const handleEditImage = useCallback(async () => {
    if (!currentNode?.image_prompt) return;
    setEditPrompt(currentNode.image_prompt);
    setEditImageModal(true);
  }, [currentNode?.image_prompt]);

  const handleEditImageSubmit = useCallback(async () => {
    if (!editPrompt.trim()) return;
    setEditImageModal(false);
    await useGameStore.getState().editImage(gameId, editPrompt);
  }, [gameId, editPrompt]);

  const handleRegenerateNode = useCallback(async () => {
    setRegenConfirm(false);
    await useGameStore.getState().regenerateNode(gameId);
  }, [gameId]);

  const handleViewGraph = useCallback(async () => {
    try {
      const data = await useGameStore.getState().fetchGraph(gameId);
      setGraphEdges(data.edges);
      setGraphModal(true);
    } catch {
      /* error set in store */
    }
  }, [gameId]);

  const handleViewEndings = useCallback(async () => {
    try {
      const data = await useGameStore.getState().fetchEndings(gameId);
      setEndingsList(data);
      setEndingsModal(true);
    } catch {
      /* error set in store */
    }
  }, [gameId]);

  const handleJumpToEnding = useCallback(
    (nodeId: string) => {
      setEndingsModal(false);
      useGameStore.getState().jumpToNode(nodeId);
    },
    []
  );

  const handleReadAloud = useCallback(async () => {
    if (!currentNode) return;
    setTtsLoading(true);
    try {
      const result = await useGameStore.getState().generateTts(gameId, currentNode.id);
      // Trigger audio playback
      const audio = new Audio(`${API}${result.audio_url}`);
      audio.play().catch(() => {});
    } catch {
      /* error set in store */
    } finally {
      setTtsLoading(false);
    }
  }, [gameId, currentNode]);

  const handleExportBook = useCallback(async () => {
    try {
      const result = await useGameStore.getState().exportBook(gameId);
      setExportResult(`Book exported to: ${result.path}`);
    } catch (err) {
      setExportResult(`Export failed: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  }, [gameId]);

  const handleGoBack = useCallback(() => {
    if (currentNode?.parent_id) {
      useGameStore.getState().jumpToNode(currentNode.parent_id);
    }
  }, [currentNode?.parent_id]);

  if (!currentGame && isLoading) {
    return (
      <GameLayout>
        <div className="flex-1 flex items-center justify-center">
          <Loading text="Loading adventure..." />
        </div>
      </GameLayout>
    );
  }

  if (error && !currentGame) {
    return (
      <GameLayout>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-red-400 text-lg mb-4">{error}</p>
            <button onClick={() => router.push("/menu")} className="text-cyan-400 hover:underline">
              Return to Menu
            </button>
          </div>
        </div>
      </GameLayout>
    );
  }

  if (!currentGame || !currentNode) return null;

  const isEnding = currentNode.is_ending;

  // Build a set of node IDs for quick lookup in graph
  const nodeIds = new Set(Object.keys(currentGame.nodes));

  return (
    <GameLayout>
      <div className="flex-1 flex overflow-hidden">
        {/* Character Sidebar */}
        <CharacterSidebar
          characters={characters}
          gameId={gameId}
          onCharacterClick={setSelectedCharacter}
        />

        {/* Main Content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Top bar with game info */}
          <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800 bg-gray-950/50">
            <div className="flex items-center gap-3">
              <button
                onClick={() => router.push("/menu")}
                className="text-gray-500 hover:text-gray-300 transition-colors"
              >
                <ArrowLeft size={18} />
              </button>
              <h2 className="text-sm font-medium text-gray-300">
                {currentGame.theme.title}
              </h2>
              <div className="flex items-center gap-2 text-xs text-gray-500 ml-2">
                <GitBranch size={12} />
                <span>{Object.keys(currentGame.nodes).length} nodes</span>
                {currentNode.is_major && (
                  <span className="px-1 py-0.5 bg-cyan-900/30 text-cyan-400 rounded text-[10px]">
                    Major
                  </span>
                )}
                {isEnding && (
                  <span className="px-1 py-0.5 bg-amber-900/30 text-amber-400 rounded text-[10px]">
                    Ending
                  </span>
                )}
              </div>
            </div>
            <GameMenu
              currentNode={currentNode}
              isStreaming={isStreaming}
              onRetryImage={handleRetryImage}
              onEditImage={handleEditImage}
              onRegenerateNode={() => setRegenConfirm(true)}
              onGoBack={handleGoBack}
              onViewGraph={handleViewGraph}
              onViewEndings={handleViewEndings}
              onViewPortraits={() => setPortraitsModal(true)}
              onReadAloud={handleReadAloud}
              onExportBook={handleExportBook}
            />
          </div>

          {/* Audio player */}
          <AudioPlayer
            gameId={gameId}
            nodeId={currentNode.id}
            narration={currentNode.narration}
          />

          {/* Story + Image side by side */}
          <div className="flex-1 flex overflow-hidden">
            {/* Story column */}
            <div className="w-1/2 flex flex-col overflow-hidden border-r border-gray-800">
              <StoryPanel
                narration={narrationDelta || currentNode.narration}
                isStreaming={isStreaming}
              />

              {/* Choices or Ending */}
              {isEnding ? (
                <div className="flex-shrink-0 border-t border-gray-800 px-1.5 py-6 text-center bg-gray-900/50">
                  <p className="text-2xl font-bold text-cyan-400 neon-glow-cyan mb-2">
                    The End
                  </p>
                  <p className="text-gray-400 mb-4">
                    You&apos;ve reached the end of this path.
                  </p>
                  <div className="flex gap-3 justify-center">
                    <button
                      onClick={() => router.push("/menu")}
                      className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg border border-gray-600/50 transition-colors"
                    >
                      Main Menu
                    </button>
                    {currentNode.parent_id && (
                      <button
                        onClick={handleGoBack}
                        className="px-4 py-2 border border-cyan-400/50 text-cyan-400 hover:bg-cyan-400/10 rounded-lg transition-colors"
                      >
                        Go Back
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <ChoiceList
                  choices={currentNode.choices ?? []}
                  onChoose={handleChoice}
                  disabled={isStreaming}
                />
              )}
            </div>

            {/* Image column */}
            {(currentImageUrl || imageStatus === "generating") && (
              <div className="w-1/2 flex-shrink-0 bg-gray-950/50 overflow-y-auto">
                <div className="p-3">
                  <ImagePanel imageUrl={currentImageUrl} imageStatus={imageStatus} />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Character Detail Modal */}
      <Modal
        open={!!selectedCharacter}
        onClose={() => setSelectedCharacter(null)}
        title={selectedCharacter?.name}
      >
        {selectedCharacter && (
          <div className="flex gap-5">
            <div
              className="flex-shrink-0 w-32 h-32 rounded-xl border border-gray-700 flex items-center justify-center overflow-hidden"
              style={{ backgroundColor: "#828181" }}
            >
              {selectedCharacter.portrait_path && gameId ? (
                <img
                  src={`${API}/api/images/${gameId}/portrait/${selectedCharacter.id}`}
                  alt={selectedCharacter.name}
                  className="w-full h-full object-contain"
                />
              ) : (
                <User size={40} className="text-gray-500" />
              )}
            </div>
            <div className="flex-1 min-w-0 space-y-3">
              <div>
                <span className="text-xs text-gray-500 uppercase">Personality</span>
                <p className="text-gray-300 text-sm">{selectedCharacter.personality}</p>
              </div>
              <div>
                <span className="text-xs text-gray-500 uppercase">Appearance</span>
                <p className="text-gray-300 text-sm">
                  {selectedCharacter.physical_description}
                </p>
              </div>
              <div>
                <span className="text-xs text-gray-500 uppercase">Backstory</span>
                <p className="text-gray-400 text-sm">{selectedCharacter.backstory}</p>
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* Story Graph — full screen */}
      {graphModal && (
        <div className="fixed inset-0 z-50 bg-gray-950 flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
            <h2 className="text-sm font-medium text-gray-300">Story Graph</h2>
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-500">{graphEdges.length} edges</span>
              <button
                onClick={() => setGraphModal(false)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
              >
                ✕
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-auto p-6">
            {graphEdges.length === 0 ? (
              <p className="text-gray-500 text-sm">No edges found.</p>
            ) : (
              <StoryGraph
                edges={graphEdges}
                rootId={currentGame.root_node_id}
                currentId={currentNode.id}
                nodes={currentGame.nodes}
                onNodeClick={(id) => {
                  setGraphModal(false);
                  useGameStore.getState().jumpToNode(id);
                }}
              />
            )}
          </div>
        </div>
      )}

      {/* Endings Modal */}
      <Modal open={endingsModal} onClose={() => setEndingsModal(false)} title="Endings Reached">
        <div className="max-h-[60vh] overflow-y-auto space-y-2">
          {endingsList.length === 0 ? (
            <p className="text-gray-500 text-sm">No endings reached yet.</p>
          ) : (
            endingsList.map((nodeId) => {
              const node = currentGame.nodes[nodeId];
              return (
                <button
                  key={nodeId}
                  onClick={() => handleJumpToEnding(nodeId)}
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

      {/* Edit Image Prompt Modal */}
      <Modal open={editImageModal} onClose={() => setEditImageModal(false)} title="Edit Image Prompt">
        <textarea
          value={editPrompt}
          onChange={(e) => setEditPrompt(e.target.value)}
          rows={6}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm text-gray-200 resize-none focus:outline-none focus:border-cyan-500"
        />
        <div className="flex justify-end gap-3 mt-4">
          <button
            onClick={() => setEditImageModal(false)}
            className="px-4 py-2 text-gray-400 hover:text-gray-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleEditImageSubmit}
            className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors"
          >
            Regenerate
          </button>
        </div>
      </Modal>

      {/* Portraits Gallery Modal */}
      <Modal open={portraitsModal} onClose={() => setPortraitsModal(false)} title="Character Portraits">
        <div className="grid grid-cols-3 gap-4">
          {characters.map((char) => (
            <button
              key={char.id}
              onClick={() => {
                setPortraitsModal(false);
                setSelectedCharacter(char);
              }}
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
      </Modal>

      {/* Regenerate Node Confirm */}
      <ConfirmDialog
        open={regenConfirm}
        onConfirm={handleRegenerateNode}
        onCancel={() => setRegenConfirm(false)}
        title="Regenerate Node"
        message="This will discard the current beat and generate a new one from the parent choice. This cannot be undone."
        confirmLabel="Regenerate"
        variant="danger"
      />

      {/* Export Result */}
      <Modal
        open={!!exportResult}
        onClose={() => setExportResult(null)}
        title="Export Book"
      >
        <p className="text-sm text-gray-300">{exportResult}</p>
      </Modal>

      {/* TTS loading indicator */}
      {ttsLoading && (
        <div className="fixed bottom-4 right-4 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-300 z-50 flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-cyan-400 animate-pulse" />
          Generating audio…
        </div>
      )}
    </GameLayout>
  );
}
