"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GameLayout } from "@/components/layout/GameLayout";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { Modal } from "@/components/ui/Modal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { apiGet, apiDelete, apiPost } from "@/lib/api";
import type { GameSummary, GameSave } from "@/lib/api";
import { Trash2, Play, BookOpen, RefreshCw, Info } from "lucide-react";

const API_BASE = "http://localhost:8101";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2 border-b border-gray-700/50 pb-1">
        {title}
      </h3>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="text-gray-500 w-32 flex-shrink-0">{label}</span>
      <span className="text-cyan-300">{value}</span>
    </div>
  );
}

export default function LoadPage() {
  const router = useRouter();
  const [games, setGames] = useState<GameSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchGames() {
      try {
        const result = await apiGet<{ games: GameSummary[] }>('/api/games');
        setGames(result.games);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load games");
      } finally {
        setIsLoading(false);
      }
    }
    fetchGames();
  }, []);

  const [deleteTarget, setDeleteTarget] = useState<GameSummary | null>(null);
  const [detailsGameId, setDetailsGameId] = useState<string | null>(null);
  const [detailsData, setDetailsData] = useState<GameSave | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  const openDetails = async (gameId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDetailsGameId(gameId);
    setDetailsLoading(true);
    setDetailsData(null);
    try {
      const data = await apiGet<GameSave>(`/api/games/${gameId}`);
      setDetailsData(data);
    } catch {
      setDetailsGameId(null);
    } finally {
      setDetailsLoading(false);
    }
  };

  const closeDetails = () => {
    setDetailsGameId(null);
    setDetailsData(null);
  };

  const confirmDelete = (game: GameSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteTarget(game);
  };
  const cancelDelete = () => setDeleteTarget(null);
  const executeDelete = async () => {
    if (!deleteTarget) return;
    try {
      await apiDelete(`/api/games/${deleteTarget.id}`);
      setGames((prev) => prev.filter((g) => g.id !== deleteTarget.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setDeleteTarget(null);
    }
  };

  return (
    <GameLayout>
      <div className="flex-1 px-4 py-8 max-w-4xl mx-auto w-full">
        <h1 className="text-2xl font-bold text-gray-100 mb-6">📂 Load Story</h1>

        {isLoading && <Loading text="Loading saves..." />}
        {error && (
          <p className="text-red-400 bg-red-900/20 p-3 rounded-lg">{error}</p>
        )}

        {!isLoading && games.length === 0 && (
          <div className="text-center py-16 text-gray-500">
            <p className="text-lg mb-2">No saved games found</p>
            <p className="text-sm">Start a new adventure from the menu!</p>
          </div>
        )}

        <div className="flex flex-col gap-4">
          {games.map((game) => (
            <Card
              key={game.id}
              onClick={() => router.push(`/play/${game.id}`)}
              className="group relative overflow-hidden"
            >
              <div className="flex gap-4">
                {/* Cover Art */}
                <div className="flex-shrink-0 relative rounded-lg overflow-hidden h-[120px]" style={{ backgroundColor: '#828181' }}>
                  {game.has_cover ? (
                    <img
                      src={`${API_BASE}/api/images/${game.id}/scene/root`}
                      alt={game.title}
                      className="h-full w-auto object-contain"
                    />
                  ) : (
                    <div className="w-[160px] h-full flex items-center justify-center">
                      <BookOpen size={32} className="text-gray-600" />
                    </div>
                  )}
                  {/* Hover overlay */}
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100">
                    <div className="flex items-center gap-2 text-white text-sm font-medium">
                      <Play size={16} />
                      Continue
                    </div>
                  </div>
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0 py-1">
                  <div className="flex items-start justify-between mb-2">
                    <h3 className="text-cyan-400 font-semibold text-lg leading-tight">{game.title}</h3>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={async (e) => {
                          e.stopPropagation();
                          try {
                            await apiPost(`/api/images/${game.id}/cover/regenerate`);
                            // Refresh games list to update cover status
                            const result = await apiGet<{ games: GameSummary[] }>('/api/games');
                            setGames(result.games);
                          } catch { /* ignore */ }
                        }}
                        className="text-gray-500 hover:text-cyan-400"
                        title="Regenerate cover art"
                      >
                        <RefreshCw size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => openDetails(game.id, e)}
                        className="text-gray-500 hover:text-cyan-400"
                        title="View details"
                      >
                        <Info size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => confirmDelete(game, e)}
                        className="text-gray-500 hover:text-red-400"
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-500">
                    <span>{game.node_count} nodes</span>
                    <span>{new Date(game.updated_at).toLocaleDateString()}</span>
                    {game.is_ending && (
                      <span className="px-1.5 py-0.5 bg-amber-900/30 text-amber-400 rounded">
                        Complete
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>
      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete Save"
        message={`Permanently delete "${deleteTarget?.title ?? "this save"}"? This cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={executeDelete}
        onCancel={cancelDelete}
      />

      {/* Save Details Modal */}
      <Modal
        open={!!detailsGameId}
        onClose={closeDetails}
        title={detailsData?.theme.title ?? "Loading..."}
        maxWidth="max-w-3xl"
      >
        {detailsLoading && <Loading text="Loading details..." />}
        {detailsData && !detailsLoading && (
          <div className="space-y-5 max-h-[70vh] overflow-y-auto pr-1">
            {/* Theme */}
            <Section title="Theme">
              <Row label="Setting" value={detailsData.theme.setting} />
              <Row label="Premise" value={detailsData.theme.premise} />
              <Row label="Keywords" value={detailsData.theme.keywords.join(", ")} />
            </Section>

            {/* Tone & Style */}
            <Section title="Tone & Style">
              <Row label="Tone Preset" value={detailsData.tone.preset} />
              {detailsData.tone.custom_descriptor && (
                <Row label="Custom Descriptor" value={detailsData.tone.custom_descriptor} />
              )}
              <Row label="Narration Style" value={detailsData.narration_style.replace(/_/g, " ")} />
              <Row label="Art Style" value={detailsData.art_style} />
              <Row label="Target Beats" value={String(detailsData.target_major_beats)} />
              <Row label="Reader Level" value={detailsData.reader_level.replace(/_/g, " ")} />
              <Row label="Pacing" value={detailsData.pacing} />
            </Section>

            {/* Characters */}
            <Section title={`Characters (${detailsData.characters.length})`}>
              <div className="flex flex-wrap gap-2">
                {detailsData.characters.map((c) => (
                  <span
                    key={c.id}
                    className="px-2 py-1 bg-cyan-900/30 text-cyan-300 rounded text-sm"
                  >
                    {c.name}
                  </span>
                ))}
              </div>
            </Section>

            {/* Stats */}
            <Section title="Stats">
              <Row label="Nodes" value={String(Object.keys(detailsData.nodes).length)} />
              <Row label="Endings Reached" value={String(detailsData.endings_reached.length)} />
              <Row label="Image Cost" value={`$${detailsData.total_image_cost_usd.toFixed(4)}`} />
              <Row label="Input Tokens" value={detailsData.text_total_input_tokens.toLocaleString()} />
              <Row label="Output Tokens" value={detailsData.text_total_output_tokens.toLocaleString()} />
              <Row label="LLM Requests" value={String(detailsData.text_total_requests)} />
            </Section>

            {/* Providers */}
            <Section title="Providers">
              <Row label="Text" value={`${detailsData.text_config.provider} / ${detailsData.text_config.model}`} />
              <Row label="Image" value={`${detailsData.image_config.provider} / ${detailsData.image_config.model}`} />
              <Row label="Character Image" value={`${detailsData.character_image_config.provider} / ${detailsData.character_image_config.model}`} />
            </Section>

            {/* Timestamps */}
            <Section title="Dates">
              <Row label="Created" value={new Date(detailsData.created_at).toLocaleString()} />
              <Row label="Updated" value={new Date(detailsData.updated_at).toLocaleString()} />
            </Section>

            <div className="pt-2 flex justify-end">
              <Button variant="secondary" size="sm" onClick={closeDetails}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </GameLayout>
  );
}
