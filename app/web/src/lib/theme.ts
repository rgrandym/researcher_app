import { prefs, setPref } from "./prefs";

// The app's colour themes. Every colour in the interface is a CSS variable (index.css),
// so a theme is a set of values chosen by `data-theme` on <html>. "system" sets no
// attribute and follows macOS light and dark. The choice is kept in this app window's
// settings on the backend (lib/prefs.ts).

export interface Theme {
  id: string;
  label: string;
  swatch: [string, string]; // background, accent: for the picker
}

export const THEMES: Theme[] = [
  { id: "system", label: "Match system", swatch: ["#faf9f7", "#1c1b19"] },
  { id: "light", label: "Claude light", swatch: ["#faf9f7", "#b5562f"] },
  { id: "dark", label: "Claude dark", swatch: ["#1c1b19", "#e08158"] },
  { id: "light-cb", label: "Light, colour-blind friendly", swatch: ["#fafafa", "#2b62b8"] },
  { id: "dark-cb", label: "Dark, colour-blind friendly", swatch: ["#17181b", "#79a8f2"] },
  { id: "slate", label: "Slate", swatch: ["#f6f7f9", "#2f6fd0"] },
  { id: "midnight", label: "Midnight", swatch: ["#0f1419", "#5ea1ff"] },
  { id: "contrast", label: "High contrast", swatch: ["#000000", "#ffb000"] },
];

export function storedTheme(): string {
  const t = prefs().theme;
  return THEMES.some((x) => x.id === t) ? t : "system";
}

export function applyTheme(id: string, save = true): void {
  const root = document.documentElement;
  if (id === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", id);
  if (save) setPref("theme", id);
}
