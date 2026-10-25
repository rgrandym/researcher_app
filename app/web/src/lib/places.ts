// Where the author was in each project: the tab, the file, the HTML style and zoom, the
// open side panel, the scroll position of every pane, and any unsaved text in the editor.
// A project view unmounts when the author goes to Workspace, Models or another view; this
// keeps its place, and saves it with the app's settings (lib/prefs) a moment after each
// change, so the next session opens where this one left off.

import { prefs, setPref } from "./prefs";

export interface Draft {
  text: string;
  original: string;
  mtime: number | null;
}

export type SidePanel = "appearance" | "comments" | "figures" | null;

export interface Place {
  tab?: "document" | "chat" | "html" | "edit" | "file";
  selected?: string;
  editPath?: string;
  doc?: string;
  style?: string;
  cite?: boolean;
  zoom?: number;
  panel?: SidePanel;
  editComments?: boolean;
  scroll: Record<string, number>;
  drafts: Record<string, Draft>;
}

const places = new Map<string, Place>();
const MAX_DRAFT = 2_000_000;

// A popped-out editor window keeps no places of its own: the main window saves them.
const saving = !new URL(window.location.href).searchParams.has("popout");
let timer: ReturnType<typeof setTimeout> | undefined;

function save(): void {
  if (!saving) return;
  clearTimeout(timer);
  timer = setTimeout(flush, 1200);
}

function flush(): void {
  clearTimeout(timer);
  timer = undefined;
  const all: Record<string, Place> = { ...(prefs().places ?? {}) };
  for (const [run, p] of places) {
    const drafts = Object.fromEntries(Object.entries(p.drafts).filter(([, d]) => d.text.length <= MAX_DRAFT));
    all[run] = { ...p, drafts };
  }
  setPref("places", all);
}

// The last changes reach the settings even when the window closes within the delay.
window.addEventListener("pagehide", () => {
  if (timer !== undefined) flush();
});

export function place(run: string): Place {
  let p = places.get(run);
  if (!p) {
    const stored = prefs().places?.[run];
    p = { ...stored, scroll: { ...(stored?.scroll ?? {}) }, drafts: { ...(stored?.drafts ?? {}) } };
    places.set(run, p);
  }
  return p;
}

export function remember(run: string, patch: Partial<Omit<Place, "scroll" | "drafts">>): void {
  Object.assign(place(run), patch);
  save();
}

export function rememberScroll(run: string, key: string, top: number): void {
  place(run).scroll[key] = top;
  save();
}

export function rememberDraft(run: string, path: string, draft: Draft | null): void {
  const drafts = place(run).drafts;
  const had = path in drafts;
  if (draft && draft.text !== draft.original) drafts[path] = draft;
  else delete drafts[path];
  if (had || path in drafts) save();
}

/** Forget a project's place, when the project is removed. */
export function forget(run: string): void {
  places.delete(run);
  const all = { ...(prefs().places ?? {}) };
  if (run in all) {
    delete all[run];
    setPref("places", all);
  }
}
