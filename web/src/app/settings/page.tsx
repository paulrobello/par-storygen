"use client";

import { useState, useEffect } from "react";
import { GameLayout } from "@/components/layout/GameLayout";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { useSettingsStore } from "@/stores/settings-store";
import { Save } from "lucide-react";
import type { SettingsResponse } from "@/lib/api";

const TEXT_PROVIDERS = [
  { label: "OpenAI", value: "openai" },
  { label: "OpenRouter", value: "openrouter" },
  { label: "Ollama (local)", value: "ollama" },
];

const IMAGE_PROVIDERS = [
  { label: "OpenAI gpt-image", value: "openai" },
  { label: "Google Gemini", value: "gemini" },
  { label: "Z.AI GLM-image", value: "zai" },
  { label: "Ollama (local)", value: "ollama" },
];

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center justify-between py-2 cursor-pointer group">
      <span className="text-sm text-gray-300 group-hover:text-gray-200">{label}</span>
      <button
        onClick={() => onChange(!checked)}
        className={`
          w-10 h-5 rounded-full transition-all duration-200 relative
          ${checked ? "bg-cyan-600" : "bg-gray-700"}
        `}
      >
        <div
          className={`
            absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all duration-200
            ${checked ? "left-5.5" : "left-0.5"}
          `}
        />
      </button>
    </label>
  );
}

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

function InputField({ value, onChange, label, type = "text", placeholder }: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  type?: string;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-xs text-gray-500 uppercase mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500/50"
      />
    </div>
  );
}

export default function SettingsPage() {
  const { settings, isLoading, error, updateSettings } = useSettingsStore();
  const loadSettings = useSettingsStore((s) => s.loadSettings);
  const [form, setForm] = useState<SettingsResponse | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  useEffect(() => {
    if (settings && !form) {
      setForm(settings);
    }
  }, [settings, form]);

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    await updateSettings(form);
    setSaving(false);
  };

  const update = <K extends keyof SettingsResponse>(key: K, value: SettingsResponse[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  if (isLoading && !form) {
    return (
      <GameLayout>
        <div className="flex-1 flex items-center justify-center">
          <Loading text="Loading settings..." />
        </div>
      </GameLayout>
    );
  }

  if (!form) {
    return (
      <GameLayout>
        <div className="flex-1 flex items-center justify-center text-gray-500">
          Unable to load settings. Make sure the backend is running.
        </div>
      </GameLayout>
    );
  }

  return (
    <GameLayout>
      <div className="flex-1 px-4 py-8 max-w-2xl mx-auto w-full">
        <h1 className="text-2xl font-bold text-gray-100 mb-6">⚙️ Settings</h1>

        {error && (
          <p className="text-red-400 bg-red-900/20 p-3 rounded-lg mb-4">{error}</p>
        )}

        <div className="space-y-8">
          {/* Text Provider */}
          <section className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-200">Text Provider</h2>
            <SelectField
              label="Provider"
              value={form.text_provider.provider}
              onChange={(v) => update("text_provider", { ...form.text_provider, provider: v })}
              options={TEXT_PROVIDERS}
            />
            <InputField
              label="Model"
              value={form.text_provider.model}
              onChange={(v) => update("text_provider", { ...form.text_provider, model: v })}
              placeholder="gpt-4o-mini"
            />
            <InputField
              label="Base URL (optional)"
              value={form.text_provider.base_url ?? ""}
              onChange={(v) => update("text_provider", { ...form.text_provider, base_url: v || null })}
              placeholder="https://api.openai.com/v1"
            />
          </section>

          {/* Image Provider */}
          <section className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-200">Image Provider</h2>
            <SelectField
              label="Provider"
              value={form.image_provider.provider}
              onChange={(v) => update("image_provider", { ...form.image_provider, provider: v })}
              options={IMAGE_PROVIDERS}
            />
            <InputField
              label="Model"
              value={form.image_provider.model}
              onChange={(v) => update("image_provider", { ...form.image_provider, model: v })}
              placeholder="gpt-image-2"
            />
            <SelectField
              label="Fallback Provider"
              value={form.image_provider.fallback_provider || "none"}
              onChange={(v) => update("image_provider", {
                ...form.image_provider,
                fallback_provider: v === "none" ? "" : v,
              })}
              options={[{ label: "None", value: "none" }, ...IMAGE_PROVIDERS]}
            />
          </section>

          {/* Toggles */}
          <section className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-2">
            <h2 className="text-lg font-semibold text-gray-200 mb-4">Preferences</h2>
            <Toggle
              label="Art Generation Enabled"
              checked={form.art_enabled}
              onChange={(v) => update("art_enabled", v)}
            />
            <Toggle
              label="Branch Prefetch"
              checked={form.prefetch_enabled}
              onChange={(v) => update("prefetch_enabled", v)}
            />
            <Toggle
              label="Prefetch Images"
              checked={form.prefetch_images_enabled}
              onChange={(v) => update("prefetch_images_enabled", v)}
            />
            <Toggle
              label="Image Streaming"
              checked={form.image_streaming_enabled}
              onChange={(v) => update("image_streaming_enabled", v)}
            />
            <Toggle
              label="Auto-Recap"
              checked={form.auto_recap_enabled}
              onChange={(v) => update("auto_recap_enabled", v)}
            />
            <Toggle
              label="Resume Recap"
              checked={form.resume_recap_enabled}
              onChange={(v) => update("resume_recap_enabled", v)}
            />
          </section>

          {/* Save Button */}
          <div className="flex justify-end">
            <Button
              onClick={handleSave}
              disabled={saving}
              variant="neon"
              size="lg"
            >
              <Save size={16} className="mr-2" />
              {saving ? "Saving..." : "Save Settings"}
            </Button>
          </div>
        </div>
      </div>
    </GameLayout>
  );
}
