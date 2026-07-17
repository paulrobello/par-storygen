// ARC-015: vitest setup. Runs before every test file.
//
// 1. Registers jest-dom matchers (toBeInTheDocument, toHaveLength, etc.) —
//    not used by every test but cheap to load and expected by @testing-library.
// 2. Installs a deterministic MockWebSocket on the global so useWebSocket.ts
//    (which calls `new WebSocket(url)`) can be driven from tests without a
//    real server. jsdom does not ship a WebSocket implementation; without
//    this mock, `new WebSocket(...)` throws at hook time.

import "@testing-library/jest-dom/vitest";

// --- MockWebSocket -----------------------------------------------------------
// A minimal WebSocket stub: records instances so tests can grab the latest one
// and fire onmessage / onclose / onerror callbacks. `readyState` mirrors the
// real WebSocket constants so the hook's `readyState === WebSocket.OPEN` guard
// in `send()` resolves true.

type WSHandler = ((ev: MessageEvent | Event) => void) | null;

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readyState: number = MockWebSocket.OPEN;
  url: string;
  // SEC-102: the subprotocols the client offered (e.g. ["bearer.<token>"]).
  // Models the real WebSocket's second constructor argument so tests can
  // assert on it; unused by existing tests.
  protocols: string[] = [];
  onopen: WSHandler = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;

  constructor(url: string, protocols: string | string[] = []) {
    this.url = url;
    this.protocols = Array.isArray(protocols) ? [...protocols] : [protocols];
    MockWebSocket.instances.push(this);
  }
  send(_data: string): void {
    // no-op; tests drive the server→client direction via onmessage
  }
  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }
  // Test helpers (not on the real WebSocket) — fire callbacks synchronously.
  __receive(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
  __close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }
}

// Install on the global so `new WebSocket(...)` in the hook finds it.
(globalThis as unknown as { WebSocket: typeof MockWebSocket }).WebSocket = MockWebSocket;

export { MockWebSocket };
