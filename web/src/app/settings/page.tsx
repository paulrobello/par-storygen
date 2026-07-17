"use client";

import { useState, useEffect } from "react";
import { GameLayout } from "@/components/layout/GameLayout";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { useSettingsStore } from "@/stores/settings-store";
import { Save, Palette } from "lucide-react";
import Link from "next/link";
import type { SettingsResponse } from "@/lib/api";
import { getProviders, toProviderOptions } from "@/lib/api";

// ENH-005: provider dropdowns are sourced from GET /api/providers so adding a
// provider on the backend surfaces here without a UI edit. The pre-ENH-005
// web labels for two image providers were shorter than the registry labels
// (`Google Gemini` vs `Google Gemini (Nano Banana 2/Pro)`;
// `Ollama (local)` vs `Ollama (local, macOS-only)`). To preserve the existing
// UI verbatim (zero behavior change to valid flows), we override those two
// labels via labelMap. The TUI Settings screen uses the full registry labels.
// Removing this labelMap is a follow-up that should land alongside a decision
// to converge on a single label set.
const TEXT_LABEL_MAP: Record<string, string> = {};
const IMAGE_LABEL_MAP: Record<string, string> = {
  gemini: "Google Gemini",
  ollama: "Ollama (local)",
};

const TTS_PROVIDERS = [
  { label: "OpenAI", value: "openai" },
  { label: "ElevenLabs", value: "elevenlabs" },
  { label: "Deepgram", value: "deepgram" },
  { label: "Gemini", value: "gemini" },
  { label: "Kokoro (local)", value: "kokoro" },
];

const TONE_PRESETS = [
  "silly", "serious", "dark", "whimsical", "mysterious", "romantic", "action", "unexpected",
];

const NARRATION_STYLES = [
  { label: "Third Person", value: "third_person" },
  { label: "First Person", value: "first_person" },
  { label: "Fourth Wall", value: "fourth_wall" },
];

const PACING_OPTIONS = [
  { label: "Slow", value: "slow" },
  { label: "Moderate", value: "moderate" },
  { label: "Fast", value: "fast" },
];

