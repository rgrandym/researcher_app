import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronDown, ChevronRight, FileOutput, FolderOpen, History, Palette, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { day, label } from "../lib/format";
import type { ExportFile, RunDetail, RunSummary, SessionDetail, SessionSummary } from "../lib/types";
import { THEMES, applyTheme, storedTheme } from "../lib/theme";
import { useUi } from "../stores/ui";

function Section({
  title,
  icon,
  open,
  onToggle,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-3">
      <button onClick={onToggle} className="flex w-full items-center gap-1.5 px-3 py-1 text-[12px] font-medium uppercase tracking-wide text-faint hover:text-muted">
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {icon}
        {title}
      </button>
      {open && <div className="mt-0.5">{children}</div>}
    </div>
  );
}

function RunFiles({ name, active }: { name: string; active?: string }) {
  const { setView } = useUi();
  const [openDirs, setOpenDirs] = useState<Record<string, boolean>>({});
  const run = useQuery({ queryKey: ["run", name], queryFn: () => api.get<RunDetail>(`/api/runs/${encodeURIComponent(name)}`) });
  if (!run.data) return <div className="ml-6 py-1 text-[11.5px] text-faint">Loading…</div>;
  const top: string[] = [];
  const dirs = new Map<string, string[]>();
  for (const f of run.data.files) {
    const parts = f.path.split("/");
    if (parts.length === 1) top.push(f.path);
    else dirs.set(parts[0], [...(dirs.get(parts[0]) ?? []), f.path]);
  }
  const fileButton = (path: string, label: string, depth: number) => (
    <button
      key={path}
      onClick={() => setView({ kind: "run", name, file: path })}
      title={path}
      className={clsx("block w-full truncate rounded px-2 py-0.5 text-left text-[12px]", active === path ? "bg-surface text-fg" : "text-muted hover:text-fg")}
      style={{ paddingLeft: `${depth * 12 + 8}px` }}
    >
      {label}
    </button>
  );
  return (
    <div className="mb-1 ml-3 border-l border-border">
      {top.map((p) => fileButton(p, p, 0))}
      {[...dirs.entries()].map(([dir, files]) => (
        <div key={dir}>
          <button onClick={() => setOpenDirs((o) => ({ ...o, [dir]: !o[dir] }))} className="flex w-full items-center gap-1 px-2 py-0.5 text-left text-[12px] text-muted hover:text-fg">
            {openDirs[dir] ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            {dir}/ <span className="text-faint">{files.length}</span>
          </button>
          {openDirs[dir] && files.map((p) => fileButton(p, p.slice(dir.length + 1), 1))}
        </div>
      ))}
    </div>
  );
}

export default function Sidebar() {
  const { view, setView, close } = useUi();
  const client = useQueryClient();
  const [open, setOpen] = useState({ history: true, vscode: false, outputs: true });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<SessionSummary[]>("/api/sessions"), refetchInterval: 15_000 });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.get<RunSummary[]>("/api/runs"), refetchInterval: 30_000 });
  const exports = useQuery({ queryKey: ["exports"], queryFn: () => api.get<ExportFile[]>("/api/exports") });
  const vscode = useQuery({
    queryKey: ["vscode-sessions"],
    queryFn: () => api.get<{ id: string; title: string; mtime: number }[]>("/api/vscode-sessions"),
    enabled: open.vscode,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/sessions/${id}`),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["sessions"] }),
  });
  const importSession = useMutation({
    mutationFn: (id: string) => api.post<SessionDetail>(`/api/vscode-sessions/${id}/import`),
    onSuccess: (s) => {
      void client.invalidateQueries({ queryKey: ["sessions"] });
      setView({ kind: "session", id: s.id });
    },
  });
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const removeRun = useMutation({
    mutationFn: (name: string) => api.del<{ removed_sessions: string[] }>(`/api/runs/${encodeURIComponent(name)}`),
    onSuccess: (res, name) => {
      void client.invalidateQueries({ queryKey: ["runs"] });
      void client.invalidateQueries({ queryKey: ["exports"] });
      void client.invalidateQueries({ queryKey: ["sessions"] });
      if ((view.kind === "run" && view.name === name) || (view.kind === "session" && res.removed_sessions.includes(view.id))) setView({ kind: "home" });
    },
  });
  const toggle = (key: keyof typeof open) => setOpen((o) => ({ ...o, [key]: !o[key] }));
  const item = (active: boolean) =>
    clsx("group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px]", active ? "bg-surface text-fg shadow-sm" : "text-muted hover:bg-surface/60 hover:text-fg");

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-panel">
      <div className="p-3">
        <button
          onClick={() => setView({ kind: "home" })}
          className="flex w-full items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-[13px] font-medium hover:border-accent"
        >
          <Plus size={15} /> New
        </button>
      </div>
      <nav className="scroll-thin min-h-0 flex-1 overflow-y-auto px-1 pb-3">
        <Section title="History" icon={<History size={12} />} open={open.history} onToggle={() => toggle("history")}>
          <div className="space-y-0.5 px-1">
            {(sessions.data ?? []).map((s) => (
              <div key={s.id} className={item(view.kind === "session" && view.id === s.id)}>
                <button className="min-w-0 flex-1 text-left" onClick={() => setView({ kind: "session", id: s.id })}>
                  <div className="truncate">{s.title}</div>
                  <div className="mt-0.5 flex items-center gap-1 text-[11px] text-faint">
                    {day(s.updated)}
                    {s.running && <span className="text-accent">· running</span>}
                    {[...new Set(s.providers)].map((p) => (
                      <span key={p} className="rounded bg-panel px-1 text-[10px]">
                        {label(p)}
                      </span>
                    ))}
                  </div>
                </button>
                <button
                  title="Delete this session"
                  className="hidden text-faint hover:text-bad group-hover:block"
                  onClick={() => {
                    if (window.confirm(`Delete "${s.title}"? Its run folders stay.`)) remove.mutate(s.id);
                  }}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
            {sessions.data?.length === 0 && <div className="px-2 py-1 text-[12px] text-faint">No sessions yet.</div>}
            <button onClick={() => toggle("vscode")} className="mt-1 flex items-center gap-1 px-2 py-1 text-[12px] text-faint hover:text-muted">
              {open.vscode ? <ChevronDown size={11} /> : <ChevronRight size={11} />} From VS Code
            </button>
            {open.vscode &&
              (vscode.data ?? []).map((v) => (
                <button key={v.id} className={item(false)} onClick={() => importSession.mutate(v.id)} title="Continue this Claude Code session in the app">
                  <div className="min-w-0 flex-1">
                    <div className="truncate">{v.title}</div>
                    <div className="text-[11px] text-faint">{day(v.mtime)} · continue in the app</div>
                  </div>
                </button>
              ))}
          </div>
        </Section>

        <Section title="Outputs" icon={<FolderOpen size={12} />} open={open.outputs} onToggle={() => toggle("outputs")}>
          <div className="space-y-0.5 px-1">
            {(runs.data ?? []).map((r) => (
              <div key={r.name}>
                <div className={item(view.kind === "run" && view.name === r.name)}>
                  <button onClick={() => setExpanded((e) => ({ ...e, [r.name]: !e[r.name] }))} className="text-faint hover:text-fg" title="Show files">
                    {expanded[r.name] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </button>
                  <button className="min-w-0 flex-1 text-left" onClick={() => setView({ kind: "run", name: r.name })} title={r.prompt}>
                    <div className="truncate">{r.name.slice(11)}</div>
                    <div className="text-[11px] text-faint">
                      {r.name.slice(0, 10)}
                    </div>
                  </button>
                  <button
                    title="Remove this project (moves it to the Trash)"
                    className="hidden text-faint hover:text-bad group-hover:block"
                    onClick={() => {
                      if (window.confirm(`Remove ${r.name}? Its folder moves to the Trash, where you can still restore it. Its conversations and cached renders are deleted.`)) removeRun.mutate(r.name);
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
                {expanded[r.name] && <RunFiles name={r.name} active={view.kind === "run" && view.name === r.name ? view.file : undefined} />}
              </div>
            ))}
            {removeRun.isError && <div className="px-2 text-[11.5px] text-bad">{(removeRun.error as Error).message}</div>}
          </div>
        </Section>

        <div className="mt-3 space-y-0.5 px-1">
          <button className={item(view.kind === "exports")} onClick={() => setView({ kind: "exports" })}>
            <FileOutput size={14} /> Exports
            <span className="ml-auto text-[11px] text-faint">{exports.data?.length ?? ""}</span>
          </button>
          <button className={item(view.kind === "workspace")} onClick={() => (view.kind === "workspace" ? close() : setView({ kind: "workspace" }))}>
            <SlidersHorizontal size={14} /> Workspace
          </button>
          <ThemePicker />
        </div>
      </nav>
    </aside>
  );
}

function ThemePicker() {
  const [theme, setTheme] = useState(storedTheme);
  const current = THEMES.find((t) => t.id === theme) ?? THEMES[0];
  return (
    <label className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-muted hover:bg-panel" title="Colour theme for this app">
      <Palette size={14} />
      <span className="flex shrink-0 overflow-hidden rounded-full border border-border" aria-hidden>
        <span className="h-3 w-1.5" style={{ background: current.swatch[0] }} />
        <span className="h-3 w-1.5" style={{ background: current.swatch[1] }} />
      </span>
      <select
        value={theme}
        onChange={(e) => {
          setTheme(e.target.value);
          applyTheme(e.target.value);
        }}
        className="min-w-0 flex-1 cursor-pointer bg-transparent text-[13px] text-muted outline-none hover:text-fg"
      >
        {THEMES.map((t) => (
          <option key={t.id} value={t.id}>
            {t.label}
          </option>
        ))}
      </select>
    </label>
  );
}
