import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowUp, Paperclip, Square, X } from "lucide-react";
import { api } from "../lib/api";
import { resetLabel } from "../lib/format";
import type { Command, Connection, Settings } from "../lib/types";
import { usageQuery, useUsageEdges } from "../lib/usage";

export interface Attached {
  name: string;
  data: string; // base64
}

function readFile(file: File): Promise<Attached> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, data: String(reader.result).split(",", 2)[1] ?? "" });
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings") });
}

export function useConnections() {
  return useQuery({ queryKey: ["connections"], queryFn: () => api.get<Connection[]>("/api/connections"), staleTime: 60_000 });
}

export default function PromptBar({
  onSend,
  onStop,
  running = false,
  connection,
  onConnection,
  contextPercent,
  placeholder = "Ask a question, or type / for a command",
  autoFocus = false,
}: {
  onSend: (text: string, files: Attached[]) => void;
  onStop?: () => void;
  running?: boolean;
  connection: string;
  onConnection: (conn: string) => void;
  contextPercent?: number | null;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<Attached[]>([]);
  const [pick, setPick] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const commands = useQuery({ queryKey: ["commands"], queryFn: () => api.get<Command[]>("/api/commands"), staleTime: 60_000 });
  const settings = useSettings();
  const connections = useConnections();
  useUsageEdges(connection, running);
  const usage = useQuery(usageQuery(connection, running));

  const slash = /^\/([\w:-]*)$/.exec(text);
  const matches = useMemo(() => {
    if (!slash) return [];
    // Every match is listed (the menu scrolls), and hyphens are optional: /useredits finds /user-edits.
    const loose = (s: string) => s.toLowerCase().replace(/-/g, "");
    const needle = loose(slash[1]);
    return (commands.data ?? []).filter((c) => loose(c.name).includes(needle));
  }, [slash, commands.data]);

  const choose = (c: Command) => {
    setText(`/${c.name} `);
    setPick(0);
    area.current?.focus();
  };

  const submit = () => {
    const value = text.trim();
    if (!value || running) return;
    onSend(value, files);
    setText("");
    setFiles([]);
  };

  // Effort for the next turn, on either provider: the meter's ‹ › or Alt+↑ / Alt+↓.
  const client = useQueryClient();
  const confNow = settings.data?.connections[connection];
  const connNow = connections.data?.find((c) => c.id === connection);
  const modelNow = connNow?.models.find((m) => m.value === confNow?.model) ?? connNow?.models[0];
  const levels = modelNow?.efforts?.length ? modelNow.efforts.filter((l) => l !== "ultra") : ["low", "medium", "high", "xhigh", "max"];
  const effort = confNow?.effort || (connNow?.runtime === "codex" ? "medium" : "high");
  const stepEffort = async (by: number) => {
    const at = Math.max(0, levels.indexOf(effort));
    const next = levels[Math.min(levels.length - 1, Math.max(0, at + by))];
    if (!next || next === effort || !confNow) return;
    await api.put("/api/settings", { connections: { [connection]: { ...confNow, effort: next } } });
    void client.invalidateQueries({ queryKey: ["settings"] });
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown") && !settings.data?.routing?.enabled) {
      e.preventDefault();
      void stepEffort(e.key === "ArrowUp" ? 1 : -1);
      return;
    }
    if (matches.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setPick((p) => (p + 1) % matches.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setPick((p) => (p - 1 + matches.length) % matches.length);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        choose(matches[Math.min(pick, matches.length - 1)]);
        return;
      }
      if (e.key === "Escape") {
        setText(text + " ");
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const routed = Boolean(settings.data?.routing?.enabled);
  const conf = settings.data?.connections[connection];
  const conn = connections.data?.find((c) => c.id === connection);
  const modelLabel = conn?.models.find((m) => m.value === conf?.model)?.label ?? (conf?.model || "default model");

  return (
    <div className="relative w-full">
      {matches.length > 0 && (
        <div className="absolute bottom-full left-0 right-0 mb-2 max-h-80 overflow-y-auto rounded-xl border border-border bg-surface p-1 shadow-lg">
          {matches.map((c, i) => (
            <button
              key={c.name}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(c);
              }}
              className={clsx("block w-full rounded-lg px-3 py-2 text-left", i === pick ? "bg-accent-bg" : "hover:bg-panel")}
            >
              <div className="text-[0.8125rem] font-medium">/{c.name}</div>
              <div className="line-clamp-2 text-[0.75rem] text-muted">{c.description}</div>
            </button>
          ))}
        </div>
      )}
      <div className="rounded-2xl border border-border bg-surface shadow-sm focus-within:border-accent/60">
        {files.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-3 pt-3">
            {files.map((f) => (
              <span key={f.name} className="flex items-center gap-1 rounded-md bg-panel px-2 py-0.5 text-[0.75rem] text-muted">
                {f.name}
                <button onClick={() => setFiles(files.filter((x) => x !== f))}>
                  <X size="0.6875rem" />
                </button>
              </span>
            ))}
          </div>
        )}
        <textarea
          ref={area}
          autoFocus={autoFocus}
          value={text}
          rows={Math.min(10, Math.max(2, text.split("\n").length))}
          onChange={(e) => {
            setText(e.target.value);
            setPick(0);
          }}
          onKeyDown={onKey}
          placeholder={placeholder}
          className="block w-full resize-none bg-transparent px-4 pt-3 text-[0.875rem] outline-none placeholder:text-faint"
        />
        <div className="flex items-center gap-2 px-2 pb-2">
          <button title="Attach files to the run's external_data/" onClick={() => fileInput.current?.click()} className="rounded-md p-1.5 text-faint hover:bg-panel hover:text-fg">
            <Paperclip size="1rem" />
          </button>
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            onChange={async (e) => {
              const list = Array.from(e.target.files ?? []);
              const read = await Promise.all(list.map(readFile));
              setFiles((prev) => [...prev, ...read]);
              e.target.value = "";
            }}
          />
          <div className="flex-1" />
          {running ? (
            <button onClick={onStop} title="Stop the turn" className="flex items-center gap-1 rounded-lg bg-fg px-3 py-1.5 text-[0.75rem] text-bg">
              <Square size="0.75rem" fill="currentColor" /> Stop
            </button>
          ) : (
            <button onClick={submit} disabled={!text.trim()} title="Send (Enter)" className="rounded-lg bg-accent p-1.5 text-white disabled:opacity-30">
              <ArrowUp size="1rem" />
            </button>
          )}
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 px-2 text-[0.75rem] text-faint">
        <select
          value={connection}
          onChange={(e) => onConnection(e.target.value)}
          className="rounded bg-transparent text-muted outline-none hover:text-fg"
          title="The connection the next message goes to"
        >
          {(connections.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
              {c.signed_in ? "" : " (not ready)"}
            </option>
          ))}
          {!connections.data && <option value={connection}>{connection}</option>}
        </select>
        <span>·</span>
        {routed ? (
          <span title="Model and effort follow the command the message starts with. Change it in Models.">auto: by command</span>
        ) : (
          <>
        <span>{modelLabel}</span>
        <span>·</span>
        <span className="group inline-flex items-center gap-1" title="Effort for the next turn: Alt+↑ / Alt+↓">
          <button onClick={() => void stepEffort(-1)} className="text-faint opacity-0 hover:text-fg group-hover:opacity-100" aria-label="Lower effort">
            ‹
          </button>
          <span className="font-mono tracking-tighter">
            {levels.map((l, i) => (
              <span key={l} className={i <= levels.indexOf(effort) ? (i >= levels.length - 1 ? "text-bad" : i >= levels.length - 2 ? "text-warn" : "text-accent") : "text-faint/50"}>
                {i <= levels.indexOf(effort) ? "▰" : "▱"}
              </span>
            ))}
          </span>
          <span>{effort}</span>
          <button onClick={() => void stepEffort(1)} className="text-faint opacity-0 hover:text-fg group-hover:opacity-100" aria-label="Raise effort">
            ›
          </button>
        </span>
          </>
        )}
        {contextPercent != null && <span>· context {Math.round(contextPercent)}%</span>}
        {(usage.data?.windows ?? []).map((w) => (
          <span key={w.name} title={w.resets_at ? `resets ${resetLabel(w.resets_at)}` : undefined} className={clsx((w.used_percent ?? 0) >= 85 && "text-warn")}>
            · {w.name} {w.used_percent != null ? `${Math.round(w.used_percent)}%` : w.status ?? ""}
          </span>
        ))}
      </div>
    </div>
  );
}
