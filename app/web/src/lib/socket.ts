// The one WebSocket to the backend: live turn events for every session, and the
// author's send / stop / permission / switch messages. Reconnects on its own.

import { TOKEN } from "./api";
import type { AppEvent } from "./types";

export type ServerMessage =
  | { type: "event"; session: string; event: AppEvent }
  | { type: "state"; session: string; running: boolean }
  | { type: "error"; session: string; text: string }
  | { type: "pong" };

type Listener = (msg: ServerMessage) => void;

const listeners = new Set<Listener>();
let ws: WebSocket | null = null;
let queue: string[] = [];
let retry = 500;

function connect(): void {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${window.location.host}/api/ws/session?token=${encodeURIComponent(TOKEN)}`);
  ws.onopen = () => {
    retry = 500;
    for (const m of queue) ws?.send(m);
    queue = [];
    for (const l of listeners) l({ type: "state", session: "", running: false });
  };
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data as string) as ServerMessage;
      for (const l of listeners) l(msg);
    } catch {
      /* ignore malformed frames */
    }
  };
  ws.onclose = () => {
    ws = null;
    setTimeout(connect, retry);
    retry = Math.min(retry * 2, 8000);
  };
}

export function send(msg: Record<string, unknown>): void {
  const text = JSON.stringify(msg);
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(text);
  else queue.push(text);
}

export function subscribe(listener: Listener): () => void {
  if (!ws) connect();
  listeners.add(listener);
  return () => listeners.delete(listener);
}
