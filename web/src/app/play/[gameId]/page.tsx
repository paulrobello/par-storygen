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
import { useSettings } from "@/hooks/useSettings";
import { useGameStore } from "@/stores/game-store";
import { useState, useCallback, useEffect, useRef } from "react";
import type { Character, Relationship, StoryNode } from "@/lib/api";
import { apiGet, apiPost, apiDelete } from "@/lib/api";
import { ArrowLeft, GitBranch, User, Film, Pencil } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { AudioPlayer } from "@/components/story/AudioPlayer";
import { GameMenu } from "@/components/story/GameMenu";
import { StoryGraph } from "@/components/story/StoryGraph";

const API = "http://localhost:8101";

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

function RelationshipsModal({
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
            const colorClasses =
              REL_TYPE_COLORS[rel.type] ?? "bg-gray-600/30 text-gray-400 border-gray-600/40";
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

  const [selectedCharacter, setSelectedCharacter] = useState<Character | null>(null);
  const [charEditing, setCharEditing] = useState(false);
  const [charEditName, setCharEditName] = useState("");
  const [charEditPersonality, setCharEditPersonality] = useState("");
  const [charEditPhysical, setCharEditPhysical] = useState("");
  const [charEditBackstory, setCharEditBackstory] = useState("");

  // Modal states
  const [graphModal, setGraphModal] = useState(false);
  const [endingsModal, setEndingsModal] = useState(false);
  const [editImageModal, setEditImageModal] = useState(false);
  const [portraitsModal, setPortraitsModal] = useState(false);
  const [portraitChar, setPortraitChar] = useState<Character | null>(null);
  const [portraitRegenLoading, setPortraitRegenLoading] = useState(false);
  const [portraitEditPrompt, setPortraitEditPrompt] = useState("");
  const [portraitEditModal, setPortraitEditModal] = useState(false);
  const [portraitEditLoading, setPortraitEditLoading] = useState(false);
  const [portraitExportLoading, setPortraitExportLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [outfitName, setOutfitName] = useState("");
  const [outfitDesc, setOutfitDesc] = useState("");
  const [outfitLoading, setOutfitLoading] = useState(false);
  const [regenConfirm, setRegenConfirm] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);
  const [relationshipsModal, setRelationshipsModal] = useState(false);
  const [recapModal, setRecapModal] = useState(false);

  // Replay modal state
  const [replayModal, setReplayModal] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayNodes, setReplayNodes] = useState<StoryNode[]>([]);

  // Auto-play state
  const [autoPlay, setAutoPlay] = useState(false);

  // Modal data
  const [graphEdges, setGraphEdges] = useState<{ parent_id: string; choice_text: string; child_id: string | null }[]>([]);
  const [endingsList, setEndingsList] = useState<string[]>([]);
  const [editPrompt, setEditPrompt] = useState("");
  const [ttsLoading, setTtsLoading] = useState(false);
  const [recapTtsLoading, setRecapTtsLoading] = useState(false);
  const [pathNodes, setPathNodes] = useState<{ id: string; chosen_choice_id: string | null }[]>([]);

  // Track which nodes we've already auto-shown the recap for
  const recapShownForNode = useRef<string | null>(null);

  // Auto-trigger recap when a new node has recap_text and settings allow it
  useEffect(() => {
    if (!currentNode?.recap_text || !currentNode?.id) return;
    if (recapShownForNode.current === currentNode.id) return;
    if (recapModal) return;

    const autoRecap = settings?.auto_recap_enabled ?? true;
    const resumeRecap = settings?.resume_recap_enabled ?? true;

    if (autoRecap || resumeRecap) {
      recapShownForNode.current = currentNode.id;
      setRecapModal(true);
    }
  }, [currentNode?.id, currentNode?.recap_text, settings?.auto_recap_enabled, settings?.resume_recap_enabled, recapModal]);

  // Fetch node path when current node changes
  useEffect(() => {
    if (!gameId || !currentNode) { setPathNodes([]); return; }
    (async () => {
      try {
        const nodes = await apiGet<{ id: string; chosen_choice_id: string | null }[]>(
          `/api/games/${gameId}/path?target_node_id=${currentNode.id}`
        );
        setPathNodes(nodes);
      } catch { setPathNodes([]); }
    })();
  }, [gameId, currentNode?.id]);

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

  const handleRecapReadAloud = useCallback(async () => {
    if (!currentNode) return;
    setRecapTtsLoading(true);
    try {
      const result = await useGameStore.getState().generateTts(gameId, currentNode.id);
      const audio = new Audio(`${API}${result.audio_url}`);
      audio.play().catch(() => {});
    } catch {
      /* silently fail */
    } finally {
      setRecapTtsLoading(false);
    }
  }, [gameId, currentNode]);

  const handleExportBook = useCallback(async () => {
    try {
      await useGameStore.getState().exportBook(gameId);
      // Trigger browser download of the exported book
      window.open(`${API}/api/games/${gameId}/export-book/download`, "_blank");
    } catch (err) {
      setExportResult(`Export failed: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  }, [gameId]);

  const handlePortraitRegen = useCallback(async (charId: string) => {
    setPortraitRegenLoading(true);
    try {
      await apiPost(`/api/images/${gameId}/portrait/${charId}/retry`);
      await useGameStore.getState().refreshGame(gameId);
      setToastMessage("Portrait regenerated");
    } catch (err) {
      setToastMessage(`Failed: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setPortraitRegenLoading(false);
      setTimeout(() => setToastMessage(null), 3000);
    }
  }, [gameId]);

  const handlePortraitEditSubmit = useCallback(async () => {
    if (!portraitChar || !portraitEditPrompt.trim()) return;
    setPortraitEditLoading(true);
    try {
      await apiPost(`/api/images/${gameId}/portrait/${portraitChar.id}/edit`, {
        prompt: portraitEditPrompt,
        mode: "full",
        use_current_as_ref: false,
      });
      await useGameStore.getState().refreshGame(gameId);
      setPortraitEditModal(false);
      setToastMessage("Portrait updated");
    } catch (err) {
      setToastMessage(`Failed: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setPortraitEditLoading(false);
      setTimeout(() => setToastMessage(null), 3000);
    }
  }, [gameId, portraitChar, portraitEditPrompt]);

  const handlePortraitExport = useCallback(async (char: Character) => {
    setPortraitExportLoading(true);
    try {
      await apiPost("/api/characters", {
        name: char.name,
        backstory: char.backstory,
        personality: char.personality,
        physical_description: char.physical_description,
        portrait_prompt: char.portrait_prompt ?? "",
        save_id: gameId,
        save_title: currentGame?.theme.title ?? "",
        character_id: char.id,
      });
      setToastMessage(`${char.name} exported to library`);
    } catch (err) {
      setToastMessage(`Export failed: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setPortraitExportLoading(false);
      setTimeout(() => setToastMessage(null), 3000);
    }
  }, [gameId, currentGame?.theme.title]);

  const handleGoBack = useCallback(() => {
    if (currentNode?.parent_id) {
      useGameStore.getState().jumpToNode(currentNode.parent_id);
    }
  }, [currentNode?.parent_id]);

  const handleViewReplay = useCallback(async () => {
    if (!gameId || !currentNode) return;
    try {
      const nodes = await apiGet<StoryNode[]>(
        `/api/games/${gameId}/path?target_node_id=${currentNode.id}`
      );
      setReplayNodes(nodes);
      setReplayIndex(0);
      setReplayModal(true);
    } catch {
      /* silently fail */
    }
  }, [gameId, currentNode]);

  // Keyboard navigation for replay modal
  useEffect(() => {
    if (!replayModal) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        setReplayIndex((i) => Math.min(i + 1, replayNodes.length - 1));
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setReplayIndex((i) => Math.max(i - 1, 0));
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [replayModal, replayNodes.length]);

  // Prune handler — refresh game data after pruning from the graph
  const handlePrune = useCallback(async () => {
    await useGameStore.getState().refreshGame(gameId);
    // Re-fetch graph edges so the graph updates
    try {
      const data = await useGameStore.getState().fetchGraph(gameId);
      setGraphEdges(data.edges);
    } catch {
      /* graph refresh is best-effort */
    }
  }, [gameId]);

  // Auto-play: pick a random choice after a 3-second delay
  useEffect(() => {
    if (!autoPlay) return;
    if (isStreaming || !currentNode || currentNode.is_ending) return;
    const choices = currentNode.choices ?? [];
    if (choices.length === 0) return;
    const timer = setTimeout(() => {
      // Re-check conditions at fire time since they may have changed
      const state = useGameStore.getState();
      if (state.isLoading || !state.currentNode) return;
      if (state.currentNode.is_ending) {
        setAutoPlay(false);
        return;
      }
      const currentChoices = state.currentNode.choices ?? [];
      if (currentChoices.length === 0) {
        setAutoPlay(false);
        return;
      }
      const randomIdx = Math.floor(Math.random() * currentChoices.length);
      advanceChoice(currentChoices[randomIdx].id);
    }, 3000);
    return () => clearTimeout(timer);
  }, [autoPlay, isStreaming, currentNode, advanceChoice]);

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
                <span className="text-gray-600">|</span>
                <span>
                  ${(currentGame.total_image_cost_usd ?? 0).toFixed(4)} &middot;{" "}
                  {(currentGame.text_total_input_tokens ?? 0).toLocaleString()}&uarr;/{" "}
                  {(currentGame.text_total_output_tokens ?? 0).toLocaleString()}&darr; tok
                </span>
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
              autoPlay={autoPlay}
              onToggleAutoPlay={() => setAutoPlay((p) => !p)}
              onRetryImage={handleRetryImage}
              onEditImage={handleEditImage}
              onRegenerateNode={() => setRegenConfirm(true)}
              onGoBack={handleGoBack}
              onViewGraph={handleViewGraph}
              onViewEndings={handleViewEndings}
              onViewPortraits={() => setPortraitsModal(true)}
              onReadAloud={handleReadAloud}
              onExportBook={handleExportBook}
              onViewReplay={handleViewReplay}
              onViewRelationships={() => setRelationshipsModal(true)}
              onViewRecap={() => setRecapModal(true)}
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
        onClose={() => {
          setSelectedCharacter(null);
          setCharEditing(false);
        }}
        title={charEditing ? "Edit Character" : (selectedCharacter?.name ?? "Character")}
      >
        {selectedCharacter && (
          <>
            {/* Portrait */}
            <div className="flex justify-center mb-4">
              <div
                className="w-24 h-24 rounded-xl border border-gray-700 flex items-center justify-center overflow-hidden"
                style={{ backgroundColor: "#828181" }}
              >
                {selectedCharacter.portrait_path && gameId ? (
                  <img
                    src={`${API}/api/images/${gameId}/portrait/${selectedCharacter.id}`}
                    alt={selectedCharacter.name}
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
                      useGameStore.getState().updateCharacter(selectedCharacter.id, {
                        name: charEditName,
                        personality: charEditPersonality,
                        physical_description: charEditPhysical,
                        backstory: charEditBackstory,
                      });
                      // Refresh selectedCharacter from the updated store
                      const updated = useGameStore.getState().characters.find((c) => c.id === selectedCharacter.id);
                      if (updated) setSelectedCharacter(updated);
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
                <div className="flex justify-end pt-2">
                  <button
                    onClick={() => {
                      setCharEditName(selectedCharacter.name);
                      setCharEditPersonality(selectedCharacter.personality);
                      setCharEditPhysical(selectedCharacter.physical_description);
                      setCharEditBackstory(selectedCharacter.backstory);
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
                onPrune={handlePrune}
                gameId={gameId}
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
      <Modal open={portraitsModal} onClose={() => { setPortraitsModal(false); setPortraitChar(null); }} title={portraitChar ? portraitChar.name : "Character Portraits"}>
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
                onClick={() => handlePortraitRegen(portraitChar.id)}
                disabled={portraitRegenLoading}
                className="w-full px-4 py-2.5 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center justify-center gap-2 text-sm"
              >
                {portraitRegenLoading ? (
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
                  setPortraitEditPrompt(portraitChar.portrait_prompt ?? portraitChar.physical_description);
                  setPortraitEditModal(true);
                }}
                disabled={portraitRegenLoading}
                className="w-full px-4 py-2.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-200 rounded-lg border border-gray-600/50 transition-colors flex items-center justify-center gap-2 text-sm"
              >
                <Pencil size={14} />
                Edit Portrait
              </button>

              <button
                onClick={() => handlePortraitExport(portraitChar)}
                disabled={portraitExportLoading}
                className="w-full px-4 py-2.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-200 rounded-lg border border-gray-600/50 transition-colors flex items-center justify-center gap-2 text-sm"
              >
                {portraitExportLoading ? (
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
              <p><span className="text-gray-400">Personality:</span> {portraitChar.personality}</p>
              <p><span className="text-gray-400">Appearance:</span> {portraitChar.physical_description}</p>
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
                              await apiPost(`/api/images/${gameId}/portrait/${portraitChar.id}/outfit/${o.id}/set`);
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
                            await apiDelete(`/api/images/${gameId}/portrait/${portraitChar.id}/outfit/${o.id}`);
                            await useGameStore.getState().refreshGame(gameId);
                            const updated = (portraitChar.outfits ?? []).filter(x => x.id !== o.id);
                            const reverted = portraitChar.current_outfit_id === o.id
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
                    await apiPost(`/api/images/${gameId}/portrait/${portraitChar.id}/outfit/revert`);
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
                      await apiPost(`/api/images/${gameId}/portrait/${portraitChar.id}/outfit`, {
                        name: outfitName,
                        description: outfitDesc,
                      });
                      await useGameStore.getState().refreshGame(gameId);
                      setOutfitName("");
                      setOutfitDesc("");
                      setToastMessage("Outfit created");
                      setTimeout(() => setToastMessage(null), 3000);
                    } catch (err) {
                      setToastMessage(`Failed: ${err instanceof Error ? err.message : "Unknown"}`);
                      setTimeout(() => setToastMessage(null), 3000);
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

      {/* Portrait Edit Prompt Modal */}
      <Modal open={portraitEditModal} onClose={() => setPortraitEditModal(false)} title="Edit Portrait Prompt">
        <textarea
          value={portraitEditPrompt}
          onChange={(e) => setPortraitEditPrompt(e.target.value)}
          rows={5}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm text-gray-200 resize-none focus:outline-none focus:border-cyan-500"
        />
        <div className="flex justify-end gap-3 mt-4">
          <button
            onClick={() => setPortraitEditModal(false)}
            className="px-4 py-2 text-gray-400 hover:text-gray-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handlePortraitEditSubmit}
            disabled={portraitEditLoading || !portraitEditPrompt.trim()}
            className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center gap-2"
          >
            {portraitEditLoading && (
              <span className="inline-block w-3 h-3 rounded-full bg-white animate-pulse" />
            )}
            Regenerate
          </button>
        </div>
      </Modal>

      {/* Toast notification */}
      {toastMessage && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-200 z-50 animate-in fade-in duration-150">
          {toastMessage}
        </div>
      )}

      {/* Relationships Modal */}
      <RelationshipsModal
        open={relationshipsModal}
        onClose={() => setRelationshipsModal(false)}
        relationships={currentGame.relationships}
        characters={characters}
      />

      {/* Recap Modal */}
      <Modal
        open={recapModal}
        onClose={() => setRecapModal(false)}
        title="Previously on..."
      >
        <div className="max-h-[60vh] overflow-y-auto">
          <div className="prose-story text-gray-200 leading-relaxed">
            <ReactMarkdown>{currentNode?.recap_text ?? ""}</ReactMarkdown>
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-4">
          <button
            onClick={handleRecapReadAloud}
            disabled={recapTtsLoading || !currentNode?.recap_text}
            className="flex items-center gap-2 px-4 py-2 text-sm text-cyan-400 border border-cyan-400/50 hover:bg-cyan-400/10 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {recapTtsLoading ? (
              <span className="inline-block w-3 h-3 rounded-full bg-cyan-400 animate-pulse" />
            ) : (
              <span>Read Aloud</span>
            )}
          </button>
          <button
            onClick={() => setRecapModal(false)}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg border border-gray-600/50 transition-colors"
          >
            Close
          </button>
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

      {/* Replay Modal — full screen */}
      {replayModal && replayNodes.length > 0 && (() => {
        const node = replayNodes[replayIndex];
        const hasImage = node.image_status === "done" || !!node.image_path;
        return (
          <div className="fixed inset-0 z-50 bg-gray-950 flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
              <div className="flex items-center gap-3">
                <Film size={16} className="text-cyan-400" />
                <h2 className="text-sm font-medium text-gray-300">Replay</h2>
                <span className="text-xs text-gray-500">
                  Beat {replayIndex + 1} of {replayNodes.length}
                </span>
              </div>
              <button
                onClick={() => setReplayModal(false)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-auto flex flex-col items-center justify-center p-6 gap-6">
              <div className="max-w-2xl w-full">
                <p className="text-gray-200 leading-relaxed whitespace-pre-wrap text-sm">
                  {node.narration}
                </p>
              </div>
              {hasImage && (
                <div className="max-w-lg w-full">
                  <img
                    src={`${API}/api/images/${gameId}/scene/${node.id}`}
                    alt="Scene illustration"
                    className="w-full rounded-lg border border-gray-700"
                  />
                </div>
              )}
            </div>

            {/* Navigation */}
            <div className="flex items-center justify-center gap-4 px-4 py-3 border-t border-gray-800">
              <button
                onClick={() => setReplayIndex((i) => Math.max(i - 1, 0))}
                disabled={replayIndex === 0}
                className="px-4 py-2 text-sm text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg border border-gray-700/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                Previous
              </button>
              <button
                onClick={() => {
                  const target = replayNodes[replayIndex];
                  setReplayModal(false);
                  useGameStore.getState().jumpToNode(target.id);
                }}
                className="px-4 py-2 text-sm text-cyan-400 border border-cyan-400/50 hover:bg-cyan-400/10 rounded-lg transition-colors"
              >
                Jump to Live
              </button>
              <button
                onClick={() => setReplayIndex((i) => Math.min(i + 1, replayNodes.length - 1))}
                disabled={replayIndex === replayNodes.length - 1}
                className="px-4 py-2 text-sm text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg border border-gray-700/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        );
      })()}
    </GameLayout>
  );
}
