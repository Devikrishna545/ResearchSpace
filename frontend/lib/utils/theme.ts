export type ThemePreference = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "research-assistant-theme";

export function parseThemePreference(value: string | null): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

export function resolveTheme(preference: ThemePreference, systemDark: boolean): "light" | "dark" {
  return preference === "system" ? systemDark ? "dark" : "light" : preference;
}

export function accountInitials(email: string): string {
  const local = email.split("@")[0] ?? "";
  const words = local.split(/[._+-]+/).filter(Boolean);
  return (words.length > 1 ? words.slice(0, 2).map((word) => word[0]).join("") : local.slice(0, 2)).toUpperCase() || "?";
}

export const themeBootstrapScript = `(function () {
  var choice = "system";
  try {
    var saved = localStorage.getItem("${THEME_STORAGE_KEY}");
    if (saved === "light" || saved === "dark") choice = saved;
  } catch (error) {}
  var systemDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = choice === "system" ? (systemDark ? "dark" : "light") : choice;
})();`;
