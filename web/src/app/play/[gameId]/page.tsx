"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { GameLayout } from "@/components/layout/GameLayout";
import { StoryPanel } from "@/components/story/StoryPanel";
import { ChoiceList } from "@/components/story/ChoiceList";
import { ImagePanel } from "@/components/story/ImagePanel";
import { CharacterSidebar } from "@/components/story/CharacterSidebar";
import { Loading } from "@/components/ui/Loading";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { AudioPlayer } from "@/components/story/AudioPlayer";
import { GameMenu } from "@/components/story/GameMenu";
import { ArrowLeft, GitBranch } from "lucide-react";
import { useGame } from "@/hooks/useGame";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useSettings } from "@/hooks/useSettings";
import { useGameStore } from "@/stores/game-store";
import { apiGet } from "@/lib/api";
import type { Character } from "@/lib/api";
import { API_BASE as API } from "@/lib/config";
// Dynamic modals (ENH-007)
const CharacterDetailModal = dynamic(() => import("@/components/play/CharacterDetailModal").then(m => ({ default: m.CharacterDetailModal })), { ssr: false });
const EditImageModal = dynamic(() => import("@/components/play/EditImageModal").then(m => ({ default: m.EditImageModal })), { ssr: false });
const EndingsModal = dynamic(() => import("@/components/play/EndingsModal").then(m => ({ default: m.EndingsModal })), { ssr: false });
const ExportBookModal = dynamic(() => import("@/components/play/ExportBookModal").then(m => ({ default: m.ExportBookModal })), { ssr: false });
const PortraitsModal = dynamic(() => import("@/components/play/PortraitsModal").then(m => ({ default: m.PortraitsModal })), { ssr: false });
const RecapModal = dynamic(() => import("@/components/play/RecapModal").then(m => ({ default: m.RecapModal })), { ssr: false });
const RelationshipsModal = dynamic(() => import("@/components/play/RelationshipsModal").then(m => ({ default: m.RelationshipsModal })), { ssr: false });
const ReplayModal = dynamic(() => import("@/components/play/ReplayModal").then(m => ({ default: m.ReplayModal })), { ssr: false });
const StoryGraphModal = dynamic(() => import("@/components/play/StoryGraphModal").then(m => ({ default: m.StoryGraphModal })), { ssr: false });
// Extracted feature hooks (QA-001)
import { useGameViews } from "@/hooks/useGameViews";
import { usePlayTts } from "@/hooks/usePlayTts";
import { usePortraitActions } from "@/hooks/usePortraitActions";
import { useRecap } from "@/hooks/useRecap";
import { useReplay } from "@/hooks/useReplay";
import { useSceneImage } from "@/hooks/useSceneImage";

