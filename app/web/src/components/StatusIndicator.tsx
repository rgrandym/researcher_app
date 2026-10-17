import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { RefreshCw, Square } from "lucide-react";
import { api } from "../lib/api";
import { clock } from "../lib/format";
import { onSocketState, reconnect, send, socketState, type SocketState } from "../lib/socket";
import type { Connection, SessionSummary } from "../lib/types";

// The header's health light: the app's own backend and live link, and each model
// connection. Green when everything answers; amber while reconnecting or when a model's
// window is used up; red when the backend does not answer or a connection is unusable.
// The panel behind it reconnects the live link and re-checks each connection on demand.

type Tone = "good" | "warn" | "bad";

function connectionTone(c: Connection): { tone: Tone; text: string } {
  if (!c.installed) return { tone: "bad", text: "not installed" };
  if (!c.signed_in) return { tone: "bad", text: c.message || "not signed in" };
  const full = c.usage?.windows.find((w) => w.status === "rejected" || (w.used_percent ?? 0) >= 100);
  if (full) return { tone: "warn", text: `${full.name} limit reached${full.resets_at ? `, resets ${clock(full.resets_at)}` : ""}` };
  return { tone: "good", text: "ready" };
}

const DOT: Record<Tone, string> = { good: "bg-good", warn: "bg-warn", bad: "bg-bad" };

