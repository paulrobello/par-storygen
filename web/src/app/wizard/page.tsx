"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { GameLayout } from "@/components/layout/GameLayout";
import { WizardStepper } from "@/components/wizard/WizardStepper";
import { Loading } from "@/components/ui/Loading";
import { apiPost } from "@/lib/api";
import type { Theme, Character, NarrationStyle, ReaderLevel, Pacing } from "@/lib/api";
import { ChevronLeft, ChevronRight, Wand2 } from "lucide-react";

const STEPS = [
  "Theme",
  "Tone",
  "Style",
  "Art",
  "Length",
  "Level",
  "Characters",
  "Confirm",
];

const TONE_PRESETS = [
  "silly",
  "serious",
  "dark",
  "whimsical",
  "mysterious",
  "romantic",
  "action",
  "unexpected",
] as const;

const READER_LEVELS: { value: ReaderLevel; label: string }[] = [
  { value: "ages_0_5", label: "Ages 0–5 (Picture Book)" },
  { value: "ages_6_10", label: "Ages 6–10 (Early Reader)" },
  { value: "ages_11_15", label: "Ages 11–15 (Young Adult)" },
  { value: "ages_15_plus", label: "Ages 15+ (Adult)" },
];

interface WizardState {
  themePrompt: string;
  theme: Theme | null;
  tonePreset: string;
  toneDescriptor: string;
  narrationStyle: NarrationStyle;
  artStyle: string;
  targetMajorBeats: number;
  readerLevel: ReaderLevel;
  pacing: Pacing;
  characters: Character[];
  characterPrompt: string;
}

const defaultWizard: WizardState = {
  themePrompt: "",
  theme: null,
  tonePreset: "serious",
  toneDescriptor: "",
  narrationStyle: "third_person",
  artStyle: "children's story book",
  targetMajorBeats: 5,
  readerLevel: "ages_11_15",
  pacing: "moderate",
  characters: [],
  characterPrompt: "",
};

