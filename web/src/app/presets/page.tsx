"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GameLayout } from "@/components/layout/GameLayout";
import { Card } from "@/components/ui/Card";
import { Loading } from "@/components/ui/Loading";
import { apiGet } from "@/lib/api";
import { Sparkles } from "lucide-react";

interface StoryPreset {
  name: string;
  description: string;
  theme: string;
  tone_preset: string;
  tone_descriptor: string;
  narration_style: string;
  art_style: string;
  target_major_beats: number;
  reader_level: string;
  pacing: string;
  characters: string;
}

interface PresetsResponse {
  curated: StoryPreset[];
  custom: StoryPreset[];
}

export default function PresetsPage() {
  const router = useRouter();
  const [presets, setPresets] = useState<PresetsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<PresetsResponse>("/api/presets")
      .then(setPresets)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load presets"));
  }, []);

  const handleSelect = (preset: StoryPreset) => {
    router.push(`/wizard?preset=${encodeURIComponent(preset.name)}`);
  };

  return (
    <GameLayout>
      <div className="flex-1 overflow-y-auto px-4 py-8">
        <div className="max-w-3xl mx-auto space-y-8">
          {/* Header */}
          <div className="text-center">
            <h1 className="text-3xl font-bold tracking-tight mb-2">
              <span className="neon-glow-cyan text-cyan-400">Quick Start</span>
            </h1>
            <p className="text-gray-500 text-sm">
              Pick a preset and jump straight into an adventure
            </p>
          </div>

          {/* Loading */}
          {!presets && !error && <Loading text="Loading presets..." />}

          {/* Error */}
          {error && (
            <div className="p-4 bg-red-900/30 border border-red-800/50 rounded-lg text-red-300 text-sm text-center">
              {error}
            </div>
          )}

          {/* Curated Presets */}
          {presets && presets.curated.length > 0 && (
            <section className="space-y-4">
              <h2 className="text-lg font-semibold text-gray-300 flex items-center gap-2">
                <Sparkles size={18} className="text-cyan-400" />
                Curated Presets
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {presets.curated.map((preset) => (
                  <PresetCard key={preset.name} preset={preset} onSelect={handleSelect} />
                ))}
              </div>
            </section>
          )}

          {/* Custom Presets */}
          {presets && presets.custom.length > 0 && (
            <section className="space-y-4">
              <h2 className="text-lg font-semibold text-gray-300">Your Presets</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {presets.custom.map((preset) => (
                  <PresetCard key={preset.name} preset={preset} onSelect={handleSelect} />
                ))}
              </div>
            </section>
          )}

          {/* Empty state */}
          {presets && presets.curated.length === 0 && presets.custom.length === 0 && (
            <div className="text-center py-12 text-gray-500">
              <p>No presets available.</p>
              <p className="text-sm mt-1">Create a story from scratch to get started.</p>
            </div>
          )}
        </div>
      </div>
    </GameLayout>
  );
}

function PresetCard({ preset, onSelect }: { preset: StoryPreset; onSelect: (p: StoryPreset) => void }) {
  const badges: string[] = [preset.tone_preset, preset.art_style].filter(Boolean);

  return (
    <Card onClick={() => onSelect(preset)} className="space-y-2">
      <h3 className="text-cyan-400 font-bold">{preset.name}</h3>
      <p className="text-gray-400 text-sm line-clamp-2">{preset.description}</p>
      {badges.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {badges.map((badge) => (
            <span
              key={badge}
              className="px-2 py-0.5 bg-gray-800 text-gray-400 text-xs rounded-full"
            >
              {badge}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}