const READER_LEVELS = [
  { label: "Ages 0-5", value: "ages_0_5" },
  { label: "Ages 6-10", value: "ages_6_10" },
  { label: "Ages 11-15", value: "ages_11_15" },
  { label: "Ages 15+", value: "ages_15_plus" },
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
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  // ENH-005: provider option lists come from the registry. Empty until the
  // first successful fetch resolves; the page's loading gate below already
  // covers the initial paint, and SelectField tolerates an empty option list.
  const [textProviderOptions, setTextProviderOptions] = useState<
    { label: string; value: string }[]
  >([]);
  const [imageProviderOptions, setImageProviderOptions] = useState<
    { label: string; value: string }[]
  >([]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  useEffect(() => {
    let cancelled = false;
    getProviders()
      .then((registry) => {
        if (cancelled) return;
        setTextProviderOptions(
          toProviderOptions(registry.text_providers, TEXT_LABEL_MAP),
        );
        setImageProviderOptions(
          toProviderOptions(registry.image_providers, IMAGE_LABEL_MAP),
        );
      })
      .catch(() => {
        // Surface stays empty — same shape as a backend-down load. The page
        // already shows "Unable to load settings" when settings fail to
        // load, and selects simply render no options if the registry call
        // fails independently.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (settings && !form) {
      setForm(settings);
    }
  }, [settings, form]);

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    try {
      await updateSettings(form);
      setToastMessage("Settings saved");
    } catch {
      setToastMessage("Failed to save settings");
    }
    setSaving(false);
    setTimeout(() => setToastMessage(null), 3000);
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
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-8 max-w-2xl mx-auto w-full">
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
              options={textProviderOptions}
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
              options={imageProviderOptions}
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
              options={[{ label: "None", value: "none" }, ...imageProviderOptions]}
            />
            <div className="pt-2">
              <Link href="/style-gallery">
                <Button variant="ghost" size="sm">
                  <Palette size={14} className="mr-2" />
                  Open Style Gallery
                </Button>
              </Link>
            </div>
          </section>

          {/* Character Portrait Provider */}
          <section className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-200">Character Portrait Provider</h2>
            <SelectField
              label="Provider"
              value={form.character_image_provider.provider}
              onChange={(v) => update("character_image_provider", { ...form.character_image_provider, provider: v })}
              options={imageProviderOptions}
            />
            <InputField
              label="Model"
              value={form.character_image_provider.model}
              onChange={(v) => update("character_image_provider", { ...form.character_image_provider, model: v })}
              placeholder="gpt-image-2"
            />
            <InputField
              label="Base URL (optional)"
              value={form.character_image_provider.base_url ?? ""}
              onChange={(v) => update("character_image_provider", { ...form.character_image_provider, base_url: v || null })}
              placeholder="https://api.openai.com/v1"
            />
          </section>

          {/* TTS */}
          <section className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-200">Text-to-Speech</h2>
            <SelectField
              label="Provider"
              value={form.tts_prefs.provider}
              onChange={(v) => update("tts_prefs", { ...form.tts_prefs, provider: v })}
              options={TTS_PROVIDERS}
            />
            <InputField
              label="Voice"
              value={form.tts_prefs.voice}
              onChange={(v) => update("tts_prefs", { ...form.tts_prefs, voice: v })}
              placeholder="alloy"
            />
            <Toggle
              label="Auto-read story beats aloud"
              checked={form.tts_prefs.auto_read}
              onChange={(v) => update("tts_prefs", { ...form.tts_prefs, auto_read: v })}
            />
            <Toggle
              label="Auto-read recaps aloud"
              checked={form.tts_prefs.auto_read_recap}
              onChange={(v) => update("tts_prefs", { ...form.tts_prefs, auto_read_recap: v })}
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
            <Toggle
              label="LLM Cache (debug)"
              checked={form.llm_cache_enabled}
              onChange={(v) => update("llm_cache_enabled", v)}
            />
            <Toggle
              label="Auto-Select (random choices)"
              checked={form.auto_select_enabled}
              onChange={(v) => update("auto_select_enabled", v)}
            />
            <div className="pt-2">
              <InputField
                label="Recap Interval (major beats)"
                value={String(form.recap_interval)}
                onChange={(v) => {
                  const n = parseInt(v, 10);
                  if (!isNaN(n) && n > 0) update("recap_interval", n);
                }}
                type="number"
                placeholder="3"
              />
            </div>
          </section>

          {/* Wizard Defaults */}
          <section className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-200">Wizard Defaults</h2>
            <InputField
              label="Default Theme Prompt"
              value={form.wizard_defaults.theme}
              onChange={(v) => update("wizard_defaults", { ...form.wizard_defaults, theme: v })}
              placeholder="A magical adventure in a faraway land..."
            />
            <SelectField
              label="Tone Preset"
              value={form.wizard_defaults.tone_preset}
              onChange={(v) => update("wizard_defaults", { ...form.wizard_defaults, tone_preset: v })}
              options={TONE_PRESETS.map((t) => ({ label: t.charAt(0).toUpperCase() + t.slice(1), value: t }))}
            />
            <InputField
              label="Custom Tone Descriptor"
              value={form.wizard_defaults.tone_descriptor}
              onChange={(v) => update("wizard_defaults", { ...form.wizard_defaults, tone_descriptor: v })}
              placeholder="Optional custom tone..."
            />
            <SelectField
              label="Narration Style"
              value={form.wizard_defaults.narration_style}
              onChange={(v) => update("wizard_defaults", { ...form.wizard_defaults, narration_style: v })}
              options={NARRATION_STYLES}
            />
            <InputField
              label="Art Style"
              value={form.wizard_defaults.art_style}
              onChange={(v) => update("wizard_defaults", { ...form.wizard_defaults, art_style: v })}
              placeholder="children's story book"
            />
            <InputField
              label="Target Major Beats"
              value={String(form.wizard_defaults.target_major_beats)}
              onChange={(v) => {
                const n = parseInt(v, 10);
                if (!isNaN(n) && n >= 2 && n <= 30) update("wizard_defaults", { ...form.wizard_defaults, target_major_beats: n });
              }}
              type="number"
              placeholder="5"
            />
            <SelectField
              label="Reader Level"
              value={form.wizard_defaults.reader_level}
              onChange={(v) => update("wizard_defaults", { ...form.wizard_defaults, reader_level: v as SettingsResponse["wizard_defaults"]["reader_level"] })}
              options={READER_LEVELS}
            />
            <SelectField
              label="Pacing"
              value={form.wizard_defaults.pacing}
              onChange={(v) => update("wizard_defaults", { ...form.wizard_defaults, pacing: v as SettingsResponse["wizard_defaults"]["pacing"] })}
              options={PACING_OPTIONS}
            />
            <InputField
              label="Character Requirements"
              value={form.wizard_defaults.characters}
              onChange={(v) => update("wizard_defaults", { ...form.wizard_defaults, characters: v })}
              placeholder="2-3 diverse characters..."
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

      {toastMessage && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-200 z-50 animate-in fade-in duration-150">
          {toastMessage}
        </div>
      )}
    </GameLayout>
  );
}