export default function WizardPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>(defaultWizard);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGeneratingTheme, setIsGeneratingTheme] = useState(false);
  const [isGeneratingChars, setIsGeneratingChars] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = <K extends keyof WizardState>(key: K, value: WizardState[K]) =>
    setState((s) => ({ ...s, [key]: value }));

  const handleGenerateTheme = async () => {
    if (!state.themePrompt.trim()) return;
    setIsGeneratingTheme(true);
    setError(null);
    try {
      const result = await apiPost<{ theme: Theme }>("/api/wizard/theme", {
        prompt: state.themePrompt,
      });
      update("theme", result.theme);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate theme");
    } finally {
      setIsGeneratingTheme(false);
    }
  };

  const handleGenerateCharacters = async () => {
    if (!state.theme) return;
    setIsGeneratingChars(true);
    setError(null);
    try {
      const result = await apiPost<{ characters: Character[] }>("/api/wizard/characters", {
        theme: state.theme,
        tone: { preset: state.tonePreset, custom_descriptor: state.toneDescriptor || null },
        character_prompt: state.characterPrompt,
      });
      update("characters", result.characters);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate characters");
    } finally {
      setIsGeneratingChars(false);
    }
  };

  const handleSubmit = async () => {
    if (!state.theme) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const result = await apiPost<{ game_id: string }>("/api/games", {
        theme: state.theme,
        tone: { preset: state.tonePreset, custom_descriptor: state.toneDescriptor || null },
        narration_style: state.narrationStyle,
        art_style: state.artStyle,
        target_major_beats: state.targetMajorBeats,
        reader_level: state.readerLevel,
        pacing: state.pacing,
        characters: state.characters,
      });
      router.push(`/play/${result.game_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create game");
      setIsSubmitting(false);
    }
  };

  const canAdvance = (): boolean => {
    switch (step) {
      case 0: return !!state.theme;
      case 1: return true;
      case 2: return true;
      case 3: return state.artStyle.trim().length > 0;
      case 4: return true;
      case 5: return true;
      case 6: return state.characters.length > 0;
      case 7: return true;
      default: return false;
    }
  };

  const renderStep = () => {
    switch (step) {
      // Step 0: Theme
      case 0:
        return (
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Describe your story idea
              </label>
              <textarea
                value={state.themePrompt}
                onChange={(e) => update("themePrompt", e.target.value)}
                placeholder="A space opera about a crew of misfits on a stolen ship..."
                className="w-full h-32 bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500/50 resize-none"
              />
            </div>
            <Button onClick={handleGenerateTheme} disabled={isGeneratingTheme || !state.themePrompt.trim()}>
              <Wand2 size={16} className="mr-2" />
              {isGeneratingTheme ? "Generating..." : "Generate Theme"}
            </Button>
            {state.theme && (
              <div className="bg-gray-900/50 border border-cyan-800/30 rounded-lg p-4 space-y-2">
                <p className="text-cyan-400 font-semibold">{state.theme.title}</p>
                <p className="text-gray-300 text-sm">{state.theme.setting}</p>
                <p className="text-gray-400 text-sm italic">{state.theme.premise}</p>
                {state.theme.keywords.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {state.theme.keywords.map((kw) => (
                      <span key={kw} className="px-2 py-0.5 bg-gray-800 text-cyan-300 text-xs rounded-full">
                        {kw}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );

      // Step 1: Tone
      case 1:
        return (
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-3">
                Select a tone preset
              </label>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {TONE_PRESETS.map((tone) => (
                  <button
                    key={tone}
                    onClick={() => update("tonePreset", tone)}
                    className={`
                      px-4 py-2.5 rounded-lg border text-sm capitalize transition-all
                      ${state.tonePreset === tone
                        ? "border-cyan-400 bg-cyan-400/10 text-cyan-400"
                        : "border-gray-700 bg-gray-900 text-gray-300 hover:border-gray-600"
                      }
                    `}
                  >
                    {tone}
                  </button>
                ))}
              </div>
            </div>
            {state.tonePreset === "custom" && (
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Custom tone descriptor
                </label>
                <input
                  type="text"
                  value={state.toneDescriptor}
                  onChange={(e) => update("toneDescriptor", e.target.value)}
                  placeholder="e.g., bittersweet with moments of absurd humor"
                  className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500/50"
                />
              </div>
            )}
          </div>
        );

      // Step 2: Narration Style
      case 2:
        return (
          <div className="space-y-4">
            <label className="block text-sm font-medium text-gray-300 mb-3">
              Narration perspective
            </label>
            {(["first_person", "third_person", "fourth_wall"] as NarrationStyle[]).map(
              (style) => (
                <button
                  key={style}
                  onClick={() => update("narrationStyle", style)}
                  className={`
                    w-full text-left px-5 py-4 rounded-lg border transition-all
                    ${state.narrationStyle === style
                      ? "border-cyan-400 bg-cyan-400/10 text-cyan-300"
                      : "border-gray-700 bg-gray-900 text-gray-300 hover:border-gray-600"
                    }
                  `}
                >
                  <p className="font-semibold capitalize">
                    {style.replace("_", " ").replace("fourth wall", "Fourth Wall (breaks)")}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {style === "first_person" && "I walked into the dark forest..."}
                    {style === "third_person" && "She walked into the dark forest..."}
                    {style === "fourth_wall" && "You walk into the dark forest, dear reader..."}
                  </p>
                </button>
              )
            )}
          </div>
        );

      // Step 3: Art Style
      case 3:
        return (
          <div className="space-y-4">
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Art style for illustrations
            </label>
            <input
              type="text"
              value={state.artStyle}
              onChange={(e) => update("artStyle", e.target.value)}
              placeholder="children's story book"
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500/50"
            />
            <div className="flex flex-wrap gap-2">
              {[
                "children's story book",
                "dark fantasy oil painting",
                "anime",
                "watercolor",
                "pixel art",
                "photorealistic",
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => update("artStyle", suggestion)}
                  className="px-3 py-1 bg-gray-800 border border-gray-700 rounded-full text-xs text-gray-400 hover:border-cyan-400/50 hover:text-cyan-400 transition-all"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        );

      // Step 4: Length
      case 4:
        return (
          <div className="space-y-6">
            <label className="block text-sm font-medium text-gray-300">
              Target major beats:{" "}
              <span className="text-cyan-400 font-bold">{state.targetMajorBeats}</span>
            </label>
            <input
              type="range"
              min={2}
              max={30}
              value={state.targetMajorBeats}
              onChange={(e) => update("targetMajorBeats", Number(e.target.value))}
              className="w-full accent-cyan-400"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>Short (2)</span>
              <span>Novel (30)</span>
            </div>
          </div>
        );

      // Step 5: Reader Level
      case 5:
        return (
          <div className="space-y-4">
            <label className="block text-sm font-medium text-gray-300 mb-3">
              Target reader level
            </label>
            {READER_LEVELS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => update("readerLevel", value)}
                className={`
                  w-full text-left px-5 py-4 rounded-lg border transition-all
                  ${state.readerLevel === value
                    ? "border-cyan-400 bg-cyan-400/10 text-cyan-300"
                    : "border-gray-700 bg-gray-900 text-gray-300 hover:border-gray-600"
                  }
                `}
              >
                {label}
              </button>
            ))}
          </div>
        );

      // Step 6: Characters
      case 6:
        return (
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Additional character guidance (optional)
              </label>
              <textarea
                value={state.characterPrompt}
                onChange={(e) => update("characterPrompt", e.target.value)}
                placeholder="Include a wise old mentor and a mischievous sidekick..."
                className="w-full h-24 bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500/50 resize-none"
              />
            </div>
            <Button onClick={handleGenerateCharacters} disabled={isGeneratingChars || !state.theme}>
              <Wand2 size={16} className="mr-2" />
              {isGeneratingChars ? "Generating..." : "Generate Characters"}
            </Button>
            {state.characters.length > 0 && (
              <div className="space-y-3">
                {state.characters.map((char) => (
                  <div key={char.id} className="bg-gray-900/50 border border-gray-700/50 rounded-lg p-4">
                    <p className="text-cyan-400 font-semibold">{char.name}</p>
                    <p className="text-gray-400 text-sm mt-1">{char.personality}</p>
                    <p className="text-gray-500 text-xs mt-2 line-clamp-2">{char.backstory}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        );

      // Step 7: Confirm
      case 7:
        return (
          <div className="space-y-4">
            <h3 className="text-lg font-semibold text-gray-200 mb-4">Review Your Story</h3>
            {state.theme && (
              <div className="bg-gray-900/50 border border-gray-700/50 rounded-lg p-4 space-y-3">
                <div>
                  <span className="text-xs text-gray-500 uppercase">Title</span>
                  <p className="text-cyan-400 font-semibold">{state.theme.title}</p>
                </div>
                <div>
                  <span className="text-xs text-gray-500 uppercase">Setting</span>
                  <p className="text-gray-300 text-sm">{state.theme.setting}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <span className="text-xs text-gray-500 uppercase">Tone</span>
                    <p className="text-gray-300 text-sm capitalize">{state.tonePreset}</p>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 uppercase">Style</span>
                    <p className="text-gray-300 text-sm capitalize">{state.narrationStyle.replace("_", " ")}</p>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 uppercase">Art</span>
                    <p className="text-gray-300 text-sm">{state.artStyle}</p>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 uppercase">Length</span>
                    <p className="text-gray-300 text-sm">{state.targetMajorBeats} major beats</p>
                  </div>
                </div>
                <div>
                  <span className="text-xs text-gray-500 uppercase">Characters ({state.characters.length})</span>
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {state.characters.map((c) => (
                      <span key={c.id} className="px-2 py-0.5 bg-gray-800 text-gray-300 text-xs rounded-full">
                        {c.name}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}
            <Button
              variant="neon"
              size="lg"
              className="w-full mt-6"
              onClick={handleSubmit}
              disabled={isSubmitting}
            >
              <Wand2 size={18} className="mr-2" />
              {isSubmitting ? "Creating Story..." : "Begin Adventure"}
            </Button>
          </div>
        );
    }
  };

  if (isSubmitting) {
    return (
      <GameLayout>
        <div className="flex-1 flex items-center justify-center">
          <Loading text="Creating your adventure..." />
        </div>
      </GameLayout>
    );
  }

  return (
    <GameLayout>
      <div className="flex-1 flex flex-col items-center px-4 py-8">
        <div className="w-full max-w-xl">
          <WizardStepper steps={STEPS} currentStep={step} />

          <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-6 min-h-[400px] flex flex-col">
            <h2 className="text-xl font-semibold text-gray-200 mb-6">
              {STEPS[step]}
            </h2>

            <div className="flex-1">{renderStep()}</div>

            {error && (
              <div className="mt-4 p-3 bg-red-900/30 border border-red-800/50 rounded-lg text-red-300 text-sm">
                {error}
              </div>
            )}

            {/* Navigation */}
            <div className="flex justify-between mt-8 pt-4 border-t border-gray-800">
              <Button
                variant="ghost"
                onClick={() => setStep((s) => s - 1)}
                disabled={step === 0}
              >
                <ChevronLeft size={16} className="mr-1" />
                Back
              </Button>
              {step < STEPS.length - 1 ? (
                <Button
                  onClick={() => setStep((s) => s + 1)}
                  disabled={!canAdvance()}
                >
                  Next
                  <ChevronRight size={16} className="ml-1" />
                </Button>
              ) : (
                <div />
              )}
            </div>
          </div>
        </div>
      </div>
    </GameLayout>
  );
}
