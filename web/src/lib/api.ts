/** Typed fetch wrapper for the par-storygen FastAPI backend. */

// ARC-016: API_BASE lives in a single config module so every frontend route,
// hook, and component derives from one source. Re-exported here so existing
// `import { API_BASE } from "@/lib/api"` call sites keep working.
import { API_BASE, API_TOKEN } from "@/lib/config";
import type { components } from "./api-types.gen";

export { API_BASE, API_TOKEN };

// ---------------------------------------------------------------------------
// Domain types matching the FastAPI / Python models
// Types are either generated from OpenAPI or hand-written where not exposed
// ---------------------------------------------------------------------------

export type NodeId = string;
export type CharacterId = string;
export type NarrationStyle = "first_person" | "third_person" | "fourth_wall";
export type Pacing = "slow" | "moderate" | "fast";
export type ReaderLevel = "ages_0_5" | "ages_6_10" | "ages_11_15" | "ages_15_plus";
export type ImageStatus = "not_planned" | "generating" | "done" | "failed";

// Generated types from OpenAPI
export type Character = components["schemas"]["Character"];
export type CharacterOutfit = components["schemas"]["CharacterOutfit"];
export type ChoiceOption = components["schemas"]["ChoiceOption"];
export type GameSummary = components["schemas"]["GameSummary"];
export type GameDetail = components["schemas"]["GameDetail"];
export type NodeDetail = components["schemas"]["NodeDetail"];
export type CharacterLibraryEntry = components["schemas"]["CharacterLibraryEntry"];

// Hand-written types not exposed in API (internal models)
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

export interface Relationship {
  char_a_id: CharacterId;
  char_b_id: CharacterId;
  type: string;
  strength: number;
  context: string;
  updated_at_node_id: NodeId;
}

// Client-side extensions of generated types
export type Choice = ChoiceOption;
export type StoredChoice = ChoiceOption; // Already has child_node_id

// StoryNode extends NodeDetail with additional client-side fields
export interface StoryNode extends Omit<NodeDetail, "choices"> {
  choices: StoredChoice[];
  chosen_at: string | null; // Not in NodeDetail
  illustration_reasoning: string | null; // Not in NodeDetail
  featured_character_ids: CharacterId[]; // Not in NodeDetail
  recap_text: string | null; // Not in NodeDetail
  tts_audio_path: string | null; // Not in NodeDetail
}

/**
 * Field defaults for a {@link StoryNode} (QA-014).
 *
 * Used as the base layer in a defaults-spread merge so that fields the server
 * adds in the future pass through via the existing-node spread, instead of
 * being silently dropped by an explicit field-by-field reconstruction. The
 * dynamic default (``created_at``) is still applied at the call site because a
 * module-level const would freeze the timestamp at import time.
 */
export const NODE_DEFAULTS: StoryNode = {
  id: "",
  parent_id: null,
  chosen_choice_id: null,
  chosen_at: null,
  narration: "",
  choices: [],
  is_major: false,
  is_ending: false,
  image_prompt: null,
  image_path: null,
  image_status: "not_planned",
  illustration_reasoning: null,
  featured_character_ids: [],
  summary_to_here: null,
  recap_text: null,
  tts_audio_path: null,
  created_at: "",
};

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

// GameSave - keep hand-written version since generated GameDetail has incompatible structure
// The generated type has `unknown` for nested objects and different field names
// diverges from schema: API uses different field names and `unknown` for complex types
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

/**
 * Return the auth header when a bearer token is configured (SEC-102).
 *
 * Spread into every fetch wrapper's headers so a token set via
 * ``NEXT_PUBLIC_API_TOKEN`` reaches all REST calls (the API server checks it
 * via ``Authorization: Bearer <token>`` when ``STORYGEN_API_TOKEN`` is set).
 * Returns an empty object when no token is configured, preserving local-dev
 * loopback-trust behavior.
 */
export function authHeaders(): Record<string, string> {
  return API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {};
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text().catch(() => "Unknown error");
    throw new Error(`API ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}

export async function apiGet<T>(path: string): Promise<T> {
  // QA-018: read-only GETs fail fast (15 s) instead of hanging forever. The
  // cost-incurring POSTs (advance/wizard/image-generation, 60-120 s legitimate)
  // keep their default timeout. Map the timeout/abort back to the wrapper's
  // Error shape with a clear message; non-timeout errors (including
  // handleResponse's `API <status>: <text>`) propagate unchanged.
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { ...authHeaders() },
      signal: AbortSignal.timeout(15_000),
    });
    return handleResponse<T>(res);
  } catch (err) {
    if (
      err instanceof Error &&
      (err.name === "TimeoutError" || err.name === "AbortError")
    ) {
      throw new Error(`API request timed out after 15s: GET ${path}`);
    }
    throw err;
  }
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(res);
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<T>(res);
}

export async function apiPostForm<T>(path: string, formData: FormData): Promise<T> {
  // FormData: the browser sets Content-Type (multipart boundary) itself; we
  // only add the Authorization header when a token is configured.
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { ...authHeaders() },
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: { ...authHeaders() },
  });
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

/**
 * Build the scene-image URL for a node, but only when its image is ready
 * (QA-013). Returns ``null`` when ``image_status !== "done"`` so callers
 * render a placeholder/spinner instead of fetching a 404. Centralized here so
 * the ``/api/images/<game>/scene/<node>`` route shape lives in one place —
 * previously duplicated across five store sites and the WS hook.
 */
export function sceneImageUrl(
  gameId: string,
  node: Pick<StoryNode, "id" | "image_status">,
): string | null {
  if (node.image_status !== "done") return null;
  return `${API_BASE}/api/images/${gameId}/scene/${node.id}`;
}
