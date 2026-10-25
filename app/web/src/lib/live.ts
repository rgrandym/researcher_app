// Messages between the app's windows: the main window and an editor popped out into its
// own window (another screen). Both are pages of this app, so a BroadcastChannel reaches
// every open one. The editor sends its unsaved text as it changes, and the HTML view in the
// main window renders it; a click on a comment in either window finds it in the other.

import { TOKEN, q } from "./api";
import type { Draft } from "./places";

export type LiveMessage =
  | { type: "draft"; run: string; path: string; text: string; dirty: boolean }
  | { type: "saved"; run: string; path: string }
  | { type: "popout-ready"; run: string; path: string }
  | { type: "handoff"; run: string; path: string; draft: Draft | null }
  | { type: "popout-closed"; run: string; path: string; draft: Draft | null }
  | { type: "popout-ping"; run: string }
  | { type: "popout-here"; run: string; path: string }
  | { type: "return"; run: string; path: string }
  | { type: "focus-comment"; run: string; id: string; to: "html" | "editor" }
  | { type: "comments-changed"; run: string };

let channel: BroadcastChannel | null | undefined;

function open(): BroadcastChannel | null {
  if (channel === undefined) {
    try {
      channel = new BroadcastChannel("research-live");
    } catch {
      channel = null; // no channel: each window still works on its own
    }
  }
  return channel;
}

export function post(message: LiveMessage): void {
  open()?.postMessage(message);
}

export function listen(handler: (message: LiveMessage) => void): () => void {
  const ch = open();
  if (!ch) return () => undefined;
  const onMessage = (e: MessageEvent<LiveMessage>) => handler(e.data);
  ch.addEventListener("message", onMessage);
  return () => ch.removeEventListener("message", onMessage);
}

/** The popped-out editor's address. The token rides along: a new window has no session yet. */
export function openPopout(run: string, path: string): Window | null {
  const url = `/?${q({ token: TOKEN, popout: "edit", run, path })}`;
  return window.open(url, `research-edit-${run}-${path}`, "popup,width=980,height=1000");
}

export interface PopoutTarget {
  run: string;
  path: string;
}

/** Set when this window is a popped-out editor (read once, before the token leaves the URL). */
export const POPOUT: PopoutTarget | null = (() => {
  const params = new URL(window.location.href).searchParams;
  const run = params.get("run");
  const path = params.get("path");
  return params.get("popout") === "edit" && run && path ? { run, path } : null;
})();