interface PathNode {
  id: string;
  chosen_choice_id: string | null;
}

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
  const { settings } = useSettings();

  // Feature hooks — each owns the useState cluster it needs.
  const portraits = usePortraitActions(gameId, currentGame?.theme.title ?? "");
  const tts = usePlayTts(gameId, currentNode, isStreaming, advanceChoice);
  const sceneImage = useSceneImage(gameId, currentNode);
  const views = useGameViews(gameId);
  const replay = useReplay(gameId, currentNode);
  const recap = useRecap(currentNode, settings);

  // Page-shell-only UI state.
  const [selectedCharacter, setSelectedCharacter] = useState<Character | null>(null);
  const [portraitsModal, setPortraitsModal] = useState(false);
  const [relationshipsModal, setRelationshipsModal] = useState(false);
  const [regenConfirm, setRegenConfirm] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);
  const [pathNodes, setPathNodes] = useState<PathNode[]>([]);

  // Fetch breadcrumb path when the current node changes.
  useEffect(() => {
    if (!gameId || !currentNode) {
      setPathNodes([]);
      return;
    }
    (async () => {
      try {
        const nodes = await apiGet<PathNode[]>(
          `/api/games/${gameId}/path?target_node_id=${currentNode.id}`,
        );
        setPathNodes(nodes);
      } catch {
        setPathNodes([]);
      }
    })();
  }, [gameId, currentNode?.id]);

  const handleChoice = async (choiceId: string) => {
    await advanceChoice(choiceId);
  };

  const handleRegenerateNode = async () => {
    setRegenConfirm(false);
    await useGameStore.getState().regenerateNode(gameId);
  };

  const handleGoBack = () => {
    if (currentNode?.parent_id) {
      useGameStore.getState().jumpToNode(currentNode.parent_id);
    }
  };

  const handleExportBook = async () => {
    try {
      await useGameStore.getState().exportBook(gameId);
      // Trigger browser download of the exported book.
      window.open(`${API}/api/games/${gameId}/export-book/download`, "_blank");
    } catch (err) {
      setExportResult(`Export failed: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  };

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

  // Below this point currentGame + currentNode are non-null.

  const isEnding = currentNode.is_ending;

  return (
    <GameLayout>
      <div className="flex-1 flex overflow-hidden">
        <CharacterSidebar characters={characters} gameId={gameId} onCharacterClick={setSelectedCharacter} />

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
              <h2 className="text-sm font-medium text-gray-300">{currentGame.theme.title}</h2>
              <div className="flex items-center gap-2 text-xs text-gray-500 ml-2">
                <GitBranch size={12} />
                <span>{Object.keys(currentGame.nodes).length} nodes</span>
                <span className="text-gray-600">|</span>
                <span>
                  ${(currentGame.total_image_cost_usd ?? 0).toFixed(4)} &middot;{" "}
                  {(currentGame.text_total_input_tokens ?? 0).toLocaleString()}&uarr;/{" "}
                  {(currentGame.text_total_output_tokens ?? 0).toLocaleString()}&darr; tok
                </span>
                {currentNode.is_major && (
                  <span className="px-1 py-0.5 bg-cyan-900/30 text-cyan-400 rounded text-[10px]">Major</span>
                )}
                {isEnding && (
                  <span className="px-1 py-0.5 bg-amber-900/30 text-amber-400 rounded text-[10px]">Ending</span>
                )}
              </div>
            </div>
            <GameMenu
              currentNode={currentNode}
              isStreaming={isStreaming}
              autoPlay={tts.autoPlay}
              onToggleAutoPlay={tts.toggleAutoPlay}
              onRetryImage={sceneImage.retryImage}
              onEditImage={sceneImage.openEdit}
              onRegenerateNode={() => setRegenConfirm(true)}
              onGoBack={handleGoBack}
              onViewGraph={views.viewGraph}
              onViewEndings={views.viewEndings}
              onViewPortraits={() => setPortraitsModal(true)}
              onReadAloud={tts.readAloud}
              onExportBook={handleExportBook}
              onViewReplay={replay.viewReplay}
              onViewRelationships={() => setRelationshipsModal(true)}
              onViewRecap={() => recap.setRecapModal(true)}
            />
          </div>

          {/* Breadcrumb path */}
          {pathNodes.length > 1 && (
            <div className="flex items-center gap-1 px-4 py-1 text-[10px] text-gray-600 border-b border-gray-800/50 bg-gray-950/30 overflow-x-auto">
              {pathNodes.map((pn, i) => (
                <span key={pn.id} className="flex items-center gap-1 whitespace-nowrap">
                  {i > 0 && <span className="text-gray-700">&rsaquo;</span>}
                  <button
                    onClick={() => useGameStore.getState().jumpToNode(pn.id)}
                    className={`hover:text-gray-300 transition-colors ${
                      pn.id === currentNode.id ? "text-cyan-400" : ""
                    }`}
                  >
                    {i === 0 ? "Start" : `#${i}`}
                  </button>
                </span>
              ))}
            </div>
          )}

          <AudioPlayer gameId={gameId} nodeId={currentNode.id} narration={currentNode.narration} />

          {/* Story + Image side by side */}
          <div className="flex-1 flex overflow-hidden">
            <div className="w-1/2 flex flex-col overflow-hidden border-r border-gray-800">
              <StoryPanel narration={narrationDelta || currentNode.narration} isStreaming={isStreaming} />

              {isEnding ? (
                <div className="flex-shrink-0 border-t border-gray-800 px-1.5 py-6 text-center bg-gray-900/50">
                  <p className="text-2xl font-bold text-cyan-400 neon-glow-cyan mb-2">The End</p>
                  <p className="text-gray-400 mb-4">You&apos;ve reached the end of this path.</p>
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
                <ChoiceList choices={currentNode.choices ?? []} onChoose={handleChoice} disabled={isStreaming} />
              )}
            </div>

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

      {/* Modals */}
      <CharacterDetailModal
        open={!!selectedCharacter}
        character={selectedCharacter}
        gameId={gameId}
        onClose={() => setSelectedCharacter(null)}
        onCharacterUpdated={setSelectedCharacter}
      />
      <StoryGraphModal
        open={views.graphModal}
        onClose={views.closeGraph}
        edges={views.graphEdges}
        gameId={gameId}
        rootId={currentGame.root_node_id}
        currentId={currentNode.id}
        nodes={currentGame.nodes}
        onPrune={views.prune}
        onNodeClick={(id) => {
          views.closeGraph();
          useGameStore.getState().jumpToNode(id);
        }}
      />
      <EndingsModal
        open={views.endingsModal}
        onClose={views.closeEndings}
        endingsList={views.endingsList}
        nodes={currentGame.nodes}
        onJumpTo={views.jumpToEnding}
      />
      <EditImageModal
        open={sceneImage.editImageModal}
        onClose={sceneImage.closeEdit}
        prompt={sceneImage.editPrompt}
        onPromptChange={sceneImage.setEditPrompt}
        onSubmit={sceneImage.submitEdit}
      />
      <PortraitsModal
        open={portraitsModal}
        onClose={() => setPortraitsModal(false)}
        gameId={gameId}
        characters={characters}
        actions={portraits}
      />
      <RelationshipsModal
        open={relationshipsModal}
        onClose={() => setRelationshipsModal(false)}
        relationships={currentGame.relationships}
        characters={characters}
      />
      <RecapModal
        open={recap.recapModal}
        onClose={() => recap.setRecapModal(false)}
        recapText={currentNode?.recap_text ?? ""}
        onReadAloud={tts.recapReadAloud}
        ttsLoading={tts.recapTtsLoading}
      />
      <ExportBookModal
        open={!!exportResult}
        onClose={() => setExportResult(null)}
        message={exportResult}
      />
      <ReplayModal
        open={replay.replayModal}
        onClose={replay.closeReplay}
        gameId={gameId}
        nodes={replay.replayNodes}
        index={replay.replayIndex}
        setIndex={replay.setReplayIndex}
      />
      <ConfirmDialog
        open={regenConfirm}
        onConfirm={handleRegenerateNode}
        onCancel={() => setRegenConfirm(false)}
        title="Regenerate Node"
        message="This will discard the current beat and generate a new one from the parent choice. This cannot be undone."
        confirmLabel="Regenerate"
        variant="danger"
      />

      {/* Portrait action toast (rendered here so it survives PortraitsModal close) */}
      {portraits.toastMessage && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-200 z-50 animate-in fade-in duration-150">
          {portraits.toastMessage}
        </div>
      )}

      {/* TTS loading indicator */}
      {tts.ttsLoading && (
        <div className="fixed bottom-4 right-4 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-300 z-50 flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-cyan-400 animate-pulse" />
          Generating audio…
        </div>
      )}
    </GameLayout>
  );
}
