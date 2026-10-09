import { create } from "zustand";
import { prefs, setPref } from "../lib/prefs";
import type { AppEvent } from "../lib/types";

export type View =
  | { kind: "home" }
  | { kind: "session"; id: string }
  | { kind: "run"; name: string; file?: string }
  | { kind: "exports" }
  | { kind: "workspace"; path?: string }
  | { kind: "models" };

interface UiState {
  view: View;
  tab: "research" | "guide";
  events: Record<string, AppEvent[]>;
  running: Record<string, boolean>;
  errors: Record<string, string>;
  activityOpen: boolean;
  // The connection the next message goes to, per session (or "new" for the home bar).
  nextConnection: Record<string, string>;
  // The view before the current one, for the close button of Workspace and Models.
  previous: View;
  setView: (view: View) => void;
  close: () => void;
  setTab: (tab: "research" | "guide") => void;
  loadEvents: (sid: string, events: AppEvent[]) => void;
  addEvent: (sid: string, event: AppEvent) => void;
  setRunning: (sid: string, running: boolean) => void;
  setError: (sid: string, text: string) => void;
  toggleActivity: () => void;
  setNextConnection: (sid: string, conn: string) => void;
}

export const useUi = create<UiState>((set) => ({
  view: { kind: "home" },
  previous: { kind: "home" },
  tab: "research",
  events: {},
  running: {},
  errors: {},
  activityOpen: prefs().activity_open,
  nextConnection: {},
  setView: (view) =>
    set((s) => ({
      view,
      tab: "research",
      // Panels do not become a place to return to.
      previous: s.view.kind === "workspace" || s.view.kind === "models" ? s.previous : s.view,
    })),
  close: () => set((s) => ({ view: s.previous, tab: "research" })),
  setTab: (tab) => set({ tab }),
  // The stored transcript, plus any live events newer than its last one.
  loadEvents: (sid, events) =>
    set((s) => {
      const last = events.length ? events[events.length - 1].ts : 0;
      const live = (s.events[sid] ?? []).filter((e) => e.ts > last);
      return { events: { ...s.events, [sid]: [...events, ...live] } };
    }),
  addEvent: (sid, event) => set((s) => ({ events: { ...s.events, [sid]: [...(s.events[sid] ?? []), event] } })),
  setRunning: (sid, running) => set((s) => ({ running: { ...s.running, [sid]: running } })),
  setError: (sid, text) => set((s) => ({ errors: { ...s.errors, [sid]: text } })),
  toggleActivity: () =>
    set((s) => {
      setPref("activity_open", !s.activityOpen);
      return { activityOpen: !s.activityOpen };
    }),
  setNextConnection: (sid, conn) => set((s) => ({ nextConnection: { ...s.nextConnection, [sid]: conn } })),
}));
