import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Circle, Code2, Download, FileDown, FolderSearch, PanelRight, PanelRightClose, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { api, ApiError, fileUrl, getText, q, renderedUrl } from "../lib/api";
import { bytes, day } from "../lib/format";
import type { RunDetail, SessionDetail } from "../lib/types";
import { place, remember, rememberDraft, rememberScroll } from "../lib/places";
import { prefs, setPref } from "../lib/prefs";
import { useUi } from "../stores/ui";
import Markdown from "./Markdown";
import SessionView from "./SessionView";

const TEXT = /\.(md|txt|jsonl|json|csv|tsv|py|ya?ml|bib)$/i;
type Tab = "document" | "chat" | "html" | "edit" | "file";

interface Rendered {
  html: string;
  figures: { name: string; files: Record<string, string> }[];
  cached: boolean;
  log: string;
}

interface Exported {
  files: string[];
  folder: string;
  check: string;
}

function FileViewer({ run, path }: { run: string; path: string }) {
  const text = useQuery({
    queryKey: ["run-file", run, path],
    queryFn: () => api.get<string>(`/api/runs/${encodeURIComponent(run)}/file?${q({ path })}`),
    enabled: TEXT.test(path),
  });
  if (/\.(png|jpe?g|svg|gif)$/i.test(path)) return <img src={fileUrl(run, path)} alt={path} className="max-w-full rounded border border-border" />;
  if (/\.(html|pdf)$/i.test(path)) return <iframe title={path} src={fileUrl(run, path)} className="h-[80vh] w-full rounded border border-border bg-white" />;
  if (!TEXT.test(path)) {
    return (
      <a className="text-[13px] text-accent underline" href={fileUrl(run, path)} target="_blank" rel="noreferrer">
        Open {path}
      </a>
    );
  }
  if (text.isLoading) return <div className="text-faint">Loading…</div>;
  if (text.isError) return <div className="text-bad">{(text.error as Error).message}</div>;
  const body = String(text.data ?? "");
  if (path.endsWith(".md")) return <Markdown text={body} />;
  if (path.endsWith(".jsonl")) {
    return (
      <div className="space-y-1">
        {body
          .split("\n")
          .filter((l) => l.trim())
          .map((line, i) => {
            let pretty = line;
            let bad = false;
            try {
              pretty = JSON.stringify(JSON.parse(line), null, 1);
            } catch {
              bad = true;
            }
            return (
              <pre key={i} className={clsx("whitespace-pre-wrap rounded bg-panel p-2 font-mono text-[11.5px]", bad && "border border-bad text-bad")}>
                {pretty}
              </pre>
            );
          })}
      </div>
    );
  }
  return <pre className="whitespace-pre-wrap font-mono text-[12px]">{body}</pre>;
}

