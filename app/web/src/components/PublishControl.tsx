import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { api } from "../lib/api";

interface Proposal { id: string; title: string; destination_root: string; operations: number; invalid?: boolean; published?: string }
interface NativeBridge { messageHandlers?: { publish?: { postMessage: (body: unknown) => Promise<string> } } }

// Writing outside the workspace is done only by the desktop app, after the author has reviewed
// the exact changes and authenticated. This control asks the app to start that; it cannot write
// anything itself, and in a browser it can only list the proposals.
export default function PublishControl({ run }: { run: string }) {
  // A run writes a proposal while the window is open, so the list polls like the rest of
  // the app's panels and refreshes again the moment the author opens it.
  const proposals = useQuery({ queryKey: ["publications", run], queryFn: () => api.get<Proposal[]>(`/api/runs/${encodeURIComponent(run)}/publications`), refetchInterval: 15_000 });
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const bridge = (window as unknown as { webkit?: NativeBridge }).webkit?.messageHandlers?.publish;
  if (!proposals.data?.length) return null;
  // The backend lists the waiting proposals first. The button counts those: a published one
  // stays in the panel for reference, below, and is not work left to do.
  const waiting = proposals.data.filter((p) => !p.published);
  const done = proposals.data.filter((p) => p.published);
  const when = (iso: string) => {
    const at = new Date(iso);
    return isNaN(at.getTime()) ? "earlier" : at.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  };

  const publish = async (p: Proposal) => {
    if (!bridge) return;
    setBusy(true);
    setStatus(null);
    try {
      setStatus({ ok: true, text: await bridge.postMessage({ run, proposal: p.id }) });
    } catch (e) {
      setStatus({ ok: false, text: String((e as Error)?.message ?? e) });
    } finally {
      setBusy(false);
      void proposals.refetch();
    }
  };

  return (
    <div className="relative ml-2">
      <button onClick={() => { if (!open) void proposals.refetch(); setOpen(!open); }} title="Proposals to write files outside this project. Nothing is written until you review and authenticate." className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent">
        <Send size="0.8125rem" /> Publish ({waiting.length})
      </button>
      {open && (
        <div className="absolute left-0 top-full z-20 mt-1 w-[26rem] rounded-md border border-border bg-bg p-2 text-[0.75rem] shadow-lg">
          {!bridge && <p className="mb-2 text-warn">Publishing works only in the Research desktop app. The proposals are listed here for reference.</p>}
          {!waiting.length && <p className="mb-2 text-faint">Nothing is waiting to be published.</p>}
          {waiting.map((p) => (
            <div key={p.id} className="mb-2 rounded border border-border p-2">
              <div className="font-medium">{p.title}</div>
              <div className="break-all text-faint">{p.destination_root} · {p.operations} file change(s)</div>
              <button disabled={!bridge || busy || p.invalid} onClick={() => void publish(p)} className="mt-1 rounded-md bg-accent px-2.5 py-1 text-white disabled:opacity-40">
                {busy ? "Waiting for you…" : "Review and publish…"}
              </button>
            </div>
          ))}
          {done.length > 0 && (
            <details className="mt-1 border-t border-border pt-1">
              <summary className="cursor-pointer text-faint">Published ({done.length})</summary>
              {done.map((p) => (
                <div key={p.id} className="mt-1 rounded border border-border/60 p-2 text-faint">
                  <div>{p.title}</div>
                  <div className="break-all">Published {when(p.published ?? "")} · {p.operations} file change(s)</div>
                </div>
              ))}
            </details>
          )}
          {status && <p className={status.ok ? "text-good" : "text-bad"}>{status.text}</p>}
        </div>
      )}
    </div>
  );
}
