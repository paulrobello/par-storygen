"use client";

import { useEffect } from "react";
import { useSettingsStore } from "@/stores/settings-store";

export function useSettings() {
  const settings = useSettingsStore((s) => s.settings);
  const isLoading = useSettingsStore((s) => s.isLoading);
  const error = useSettingsStore((s) => s.error);
  const loadSettings = useSettingsStore((s) => s.loadSettings);
  const updateSettings = useSettingsStore((s) => s.updateSettings);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  return { settings, isLoading, error, updateSettings, reload: loadSettings };
}
