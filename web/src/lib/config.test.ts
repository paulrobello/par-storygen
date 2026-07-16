// ARC-015 / ARC-016: tests for the centralized web config module.
//
// Pins the single-source-of-truth contract: API_BASE reads
// NEXT_PUBLIC_API_BASE (falling back to the dev default), and WS_BASE is
// derived from API_BASE by swapping the scheme. A regression here would
// re-introduce the eight-file hard-coded-port bug ARC-016 removed.

import { describe, it, expect } from "vitest";
import { API_BASE, WS_BASE } from "./config";

describe("config", () => {
  it("API_BASE defaults to the dev API server on :8101", () => {
    // NEXT_PUBLIC_API_BASE is unset in the vitest environment, so the default
    // branch fires. This is the same default `make api-dev` serves.
    expect(API_BASE).toBe("http://localhost:8101");
  });

  it("WS_BASE derives ws:// from an http:// API_BASE", () => {
    expect(WS_BASE).toBe("ws://localhost:8101");
  });

  it("WS_BASE preserves the host and port from API_BASE", () => {
    // Splitting on "://" confirms only the scheme swapped; the authority is
    // carried through unchanged so a custom NEXT_PUBLIC_API_BASE like
    // "https://storygen.example.com:8443" produces the matching wss:// base.
    const [, apiAuthority] = API_BASE.split("://");
    const [, wsAuthority] = WS_BASE.split("://");
    expect(wsAuthority).toBe(apiAuthority);
  });

  it("WS_BASE uses the ws:// scheme when API_BASE is http://", () => {
    expect(WS_BASE.startsWith("ws://")).toBe(true);
    expect(WS_BASE.startsWith("wss://")).toBe(false);
  });
});
