import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { clock } from "../lib/format";
import { onSocketState, reconnect, socketState, type SocketState } from "../lib/socket";
import type { Connection } from "../lib/types";

// The header's health light: the app's own backend and live link, and each model
// connection. Green when everything answers; amber while reconnecting or when a model's
// window is used up; red when the backend does not answer or a connection is unusable.
// The panel behind it reconnects the live link and re-checks each connection on demand.

type Tone = "good" | "warn" | "bad";

function connectionTone(c: Connection): { tone: Tone; text: string } {
  if (!c.installed) return { tone: "bad", text: "not installed" };
  if (!c.signed_in) return { tone: "bad", text: c.message || "not signed in" };
  const full = c.usage?.windows.find((w) => (w.used_percent ?? 0) >= 100);
  if (full) return { tone: "warn", text: `${full.name} window used up${full.resets_at ? `, resets ${clock(full.resets_at)}` : ""}` };
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
  const usable = (conns.data ?? []).filter((c) => c.installed);
  const tones = usable.map((c) => connectionTone(c).tone);
  const overall: Tone = appTone === "bad" || (tones.length > 0 && tones.every((t) => t === "bad")) ? "bad" : appTone === "warn" || tones.includes("bad") || tones.includes("warn") ? "warn" : "good";
  const stale = Boolean(health.data?.stale);
  const [restarting, setRestarting] = useState("");
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
    } finally {
      setChecking(null);
    }
  };
  const reconnectAll = async () => {
    reconnect();
    await health.refetch();
    await client.invalidateQueries({ queryKey: ["connections"] });
  };

  return (
    <div className="relative">
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
              <button onClick={() => void reconnectAll()} className="ml-auto flex items-center gap-1 rounded-md border border-border px-2 py-0.5 hover:border-accent">
                <RefreshCw size="0.6875rem" /> Reconnect
              </button>
            </div>
            {!backendUp && <div className="mt-1 text-[0.6875rem] text-faint">If this stays red, quit Research from the Dock and open it again.</div>}
            {stale && backendUp && (
              <div className="mt-2 flex items-center gap-2 rounded-md border border-warn/50 px-2 py-1.5">
                <span className="min-w-0 flex-1 text-[0.6875rem]">
                  The app was updated. Restart its backend to use the new version{health.data?.running ? " once the running turn finishes" : ""}.
                </span>
                <button onClick={() => void restart()} disabled={Boolean(restarting) || health.data?.running} className="shrink-0 rounded-md bg-accent px-2 py-0.5 text-white disabled:opacity-50">
                  Restart
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
