"use client";

import { create } from "zustand";
import type { SettingsResponse } from "@/lib/api";
import { apiGet, apiPut } from "@/lib/api";

interface SettingsState {
  settings: SettingsResponse | null;
  isLoading: boolean;
  error: string | null;

  loadSettings: () => Promise<void>;
  updateSettings: (settings: SettingsResponse) => Promise<void>;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  settings: null,
  isLoading: false,
  error: null,

  loadSettings: async () => {
    set({ isLoading: true, error: null });
    try {
      const settings = await apiGet<SettingsResponse>("/api/settings");
      set({ settings, isLoading: false });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to load settings",
      });
    }
  },

  updateSettings: async (settings: SettingsResponse) => {
    set({ isLoading: true, error: null });
    try {
      await apiPut<SettingsResponse>("/api/settings", settings);
      set({ settings, isLoading: false });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to save settings",
      });
    }
  },
}));
