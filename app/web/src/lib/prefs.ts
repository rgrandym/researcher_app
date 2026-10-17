// Interface preferences: theme, agent view, which side panels are open. Kept in the app's
// settings on the backend, because the backend takes a new port at every launch and the
// browser's own storage is per port, so it would start empty each time. Loaded once
// before the first render (main.tsx); a change is saved at once.

import { api } from "./api";

export interface Prefs {
  theme: string;
  agents_view: "cards" | "lanes";
  sidebar_open: boolean;
  activity_open: boolean;
  run_panel_open: boolean;
  // Side panels' widths, as shares of the window (components/Panel.tsx).
  panel_widths?: Record<string, number>;
  figures_open?: boolean;
}

const DEFAULTS: Prefs = { theme: "system", agents_view: "lanes", sidebar_open: true, activity_open: true, run_panel_open: true };
let current: Prefs = { ...DEFAULTS };

export async function loadPrefs(): Promise<Prefs> {
  try {
    const s = await Promise.race([
      api.get<{ ui?: Partial<Prefs> }>("/api/settings"),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timeout")), 1500)),
    ]);
    current = { ...DEFAULTS, ...(s.ui ?? {}) };
    if (current.agents_view !== "cards") current.agents_view = "lanes";
  } catch {
    current = { ...DEFAULTS };
  }
  return current;
}

export function prefs(): Prefs {
  return current;
}

export function setPref<K extends keyof Prefs>(key: K, value: Prefs[K]): void {
  current = { ...current, [key]: value };
  void api.put("/api/settings", { ui: current }).catch(() => {
    /* not saved; the choice still holds for this window */
  });
}