export default function StatusIndicator() {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState<SocketState>(socketState());
  const [checking, setChecking] = useState<string | null>(null);
  useEffect(() => onSocketState(setLink), []);
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<{ ok: boolean; stale?: boolean; running?: boolean }>("/api/health"),
    refetchInterval: 10_000,
    retry: false,
  });
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api.get<Connection[]>("/api/connections"), refetchInterval: 60_000 });

  const backendUp = health.isSuccess && !health.isError;
  const appTone: Tone = !backendUp ? "bad" : link === "open" ? "good" : "warn";
  const usable = (conns.data ?? []).filter((c) => c.installed && (c.billing === "plan" || c.signed_in));
  const tones = usable.map((c) => connectionTone(c).tone);
  const overall: Tone = appTone === "bad" || (tones.length > 0 && tones.every((t) => t === "bad")) ? "bad" : appTone === "warn" || tones.includes("bad") || tones.includes("warn") ? "warn" : "good";
  const stale = Boolean(health.data?.stale);
  const [restarting, setRestarting] = useState("");
  const [reconnectResult, setReconnectResult] = useState("");
  const [reconnecting, setReconnecting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState("");
  const stopAll = async () => {
    setStopping(true);
    setStopError("");
    try {
      try {
        await api.post("/api/stop-all");
      } catch (error) {
        if ((error as { status?: number }).status !== 404) throw error;
        // A turn started before this endpoint was installed still understands the
        // existing per-session Stop message. Keep that turn's backend running.
        const sessions = await api.get<SessionSummary[]>("/api/sessions");
        for (const session of sessions.filter((s) => s.running)) {
          send({ type: "stop", session: session.id });
        }
      }
      void client.invalidateQueries({ queryKey: ["health"] });
      void client.invalidateQueries({ queryKey: ["sessions"] });
    } catch (error) {
      setStopError((error as Error).message || "Could not stop the turns.");
    } finally {
      setStopping(false);
    }
  };
  const restart = async () => {
    setRestarting("Restarting…");
    try {
      await api.post("/api/restart");
      // The backend comes back on the same address; the live link reconnects by itself.
      setTimeout(() => {
        reconnect();
        void health.refetch();
        setRestarting("");
      }, 2500);
    } catch (e) {
      setRestarting((e as Error).message || "Restart failed");
    }
  };
  const label = appTone === "bad" ? "Offline" : appTone === "warn" ? "Reconnecting" : stale ? "Update ready" : overall === "good" ? "Connected" : "Check connections";
  const shown: Tone = stale && overall === "good" ? "warn" : overall;

  const check = async (id: string) => {
    setChecking(id);
    try {
      await api.post(`/api/connections/${id}/test`);
      await client.invalidateQueries({ queryKey: ["connections"] });
      setReconnectResult("Model status refreshed.");
    } catch (error) {
      setReconnectResult((error as Error).message || "Model check failed.");
    } finally {
      setChecking(null);
    }
  };
  const reconnectAll = async () => {
    setReconnecting(true);
    setReconnectResult("");
    reconnect();
    try {
      const state = await health.refetch();
      if (state.isError) {
        setReconnectResult("The app backend is unavailable. Reopen Research to start it.");
        return;
      }
      const fresh = await api.get<Connection[]>("/api/connections?fresh=true");
      client.setQueryData(["connections"], fresh);
      setReconnectResult("App reached. Model status refreshed below.");
    } catch (error) {
      setReconnectResult((error as Error).message || "Connection check failed.");
    } finally {
      setReconnecting(false);
    }
  };

  return (
    <div className="relative flex items-center gap-1">
      {health.data?.running && (
        <button onClick={() => void stopAll()} disabled={stopping} title="Stop every running agent turn" className="flex items-center gap-1 rounded-md border border-bad/60 px-2 py-1 text-[0.75rem] text-bad hover:bg-bad/10 disabled:opacity-50">
          <Square size="0.6875rem" fill="currentColor" /> {stopping ? "Stopping…" : "Stop all"}
        </button>
      )}
      {stopError && <span className="max-w-32 truncate text-[0.6875rem] text-bad" title={stopError}>{stopError}</span>}
      <button onClick={() => setOpen(!open)} title="Connection status" className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[0.75rem] text-muted hover:bg-panel hover:text-fg">
        <span className="relative flex h-2 w-2">
          {shown !== "good" && <span className={clsx("absolute inline-flex h-full w-full animate-ping rounded-full opacity-60", DOT[shown])} />}
          <span className={clsx("relative inline-flex h-2 w-2 rounded-full", DOT[shown])} />
        </span>
        {label}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-50 mt-1 w-[19rem] rounded-lg border border-border bg-surface p-3 text-[0.75rem] shadow-xl">
            <div className="flex items-center gap-2">
              <span className={clsx("h-2 w-2 shrink-0 rounded-full", DOT[appTone])} />
              <span className="font-medium">App</span>
              <span className="text-faint">{!backendUp ? "the backend does not answer" : link === "open" ? "live" : "link reconnecting"}</span>
              <button onClick={() => void reconnectAll()} disabled={reconnecting} className="ml-auto flex items-center gap-1 rounded-md border border-border px-2 py-0.5 hover:border-accent disabled:opacity-50">
                <RefreshCw size="0.6875rem" className={clsx(reconnecting && "animate-spin")} /> Reconnect
              </button>
            </div>
            {backendUp && <button onClick={() => window.location.reload()} className="mt-2 text-[0.6875rem] text-muted underline hover:text-fg">Reload window to use interface updates</button>}
            {reconnectResult && <div className="mt-1 text-[0.6875rem] text-faint">{reconnectResult}</div>}
            {!backendUp && <div className="mt-1 text-[0.6875rem] text-faint">Reopen Research from the Dock if the backend stays offline.</div>}
            {stale && backendUp && (
              <div className="mt-2 flex items-center gap-2 rounded-md border border-warn/50 px-2 py-1.5">
                <span className="min-w-0 flex-1 text-[0.6875rem]">
                  {health.data?.running
                    ? "Reload the window for interface changes. Backend changes can load when the turn finishes."
                    : "The app was updated. Restart its backend to use the new version."}
                </span>
                <button onClick={() => health.data?.running ? window.location.reload() : void restart()} disabled={Boolean(restarting)} className="shrink-0 rounded-md bg-accent px-2 py-0.5 text-white disabled:opacity-50">
                  {health.data?.running ? "Reload window" : "Restart"}
                </button>
              </div>
            )}
            {restarting && <div className="mt-1 text-[0.6875rem] text-faint">{restarting}</div>}
            <div className="mb-1 mt-3 text-[0.625rem] font-medium uppercase tracking-wide text-faint">Models</div>
            {(conns.data ?? []).map((c) => {
              const t = connectionTone(c);
              return (
                <div key={c.id} className="flex items-center gap-2 py-0.5">
                  <span className={clsx("h-2 w-2 shrink-0 rounded-full", DOT[t.tone])} />
                  <span className="min-w-0 flex-1 truncate" title={t.text}>
                    {c.label} <span className="text-faint">· {t.text}</span>
                  </span>
                  <button onClick={() => void check(c.id)} disabled={checking === c.id} className="flex items-center gap-1 rounded-md border border-border px-2 py-0.5 hover:border-accent disabled:opacity-50">
                    <RefreshCw size="0.6875rem" className={clsx(checking === c.id && "animate-spin")} /> Check
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