function EditPane({ run, path, onSaved }: { run: string; path: string; onSaved: () => void }) {
  const kept = place(run).drafts[path];
  const [text, setText] = useState(kept?.text ?? "");
  const [original, setOriginal] = useState(kept?.original ?? "");
  const [mtime, setMtime] = useState<number | null>(kept?.mtime ?? null);
  const area = useRef<HTMLTextAreaElement>(null);
  const [message, setMessage] = useState("");
  const [conflict, setConflict] = useState(false);
  const load = async () => {
    const res = await getText(`/api/runs/${encodeURIComponent(run)}/file?${q({ path })}`);
    setText(res.text);
    setOriginal(res.text);
    setMtime(res.mtime);
    setConflict(false);
    setMessage("");
  };
  useEffect(() => {
    // Unsaved text from before the author left this tab comes back as it was.
    if (!place(run).drafts[path]) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, path]);
  useEffect(() => {
    rememberDraft(run, path, { text, original, mtime });
  }, [run, path, text, original, mtime]);
  useLayoutEffect(() => {
    const el = area.current;
    const top = place(run).scroll[`edit:${path}`];
    if (el && top && original) el.scrollTop = top;
  }, [run, path, original]);
  const save = useMutation({
    mutationFn: () => api.put<{ mtime: number }>(`/api/runs/${encodeURIComponent(run)}/file`, { path, content: text, mtime }),
    onSuccess: (r) => {
      setMtime(r.mtime);
      setOriginal(text);
      setMessage("Saved. The HTML view re-renders from this file. To have an agent absorb the edit into the report, ask for /user-edits.");
      onSaved();
    },
    onError: (e) => {
      setConflict(e instanceof ApiError && e.status === 409 && e.message.includes("changed on disk"));
      setMessage((e as Error).message);
    },
  });
  const dirty = text !== original;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-[12.5px]">
        <span className="font-mono">{path}</span>
        {dirty && <span className="text-warn">unsaved</span>}
        <div className="flex-1" />
        <button onClick={() => setText(original)} disabled={!dirty} className="rounded-md border border-border px-2.5 py-1 disabled:opacity-40">
          Revert
        </button>
        <button onClick={() => save.mutate()} disabled={!dirty || save.isPending} className="rounded-md bg-accent px-3 py-1 text-white disabled:opacity-40">
          Save
        </button>
      </div>
      {message && (
        <div className={clsx("border-b border-border px-4 py-1.5 text-[12px]", conflict ? "text-bad" : "text-muted")}>
          {message}
          {conflict && (
            <button onClick={() => void load()} className="ml-2 underline">
              Reload from disk
            </button>
          )}
        </div>
      )}
      <textarea
        ref={area}
        onScroll={(e) => rememberScroll(run, `edit:${path}`, e.currentTarget.scrollTop)}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "s") {
            e.preventDefault();
            if (dirty) save.mutate();
          }
        }}
        spellCheck
        className="min-h-0 flex-1 resize-none bg-bg p-5 font-mono text-[13px] leading-6 outline-none"
      />
    </div>
  );
}

