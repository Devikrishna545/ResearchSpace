"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { parseThemePreference, resolveTheme, THEME_STORAGE_KEY, type ThemePreference } from "@/lib/utils/theme";

type ThemeContextValue = { preference: ThemePreference; setPreference: (value: ThemePreference) => void };
const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>("system");
  const active = useRef<ThemePreference>("system");
  const media = useRef<MediaQueryList | null>(null);

  useEffect(() => {
    media.current = window.matchMedia("(prefers-color-scheme: dark)");
    let stored: string | null = null;
    try { stored = window.localStorage.getItem(THEME_STORAGE_KEY); } catch { /* Storage may be unavailable. */ }
    active.current = parseThemePreference(stored);
    setPreferenceState(active.current);
    document.documentElement.dataset.theme = resolveTheme(active.current, media.current.matches);
    const onSystemChange = () => {
      if (active.current === "system") {
        document.documentElement.dataset.theme = resolveTheme("system", media.current?.matches ?? false);
      }
    };
    const onStorageChange = (event: StorageEvent) => {
      if (event.key !== THEME_STORAGE_KEY) return;
      active.current = parseThemePreference(event.newValue);
      setPreferenceState(active.current);
      document.documentElement.dataset.theme = resolveTheme(active.current, media.current?.matches ?? false);
    };
    media.current.addEventListener("change", onSystemChange);
    window.addEventListener("storage", onStorageChange);
    return () => {
      media.current?.removeEventListener("change", onSystemChange);
      window.removeEventListener("storage", onStorageChange);
    };
  }, []);

  function setPreference(value: ThemePreference) {
    active.current = value;
    setPreferenceState(value);
    document.documentElement.dataset.theme = resolveTheme(value, media.current?.matches ?? window.matchMedia("(prefers-color-scheme: dark)").matches);
    try { window.localStorage.setItem(THEME_STORAGE_KEY, value); } catch { /* Keep the in-memory preference. */ }
  }

  return <ThemeContext.Provider value={{ preference, setPreference }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme requires ThemeProvider");
  return value;
}
