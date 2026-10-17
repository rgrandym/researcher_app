import { lazy, Suspense, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronDown, ChevronRight, History, Plus, Sparkles } from "lucide-react";
import { api, q } from "../lib/api";
import type { Commit, WorkspaceGroup } from "../lib/types";
import Markdown from "./Markdown";
import Panel, { CENTER, PANELS } from "./Panel";

const MarkdownEditor = lazy(() => import("./MarkdownEditor"));

function DiffView({ text }: { text: string }) {
  if (!text.trim()) return <div className="text-[0.75rem] text-faint">No change.</div>;
  return (
    <pre className="scroll-thin max-h-[50vh] overflow-auto rounded-md bg-panel p-2 font-mono text-[0.7188rem] leading-5">
      {text.split("\n").map((line, i) => (
        <div
          key={i}
          className={clsx(
            line.startsWith("+") && !line.startsWith("+++") && "bg-good/15 text-good",
            line.startsWith("-") && !line.startsWith("---") && "bg-bad/15 text-bad",
            line.startsWith("@@") && "text-accent",
          )}
        >
          {line || " "}
        </div>
      ))}
    </pre>
  );
}

function Modal({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-6" onClick={onClose}>
      <div className="max-h-full w-full max-w-3xl overflow-auto rounded-xl border border-border bg-surface p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

type Tab = "edit" | "preview" | "history";

export default function WorkspaceView({ initialPath }: { initialPath?: string }) {
  const client = useQueryClient();
  const files = useQuery({ queryKey: ["ws-files"], queryFn: () => api.get<WorkspaceGroup[]>("/api/workspace/files") });
  const [closed, setClosed] = useState<Record<string, boolean>>({ Scripts: true, Mods: true });
  const [path, setPath] = useState<string | undefined>(initialPath);
  const [content, setContent] = useState("");
  const [original, setOriginal] = useState("");
  const [isNew, setIsNew] = useState(false);
  const [tab, setTab] = useState<Tab>("edit");
  const [review, setReview] = useState<{ diff: string; problems: string[] } | null>(null);
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [improve, setImprove] = useState("");
  const [proposal, setProposal] = useState<{ diff: string; content: string; reply: string; error: string } | null>(null);
  const [commit, setCommit] = useState<{ rev: string; text: string } | null>(null);

  const file = useQuery({
    queryKey: ["ws-file", path],
    queryFn: () => api.get<{ content: string; exists: boolean }>(`/api/workspace/file?${q({ path: path ?? "" })}`),
    enabled: Boolean(path) && !isNew,
  });
  const history = useQuery({
    queryKey: ["ws-history", path],
    queryFn: () => api.get<Commit[]>(`/api/workspace/history?${q({ path: path ?? "" })}`),
    enabled: Boolean(path) && tab === "history" && !isNew,
  });

  useEffect(() => {
    if (file.data) {
      setContent(file.data.content);
      setOriginal(file.data.content);
    }
  }, [file.data]);

  const open = (p: string) => {
    if (content !== original && !window.confirm("Discard the unsaved change?")) return;
    setIsNew(false);
    setPath(p);
    setTab("edit");
    setNotice("");
    setProposal(null);
  };

  const prepare = useMutation({
    mutationFn: () => api.post<{ diff: string; problems: string[] }>("/api/workspace/diff", { path, content }),
    onSuccess: (r) => {
      setReview(r);
      const name = path?.split("/").slice(-2).join("/") ?? "";
      setMessage((m) => m || `Edit ${name}: `);
    },
    onError: (e) => setNotice((e as Error).message),
  });
  const save = useMutation({
    mutationFn: () => api.post<{ ok: boolean; problems: string[]; commit?: string | null; stale_sessions?: string[] }>("/api/workspace/save", { path, content, message }),
    onSuccess: (r) => {
      if (!r.ok) {
        setReview((v) => (v ? { ...v, problems: r.problems } : v));
        return;
      }
      setReview(null);
      setMessage("");
      setOriginal(content);
      setIsNew(false);
      const stale = r.stale_sessions?.length ? ` ${r.stale_sessions.length} open session(s) will start their next turn fresh, with a handoff.` : "";
      setNotice(`Saved${r.commit ? ` and committed as ${r.commit}` : " (this file is not versioned)"}.${stale}`);
      void client.invalidateQueries({ queryKey: ["ws-files"] });
      void client.invalidateQueries({ queryKey: ["ws-history", path] });
      void client.invalidateQueries({ queryKey: ["commands"] });
    },
    onError: (e) => setNotice((e as Error).message),
  });
  const restore = useMutation({
    mutationFn: (rev: string) => api.post<{ ok: boolean; problems: string[]; commit?: string }>("/api/workspace/restore", { path, rev }),
    onSuccess: (r) => {
      setNotice(r.ok ? `Restored and committed as ${r.commit}.` : `Restore blocked: ${r.problems.join(" ")}`);
      setCommit(null);
      void client.invalidateQueries({ queryKey: ["ws-file", path] });
      void client.invalidateQueries({ queryKey: ["ws-history", path] });
    },
    onError: (e) => setNotice((e as Error).message),
  });
  const ask = useMutation({
    mutationFn: () => api.post<{ diff: string; content: string; reply: string; error: string }>("/api/workspace/improve", { path, request: improve }),
    onSuccess: (r) => setProposal(r),
    onError: (e) => setNotice((e as Error).message),
  });
  const create = useMutation({
    mutationFn: (body: { kind: string; name: string; description: string }) => api.post<{ path: string; content: string }>("/api/workspace/new", body),
    onSuccess: (r) => {
      setCreating(false);
      setIsNew(true);
      setPath(r.path);
      setContent(r.content);
      setOriginal("");
      setTab("edit");
    },
    onError: (e) => setNotice((e as Error).message),
  });

  const showCommit = async (rev: string) => {
    const text = await api.get<string>(`/api/workspace/commit?${q({ path: path ?? "", rev })}`);
    setCommit({ rev, text });
  };

  return (
    <div className="flex h-full">
      <Panel size={PANELS.nav} side="left">
      <nav className="scroll-thin min-h-0 flex-1 overflow-y-auto p-3 text-[0.7812rem]">
        <button onClick={() => setCreating(true)} className="mb-2 flex w-full items-center gap-1.5 rounded-md border border-border px-2 py-1.5 hover:border-accent">
          <Plus size="0.8125rem" /> New skill, command or agent
        </button>
        {(files.data ?? []).map((g) => (
          <div key={g.group} className="mb-1">
            <button onClick={() => setClosed((c) => ({ ...c, [g.group]: !c[g.group] }))} className="flex w-full items-center gap-1 py-1 text-[0.7188rem] font-medium uppercase tracking-wide text-faint hover:text-muted">
              {closed[g.group] ? <ChevronRight size="0.6875rem" /> : <ChevronDown size="0.6875rem" />}
              {g.group}
              <span className="ml-auto font-normal">{g.files.length}</span>
            </button>
            {!closed[g.group] &&
              g.files.map((f) => (
                <button key={f.path} onClick={() => open(f.path)} title={f.path} className={clsx("block w-full truncate rounded px-2 py-1 text-left", path === f.path ? "bg-panel text-fg" : "text-muted hover:bg-panel hover:text-fg")}>
                  {f.name}
                </button>
              ))}
            {!closed[g.group] && g.files.length === 0 && <div className="px-2 text-[0.7188rem] text-faint">None</div>}
          </div>
        ))}
      </nav>
      </Panel>

      <div className={`flex flex-col ${CENTER}`}>
        {!path ? (
          <div className="p-8 text-[0.8125rem] text-muted">
            <h1 className="mb-1 text-[1.125rem] font-medium text-fg">Workspace</h1>
            The skills, commands, agents, doctrine and scripts that define how the agents behave. A change here applies to VS Code and the app alike. Every save is checked, then committed alone to the local repository.
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 border-b border-border px-4 py-2">
              <div className="min-w-0 flex-1 truncate font-mono text-[0.7812rem]">
                {path}
                {isNew && <span className="ml-2 text-accent">new</span>}
                {content !== original && <span className="ml-2 text-warn">unsaved</span>}
              </div>
              {(["edit", "preview", "history"] as Tab[])
                .filter((t) => (t === "preview" ? path.endsWith(".md") : t === "history" ? !isNew : true))
                .map((t) => (
                  <button key={t} onClick={() => setTab(t)} className={clsx("rounded-md px-2.5 py-1 text-[0.75rem]", tab === t ? "bg-panel text-fg" : "text-muted hover:text-fg")}>
                    {t === "edit" ? "Edit" : t === "preview" ? "Preview" : "History"}
                  </button>
                ))}
              <button onClick={() => setContent(original)} disabled={content === original} className="rounded-md border border-border px-2.5 py-1 text-[0.75rem] disabled:opacity-40">
                Revert
              </button>
              <button onClick={() => prepare.mutate()} disabled={content === original && !isNew} className="rounded-md bg-accent px-3 py-1 text-[0.75rem] text-white disabled:opacity-40">
                Save…
              </button>
            </div>
            {notice && <div className="border-b border-border bg-panel px-4 py-1.5 text-[0.75rem] text-muted">{notice}</div>}
            <div className="min-h-0 flex-1">
              {tab === "edit" && (
                path.endsWith(".md") ? (
                  <Suspense fallback={<div className="p-4 text-muted">Loading editor…</div>}>
                    <MarkdownEditor key={path} value={content} onChange={setContent} onSave={() => { if (content !== original) prepare.mutate(); }} />
                  </Suspense>
                ) : (
                  <textarea value={content} onChange={(e) => setContent(e.target.value)} className="h-full w-full resize-none bg-bg p-4 font-mono text-[0.7812rem] leading-5 outline-none" />
                )
              )}
              {tab === "preview" && (
                <div className="scroll-thin h-full overflow-y-auto">
                  <Markdown text={content} className="mx-auto max-w-3xl px-8 py-6" />
                </div>
              )}
              {tab === "history" && (
                <div className="scroll-thin h-full overflow-y-auto p-4">
                  {history.data?.length === 0 && <div className="text-[0.7812rem] text-faint">No commits for this file.</div>}
                  {(history.data ?? []).map((c) => (
                    <div key={c.rev} className="flex items-center gap-2 border-b border-border py-1.5 text-[0.7812rem]">
                      <History size="0.8125rem" className="text-faint" />
                      <button onClick={() => void showCommit(c.rev)} className="font-mono text-accent">
                        {c.short}
                      </button>
                      <span className="text-faint">{c.date.slice(0, 16).replace("T", " ")}</span>
                      <span className="min-w-0 flex-1 truncate">{c.message}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            {!isNew && (
              <div className="border-t border-border p-3">
                <div className="flex items-start gap-2">
                  <Sparkles size="0.9375rem" className="mt-1.5 text-accent" />
                  <textarea
                    value={improve}
                    onChange={(e) => setImprove(e.target.value)}
                    rows={2}
                    placeholder="Improve with an agent: describe the change in plain words. It reads .claude/ and edits a copy of this file only, with no web access."
                    className="flex-1 resize-none rounded-md border border-border bg-surface px-2 py-1.5 text-[0.7812rem] outline-none"
                  />
                  <button onClick={() => ask.mutate()} disabled={!improve.trim() || ask.isPending} className="rounded-md border border-border px-3 py-1.5 text-[0.75rem] hover:border-accent disabled:opacity-40">
                    {ask.isPending ? "Working…" : "Propose"}
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {review && (
        <Modal onClose={() => setReview(null)}>
          <h2 className="mb-2 text-[0.9375rem] font-medium">Save {path}</h2>
          {review.problems.length > 0 && (
            <div className="mb-3 rounded-md border border-bad/50 p-2 text-[0.7812rem] text-bad">
              <div className="font-medium">The checks block this save:</div>
              {review.problems.map((p, i) => (
                <div key={i} className="whitespace-pre-wrap">
                  {p}
                </div>
              ))}
            </div>
          )}
          <DiffView text={review.diff} />
          <label className="mt-3 block text-[0.75rem] text-muted">Commit message</label>
          <input value={message} onChange={(e) => setMessage(e.target.value)} className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-[0.8125rem]" />
          <div className="mt-3 flex justify-end gap-2">
            <button onClick={() => setReview(null)} className="rounded-md border border-border px-3 py-1.5 text-[0.7812rem]">
              Cancel
            </button>
            <button onClick={() => save.mutate()} disabled={review.problems.length > 0 || save.isPending} className="rounded-md bg-accent px-3 py-1.5 text-[0.7812rem] text-white disabled:opacity-40">
              {save.isPending ? "Checking…" : "Save and commit"}
            </button>
          </div>
        </Modal>
      )}

      {proposal && (
        <Modal onClose={() => setProposal(null)}>
          <h2 className="mb-2 text-[0.9375rem] font-medium">Proposed change</h2>
          {proposal.error && <div className="mb-2 text-[0.7812rem] text-bad">{proposal.error}</div>}
          {proposal.reply && <Markdown text={proposal.reply} className="mb-3 text-[0.8125rem]" />}
          <DiffView text={proposal.diff} />
          <div className="mt-3 flex justify-end gap-2">
            <button onClick={() => setProposal(null)} className="rounded-md border border-border px-3 py-1.5 text-[0.7812rem]">
              Reject
            </button>
            <button
              disabled={!proposal.diff.trim()}
              onClick={() => {
                setContent(proposal.content);
                setProposal(null);
                setTab("edit");
                setNotice("The proposal is in the editor. Edit it if you like, then Save.");
              }}
              className="rounded-md bg-accent px-3 py-1.5 text-[0.7812rem] text-white disabled:opacity-40"
            >
              Accept into the editor
            </button>
          </div>
        </Modal>
      )}

      {commit && (
        <Modal onClose={() => setCommit(null)}>
          <DiffView text={commit.text} />
          <div className="mt-3 flex justify-end gap-2">
            <button onClick={() => setCommit(null)} className="rounded-md border border-border px-3 py-1.5 text-[0.7812rem]">
              Close
            </button>
            <button
              onClick={() => {
                if (window.confirm(`Restore ${path} to ${commit.rev.slice(0, 7)}? The restore is itself a new commit.`)) restore.mutate(commit.rev);
              }}
              className="rounded-md bg-accent px-3 py-1.5 text-[0.7812rem] text-white"
            >
              Restore this version
            </button>
          </div>
        </Modal>
      )}

      {creating && (
        <Modal onClose={() => setCreating(false)}>
          <NewFileForm onCreate={(body) => create.mutate(body)} onCancel={() => setCreating(false)} />
        </Modal>
      )}
    </div>
  );
}

function NewFileForm({ onCreate, onCancel }: { onCreate: (b: { kind: string; name: string; description: string }) => void; onCancel: () => void }) {
  const [kind, setKind] = useState("skill");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <div className="space-y-3 text-[0.8125rem]">
      <h2 className="text-[0.9375rem] font-medium">New file from a template</h2>
      <div className="flex gap-2">
        {["skill", "command", "agent"].map((k) => (
          <button key={k} onClick={() => setKind(k)} className={clsx("rounded-md border px-3 py-1", kind === k ? "border-accent bg-accent-bg" : "border-border")}>
            {k}
          </button>
        ))}
      </div>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="name, in lower-case-with-hyphens" className="w-full rounded-md border border-border bg-surface px-2 py-1.5" />
      <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="description: one line on when to use it" className="w-full rounded-md border border-border bg-surface px-2 py-1.5" />
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="rounded-md border border-border px-3 py-1.5">
          Cancel
        </button>
        <button disabled={!name.trim()} onClick={() => onCreate({ kind, name: name.trim(), description })} className="rounded-md bg-accent px-3 py-1.5 text-white disabled:opacity-40">
          Create
        </button>
      </div>
    </div>
  );
}