function HtmlPane({ run, version }: { run: string; version: number }) {
  const styles = useQuery({ queryKey: ["styles"], queryFn: () => api.get<{ name: string; description: string }[]>("/api/styles"), staleTime: Infinity });
  const [style, setStyleState] = useState(() => place(run).style ?? "meridian");
  const [cite, setCiteState] = useState(() => place(run).cite ?? true);
  const setStyle = (v: string) => {
    setStyleState(v);
    remember(run, { style: v });
  };
  const setCite = (v: boolean) => {
    setCiteState(v);
    remember(run, { cite: v });
  };
  // The rendered page is served from this app's own address, so its scroll can be read
  // and put back: the author returns to the paragraph they were reading.
  const onFrameLoad = (frame: HTMLIFrameElement) => {
    const win = frame.contentWindow;
    if (!win) return;
    const top = place(run).scroll.html;
    if (top) win.scrollTo(0, top);
    let pending = false;
    win.addEventListener("scroll", () => {
      if (pending) return;
      pending = true;
      win.requestAnimationFrame(() => {
        pending = false;
        rememberScroll(run, "html", win.scrollY);
      });
    });
  };
  const [exported, setExported] = useState<Exported | null>(null);
  const [saved, setSaved] = useState("");
  const rendered = useQuery({
    queryKey: ["render", run, style, cite, version],
    queryFn: () => api.post<Rendered>(`/api/runs/${encodeURIComponent(run)}/render`, { style, cite }),
    staleTime: Infinity,
    retry: false,
  });
  const exportRun = useMutation({
    mutationFn: (formats: string[]) => api.post<Exported>(`/api/runs/${encodeURIComponent(run)}/export`, { style, cite, formats }),
    onSuccess: setExported,
  });
  const saveFigures = useMutation({
    mutationFn: () => api.post<{ saved: string[] }>(`/api/runs/${encodeURIComponent(run)}/figures/save`, { style, cite }),
    onSuccess: (r) => setSaved(`${r.saved.length} file(s) saved to export/${style}/figures/.`),
  });
  const data = rendered.data;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2 text-[12.5px]">
        <label className="text-faint">Style</label>
        <select value={style} onChange={(e) => setStyle(e.target.value)} className="rounded-md border border-border bg-surface px-2 py-1">
          {(styles.data ?? [{ name: "meridian", description: "" }]).map((s) => (
            <option key={s.name} value={s.name} title={s.description}>
              {s.name}
            </option>
          ))}
        </select>
        <label className="ml-2 text-faint">Citations</label>
        <select value={cite ? "cited" : "ids"} onChange={(e) => setCite(e.target.value === "cited")} className="rounded-md border border-border bg-surface px-2 py-1">
          <option value="cited">Author and year</option>
          <option value="ids">Evidence IDs</option>
        </select>
        <button onClick={() => void rendered.refetch()} title="Render again" className="rounded-md p-1 text-faint hover:text-fg">
          <RefreshCw size={13} className={clsx(rendered.isFetching && "animate-spin")} />
        </button>
        <div className="flex-1" />
        <button onClick={() => exportRun.mutate(["html"])} disabled={exportRun.isPending} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 hover:border-accent disabled:opacity-40">
          <FileDown size={13} /> Export HTML
        </button>
        <button onClick={() => exportRun.mutate(["html", "pdf"])} disabled={exportRun.isPending} className="flex items-center gap-1 rounded-md bg-accent px-2.5 py-1 text-white disabled:opacity-40">
          <FileDown size={13} /> {exportRun.isPending ? "Exporting…" : "Export PDF"}
        </button>
      </div>
      {(exported || exportRun.isError) && (
        <div className="border-b border-border px-4 py-2 text-[12px]">
          {exportRun.isError ? (
            <pre className="whitespace-pre-wrap text-bad">{(exportRun.error as Error).message}</pre>
          ) : (
            exported && (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <span>Written to {exported.folder}/:</span>
                  {exported.files.map((f) => (
                    <button key={f} onClick={() => void api.post("/api/exports/open", { path: f })} className="text-accent underline">
                      {f.split("/").pop()}
                    </button>
                  ))}
                  <button onClick={() => void api.post("/api/reveal", { path: exported.files[0] })} className="text-muted underline">
                    Show in Finder
                  </button>
                </div>
                <pre className={clsx("mt-1 whitespace-pre-wrap text-[11.5px]", exported.check.startsWith("Export check passed") ? "text-good" : "text-warn")}>{exported.check}</pre>
              </>
            )
          )}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 bg-white">
          {rendered.isFetching && !data && <div className="p-6 text-[13px] text-faint">Rendering the figures and the HTML…</div>}
          {rendered.isError && <pre className="whitespace-pre-wrap p-6 text-[12.5px] text-bad">{(rendered.error as Error).message}</pre>}
          {data && <iframe key={data.html + version} title="HTML" src={renderedUrl(run, style, cite, data.html)} onLoad={(e) => onFrameLoad(e.currentTarget)} className="h-full w-full border-0" />}
        </div>
        {data && data.figures.length > 0 && (
          <aside className="scroll-thin w-60 shrink-0 overflow-y-auto border-l border-border bg-panel/50 p-3 text-[12px]">
            <div className="mb-2 flex items-center">
              <span className="text-[11px] font-medium uppercase tracking-wide text-faint">Figures</span>
              <button onClick={() => saveFigures.mutate()} className="ml-auto text-[11.5px] text-accent underline" title={`Copy every figure to export/${style}/figures/`}>
                Save all
              </button>
            </div>
            {saved && <div className="mb-2 text-[11.5px] text-good">{saved}</div>}
            {data.figures.map((f) => (
              <div key={f.name} className="mb-3">
                {f.files.png && <img src={renderedUrl(run, style, cite, f.files.png)} alt={f.name} className="w-full rounded border border-border bg-white" />}
                <div className="mt-1 flex items-center gap-2">
                  <span className="font-medium">{f.name}</span>
                  {Object.entries(f.files).map(([kind, path]) => (
                    <a key={kind} href={renderedUrl(run, style, cite, path, true)} className="flex items-center gap-0.5 text-accent">
                      <Download size={11} /> {kind.toUpperCase()}
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </aside>
        )}
      </div>
    </div>
  );
}

export default function RunView({ name, file }: { name: string; file?: string }) {
  const client = useQueryClient();
  const { setView } = useUi();
  const run = useQuery({ queryKey: ["run", name], queryFn: () => api.get<RunDetail>(`/api/runs/${encodeURIComponent(name)}`), refetchInterval: 15_000 });
  // Back where the author left this project: tab, file, and (below) scroll positions.
  const kept = place(name);
  const [tab, setTabState] = useState<Tab>(file ? "file" : (kept.tab ?? "document"));
  const [selected, setSelectedState] = useState<string | undefined>(file ?? kept.selected);
  const [editPath, setEditPathState] = useState<string | undefined>(kept.editPath);
  const setTab = (t: Tab) => {
    setTabState(t);
    remember(name, { tab: t });
  };
  const setSelected = (f: string | undefined) => {
    setSelectedState(f);
    remember(name, { selected: f });
  };
  const setEditPath = (f: string | undefined) => {
    setEditPathState(f);
    remember(name, { editPath: f });
  };
  const reader = useRef<HTMLDivElement>(null);
  const readerKey = tab === "file" ? `file:${selected ?? ""}` : "document";
  const [version, setVersion] = useState(0);
  const [panelOpen, setPanelOpenState] = useState(() => prefs().run_panel_open);
  const setPanelOpen = (open: boolean) => {
    setPanelOpenState(open);
    setPref("run_panel_open", open);
  };
  // The project's conversation, opened (or created) when the Chat tab is first shown.
  const [chat, setChat] = useState<string | null>(null);
  const openChat = useMutation({
    mutationFn: (fresh: boolean) => api.post<SessionDetail>(`/api/runs/${encodeURIComponent(name)}/chat`, { new: fresh }),
    onSuccess: (s) => {
      setChat(s.id);
      void client.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
  useEffect(() => {
    setChat(null);
  }, [name]);
  useEffect(() => {
    if (tab === "chat" && !chat && !openChat.isPending) openChat.mutate(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, chat]);
  useEffect(() => {
    if (file) {
      setSelected(file);
      setTab("file");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);
  const remove = useMutation({
    mutationFn: () => api.del<{ trash: string }>(`/api/runs/${encodeURIComponent(name)}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["runs"] });
      void client.invalidateQueries({ queryKey: ["exports"] });
      void client.invalidateQueries({ queryKey: ["sessions"] });
      setView({ kind: "home" });
    },
  });
  const data = run.data;
  const hasContent = Boolean(data);
  useLayoutEffect(() => {
    const el = reader.current;
    const top = place(name).scroll[readerKey];
    if (!el || !top) return;
    // A file's text arrives after the pane does: wait until the page is tall enough to
    // hold the old position, then go there. Give up after a few seconds.
    const restore = () => {
      if (el.scrollHeight - el.clientHeight < top - 2) return false;
      el.scrollTop = top;
      return true;
    };
    if (restore()) return;
    const watch = new ResizeObserver(() => {
      if (restore()) watch.disconnect();
    });
    if (el.firstElementChild) watch.observe(el.firstElementChild);
    const stop = setTimeout(() => watch.disconnect(), 4000);
    return () => {
      watch.disconnect();
      clearTimeout(stop);
    };
  }, [name, readerKey, hasContent]);
  if (run.isError) return <div className="p-6 text-bad">{(run.error as Error).message}</div>;
  if (!data) return <div className="p-6 text-faint">Loading…</div>;
  const primary = data.meta.primary;
  const editing = editPath ?? primary ?? undefined;
  const onSaved = () => {
    setVersion((v) => v + 1);
    void client.invalidateQueries({ queryKey: ["run", name] });
    void client.invalidateQueries({ queryKey: ["run-file", name] });
  };
  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: "document", label: "Document", show: true },
    { id: "chat", label: "Chat", show: true },
    { id: "html", label: "HTML", show: Boolean(primary) },
    { id: "edit", label: "Edit", show: Boolean(editing) },
    { id: "file", label: selected ?? "File", show: Boolean(selected) },
  ];

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border px-5 py-2">
          <div className="min-w-0 flex-1">
            <div className="text-[11.5px] text-faint">
              Research · {data.evidence_rows} evidence rows · {data.notes} notes
            </div>
            <div className="truncate text-[15px] font-medium">{name}</div>
          </div>
          <button onClick={() => void api.post(`/api/runs/${encodeURIComponent(name)}/vscode`)} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[12px] hover:border-accent">
            <Code2 size={13} /> VS Code
          </button>
          <button onClick={() => void api.post(`/api/runs/${encodeURIComponent(name)}/reveal`)} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[12px] hover:border-accent">
            <FolderSearch size={13} /> Finder
          </button>
          {tab !== "chat" && (
            <button
              onClick={() => setPanelOpen(!panelOpen)}
              title={panelOpen ? "Collapse the stages and files panel" : "Show the stages and files panel"}
              className={clsx("rounded-md p-1.5 hover:bg-panel hover:text-fg", panelOpen ? "text-accent" : "text-faint")}
            >
              <PanelRight size={16} />
            </button>
          )}
          <button
            onClick={() => {
              if (window.confirm(`Remove ${name}? Its folder moves to the Trash, where you can still restore it. Its conversations and cached renders are deleted.`)) remove.mutate();
            }}
            className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[12px] text-bad hover:border-bad"
          >
            <Trash2 size={13} /> Remove
          </button>
        </div>
        {remove.isError && <div className="border-b border-border px-5 py-1.5 text-[12px] text-bad">{(remove.error as Error).message}</div>}
        <div className="flex gap-1 border-b border-border px-4 py-1.5">
          {tabs
            .filter((t) => t.show)
            .map((t) => (
              <button key={t.id} onClick={() => setTab(t.id)} className={clsx("max-w-[16rem] truncate rounded-md px-3 py-1 text-[12.5px]", tab === t.id ? "bg-panel font-medium text-fg" : "text-muted hover:text-fg")}>
                {t.label}
              </button>
            ))}
          {tab === "file" && selected?.endsWith(".md") && !selected.startsWith("export/") && (
            <button
              onClick={() => {
                setEditPath(selected);
                setTab("edit");
              }}
              className="ml-2 flex items-center gap-1 text-[12px] text-accent"
            >
              <Pencil size={12} /> Edit this file
            </button>
          )}
        </div>
        <div className="min-h-0 flex-1">
          {tab === "chat" &&
            (chat ? (
              <SessionView key={chat} id={chat} embedded onNew={() => openChat.mutate(true)} />
            ) : (
              <div className="p-6 text-[13px] text-faint">{openChat.isError ? (openChat.error as Error).message : "Opening the project's conversation…"}</div>
            ))}
          {tab === "html" && <HtmlPane run={name} version={version} />}
          {tab === "edit" && editing && <EditPane run={name} path={editing} onSaved={onSaved} />}
          {(tab === "document" || tab === "file") && (
            <div ref={reader} onScroll={(e) => rememberScroll(name, readerKey, e.currentTarget.scrollTop)} className="scroll-thin h-full overflow-y-auto">
              <div className="mx-auto max-w-3xl px-8 py-6">
                {tab === "file" && selected ? (
                  <FileViewer run={name} path={selected} />
                ) : data.master ? (
                  <Markdown text={data.master} />
                ) : (
                  <div className="text-[13px] text-faint">No master document yet ({data.meta.masters.join(", ")}).</div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
      {tab !== "chat" && panelOpen && (
      <aside className="scroll-thin w-64 shrink-0 overflow-y-auto border-l border-border bg-panel/50 p-4 text-[12.5px]">
        <div className="mb-1.5 flex items-center text-[11px] font-medium uppercase tracking-wide text-faint">
          Stages
          <button onClick={() => setPanelOpen(false)} title="Collapse the panel" className="ml-auto rounded-md p-0.5 normal-case hover:bg-panel hover:text-fg">
            <PanelRightClose size={14} />
          </button>
        </div>
        {data.stages.map((s) => (
          <div key={s.stage} className="flex items-center gap-1.5 py-0.5" title={s.detail}>
            {s.ok ? <Check size={12} className="text-good" /> : <Circle size={10} className="mx-0.5 text-faint" />}
            <span className={s.ok ? "" : "text-faint"}>{s.stage}</span>
            <span className="ml-auto truncate pl-2 text-[11px] text-faint">{s.detail}</span>
          </div>
        ))}
        <div className="mb-1.5 mt-4 text-[11px] font-medium uppercase tracking-wide text-faint">Files</div>
        <div className="space-y-0.5">
          {data.files.map((f) => (
            <button
              key={f.path}
              onClick={() => {
                setSelected(f.path);
                setTab("file");
              }}
              className={clsx("flex w-full items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-panel", selected === f.path && tab === "file" && "bg-panel")}
            >
              <span className={clsx("min-w-0 flex-1 truncate", f.path === primary && "font-medium")}>{f.path}</span>
              <span className="shrink-0 text-[10.5px] text-faint">
                {bytes(f.size)} · {day(f.mtime)}
              </span>
            </button>
          ))}
        </div>
      </aside>
      )}
    </div>
  );
}
