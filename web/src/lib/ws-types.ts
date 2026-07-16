/** WebSocket event types for real-time game updates. */

// ---------------------------------------------------------------------------
// Client → Server events
// ---------------------------------------------------------------------------

export interface ClientPing {
  type: "ping";
}

export interface ClientAdvance {
  type: "advance";
  game_id: string;
  choice_id: string;
}

export type ClientEvent = ClientPing | ClientAdvance;

// ---------------------------------------------------------------------------
// Server → Client events
// ---------------------------------------------------------------------------

export interface ServerNarrationDelta {
  type: "narration_delta";
  node_id: string;
  text: string;
}

export interface ServerBeatCommitted {
  type: "beat_committed";
  node_id: string;
  is_ending: boolean;
  choices: { id: string; text: string; child_node_id: string | null }[];
}

export interface ServerImageStatus {
  type: "image_status";
  node_id: string;
  status: "not_planned" | "generating" | "done" | "failed";
}

export interface ServerImageCommitted {
  type: "image_committed";
  node_id: string;
  image_path: string;
}

export interface ServerImageFailed {
  type: "image_failed";
  node_id: string;
  error: string;
}

export interface ServerNewCharacters {
  type: "new_characters";
  characters: {
    id: string;
    name: string;
    backstory: string;
    personality: string;
    physical_description: string;
    portrait_path: string | null;
  }[];
}

export interface ServerError {
  type: "error";
  message: string;
}

export interface ServerPong {
  type: "pong";
}

export type ServerEvent =
  | ServerNarrationDelta
  | ServerBeatCommitted
  | ServerImageStatus
  | ServerImageCommitted
  | ServerImageFailed
  | ServerNewCharacters
  | ServerError
  | ServerPong;
