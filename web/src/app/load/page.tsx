"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GameLayout } from "@/components/layout/GameLayout";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { apiGet, apiDelete } from "@/lib/api";
import type { GameSummary } from "@/lib/api";
import { Trash2, Play, BookOpen } from "lucide-react";

const API_BASE = "http://localhost:8101";

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
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => confirmDelete(game, e)}
                      className="text-gray-500 hover:text-red-400"
                    >
                      <Trash2 size={14} />
                    </Button>
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
    </GameLayout>
  );
}
