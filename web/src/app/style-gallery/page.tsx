"use client";

import { useState } from "react";
import Link from "next/link";
import { GameLayout } from "@/components/layout/GameLayout";
import { Button } from "@/components/ui/Button";
import { Palette, ArrowLeft, Sparkles, Clock } from "lucide-react";

const IMAGE_PROVIDERS = [
  { label: "OpenAI gpt-image", value: "openai" },
  { label: "Google Gemini", value: "gemini" },
  { label: "Z.AI GLM-image", value: "zai" },
  { label: "Ollama (local)", value: "ollama" },
];

interface ProviderConfig {
  provider: string;
  model: string;
  baseUrl: string;
}

const DEFAULT_PROMPT = "A brave knight in shining armor standing on a hilltop at sunset";

function SelectField({ value, onChange, options, label }: {
  value: string;
  onChange: (v: string) => void;
  options: { label: string; value: string }[];
  label: string;
}) {
  return (
    <div>
      <label className="block text-xs text-gray-500 uppercase mb-1">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 focus:outline-none focus:border-cyan-500/50"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function InputField({ value, onChange, label, placeholder }: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-xs text-gray-500 uppercase mb-1">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500/50"
      />
    </div>
  );
}

function ProviderColumn({
  index,
  config,
  onChange,
}: {
  index: number;
  config: ProviderConfig;
  onChange: (config: ProviderConfig) => void;
}) {
  return (
    <div className="flex-1 bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-4">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        Provider {index}
      </h3>
      <SelectField
        label="Provider"
        value={config.provider}
        onChange={(v) => onChange({ ...config, provider: v })}
        options={IMAGE_PROVIDERS}
      />
      <InputField
        label="Model"
        value={config.model}
        onChange={(v) => onChange({ ...config, model: v })}
        placeholder="gpt-image-2"
      />
      <InputField
        label="Base URL (optional)"
        value={config.baseUrl}
        onChange={(v) => onChange({ ...config, baseUrl: v })}
        placeholder="https://api.openai.com/v1"
      />

      {/* Placeholder result area */}
      <div className="mt-4 border border-dashed border-gray-700 rounded-lg p-6 flex flex-col items-center justify-center min-h-[200px] text-center">
        <div className="w-12 h-12 rounded-full bg-gray-800 flex items-center justify-center mb-3">
          <Sparkles size={20} className="text-gray-600" />
        </div>
        <p className="text-gray-600 text-sm">Image preview will appear here</p>
      </div>
    </div>
  );
}

export default function StyleGalleryPage() {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [config1, setConfig1] = useState<ProviderConfig>({
    provider: "openai",
    model: "gpt-image-2",
    baseUrl: "",
  });
  const [config2, setConfig2] = useState<ProviderConfig>({
    provider: "gemini",
    model: "gemini-2.0-flash-exp",
    baseUrl: "",
  });

  return (
    <GameLayout>
      <div className="flex-1 px-4 py-8 max-w-5xl mx-auto w-full overflow-y-auto">
        {/* Header */}
        <div className="flex items-center gap-3 mb-2">
          <Link href="/settings" className="text-gray-500 hover:text-gray-300 transition-colors">
            <ArrowLeft size={20} />
          </Link>
          <h1 className="text-2xl font-bold text-gray-100">Style Gallery</h1>
          <Palette size={20} className="text-cyan-400" />
        </div>
        <p className="text-gray-500 mb-6 ml-8">
          Compare image providers side by side to find the best style for your stories.
        </p>

        {/* Prompt */}
        <section className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 mb-6">
          <InputField
            label="Test Prompt"
            value={prompt}
            onChange={setPrompt}
            placeholder={DEFAULT_PROMPT}
          />
        </section>

        {/* Provider columns */}
        <div className="flex gap-6 mb-6">
          <ProviderColumn index={1} config={config1} onChange={setConfig1} />
          <ProviderColumn index={2} config={config2} onChange={setConfig2} />
        </div>

        {/* Generate button area */}
        <div className="flex justify-center gap-4 mb-8">
          <Button variant="neon" size="lg" disabled title="Coming soon - needs backend API support">
            <Clock size={16} className="mr-2" />
            Generate Side by Side
          </Button>
        </div>

        {/* Coming soon notice */}
        <div className="bg-gray-900/30 border border-gray-800/50 rounded-xl p-6 text-center">
          <div className="w-10 h-10 rounded-full bg-cyan-900/30 flex items-center justify-center mx-auto mb-3">
            <Sparkles size={18} className="text-cyan-400" />
          </div>
          <h3 className="text-gray-300 font-medium mb-2">Coming Soon</h3>
          <p className="text-gray-500 text-sm max-w-md mx-auto">
            Style Gallery requires a backend generation endpoint. Once the API supports
            on-demand image generation from provider configs, you will be able to generate
            images side by side and compare quality, style, and speed across providers.
          </p>
        </div>
      </div>
    </GameLayout>
  );
}
