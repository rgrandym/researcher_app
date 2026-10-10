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
let timer: ReturnType<typeof setTimeout> | null = null;

// Whether the live link is up, for the header's status indicator.
export type SocketState = "open" | "connecting" | "closed";
const stateListeners = new Set<(s: SocketState) => void>();
let state: SocketState = "connecting";
function setState(next: SocketState): void {
  state = next;
  for (const l of stateListeners) l(next);
}
export function socketState(): SocketState {
  return state;
}
export function onSocketState(listener: (s: SocketState) => void): () => void {
  stateListeners.add(listener);
  return () => stateListeners.delete(listener);
}

/** Drop the link and open it again at once, instead of waiting out the back-off. */
export function reconnect(): void {
  if (timer) clearTimeout(timer);
  timer = null;
  retry = 500;
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
  connect();
}

function connect(): void {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  setState("connecting");
  ws = new WebSocket(`${proto}://${window.location.host}/api/ws/session?token=${encodeURIComponent(TOKEN)}`);
  ws.onopen = () => {
    retry = 500;
    setState("open");
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
    setState("closed");
    timer = setTimeout(connect, retry);
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
