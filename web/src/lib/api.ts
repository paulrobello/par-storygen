/** Typed fetch wrapper for the par-storygen FastAPI backend. */

// SEC-008 / ARC-016: API base is configurable via NEXT_PUBLIC_API_BASE so the
// frontend doesn't hard-code a port. Default matches `make api-dev` (:8101).
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8101";

// ---------------------------------------------------------------------------
// Domain types matching the FastAPI / Python models
// ---------------------------------------------------------------------------

export type NodeId = string;
export type CharacterId = string;
export type NarrationStyle = "first_person" | "third_person" | "fourth_wall";
export type Pacing = "slow" | "moderate" | "fast";
export type ReaderLevel = "ages_0_5" | "ages_6_10" | "ages_11_15" | "ages_15_plus";
export type ImageStatus = "not_planned" | "generating" | "done" | "failed";

export interface Theme {
  title: string;
  setting: string;
  premise: string;
  keywords: string[];
}

export interface Tone {
  preset: string;
  custom_descriptor: string | null;
}

export interface CharacterOutfit {
  id: string;
  name: string;
  description: string;
  portrait_path: string;
  portrait_prompt: string;
  created_at: string;
}

export interface Character {
  id: CharacterId;
  name: string;
  backstory: string;
  backstory_summary: string | null;
  personality: string;
  physical_description: string;
  portrait_path: string | null;
  portrait_prompt: string | null;
  introduced_at_node_id: NodeId;
  outfits: CharacterOutfit[];
  current_outfit_id: string | null;
  reference_image_path: string | null;
}

export interface Relationship {
  char_a_id: CharacterId;
  char_b_id: CharacterId;
  type: string;
  strength: number;
  context: string;
  updated_at_node_id: NodeId;
}

export interface Choice {
  id: string;
  text: string;
}

export interface StoredChoice extends Choice {
  child_node_id: NodeId | null;
}

export interface StoryNode {
  id: NodeId;
  parent_id: string | null;
  chosen_choice_id: string | null;
  chosen_at: string | null;
  narration: string;
  choices: StoredChoice[];
  is_major: boolean;
  is_ending: boolean;
  image_prompt: string | null;
  image_path: string | null;
  image_status: ImageStatus;
  illustration_reasoning: string | null;
  featured_character_ids: CharacterId[];
  summary_to_here: string | null;
  recap_text: string | null;
  tts_audio_path: string | null;
  created_at: string;
}

export interface TextProviderConfig {
  provider: string;
  model: string;
  base_url: string | null;
}

export interface ImageProviderConfig {
  provider: string;
  model: string;
  base_url: string | null;
}

export interface GameSave {
  version: number;
  id: string;
  theme: Theme;
  tone: Tone;
  narration_style: NarrationStyle;
  art_style: string;
  target_major_beats: number;
  reader_level: ReaderLevel;
  pacing: Pacing;
  text_config: TextProviderConfig;
  image_config: ImageProviderConfig;
  character_image_config: ImageProviderConfig;
  characters: Character[];
  relationships: Relationship[];
  nodes: Record<NodeId, StoryNode>;
  root_node_id: NodeId;
  current_node_id: NodeId;
  endings_reached: NodeId[];
  total_image_cost_usd: number;
  text_total_input_tokens: number;
  text_total_output_tokens: number;
  text_total_requests: number;
  text_calls_by_model: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export interface GameSummary {
  id: string;
  title: string;
  updated_at: string;
  node_count: number;
  is_ending: boolean;
  has_cover: boolean;
}

export interface LibraryCharacter {
  id: string;
  name: string;
  backstory: string;
  personality: string;
  physical_description: string;
  portrait_prompt: string;
  exported_at: string;
  source: string;
  has_portrait: boolean;
  reference_image_path?: string | null;
}

export interface CharacterLibraryResponse {
  characters: LibraryCharacter[];
}

// Alias for consistency with import endpoint
export type CharacterLibraryEntry = LibraryCharacter;

export interface PortraitRegenerateRequest {
  art_style?: string;
}

export interface PortraitEditRequest {
  prompt: string;
  mode: "edit" | "full";
  use_current_as_ref: boolean;
  art_style?: string;
}

export interface CharacterCreateRequest {
  concept: string;
  name?: string;
}

export interface StoryImportRequest {
  save_id: string;
  character_ids: string[];
}

export interface StoryImportResponse {
  imported: CharacterLibraryEntry[];
}

export interface SettingsResponse {
  text_provider: TextProviderConfig;
  image_provider: ImageProviderConfig & {
    fallback_provider: string;
    fallback_model: string;
  };
  character_image_provider: ImageProviderConfig;
  wizard_defaults: {
    theme: string;
    tone_preset: string;
    tone_descriptor: string;
    narration_style: string;
    art_style: string;
    target_major_beats: number;
    reader_level: ReaderLevel;
    pacing: Pacing;
    characters: string;
    save_to_catalog: boolean;
  };
  tts_prefs: {
    provider: string;
    voice: string;
    auto_read: boolean;
    auto_read_recap: boolean;
  };
  art_enabled: boolean;
  prefetch_enabled: boolean;
  prefetch_images_enabled: boolean;
  image_streaming_enabled: boolean;
  llm_cache_enabled: boolean;
  auto_select_enabled: boolean;
  auto_open_art_enabled: boolean;
  auto_recap_enabled: boolean;
  resume_recap_enabled: boolean;
  recap_interval: number;
  graphics_mode: string;
}

export interface WizardThemeResponse {
  theme: Theme;
}

export interface WizardCharactersResponse {
  characters: Character[];
}

export interface CreateGameResponse {
  game_id: string;
}

export interface AdvanceResponse {
  node: StoryNode;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text().catch(() => "Unknown error");
    throw new Error(`API ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  return handleResponse<T>(res);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(res);
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<T>(res);
}

export async function apiPostForm<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", body: formData });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
}

// ---------------------------------------------------------------------------
// Image URL helper
// ---------------------------------------------------------------------------

export function imageUrl(gameId: string, imagePath: string): string {
  return `${API_BASE}/api/games/${gameId}/images/${imagePath}`;
}

export function characterPortraitUrl(libraryId: string, portraitPath: string): string {
  return `${API_BASE}/api/library/${libraryId}/${portraitPath}`;
}
