import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { X } from "lucide-react";
import { api } from "../lib/api";

export interface Subject {
  slug: string;
  path: string;
  role: "subject" | "template";
  format: string;
  editable: boolean;
  extracted: boolean;
  counts: Record<string, number>;
  deliverable: { version: string; file: string | null; ok: boolean | null; problems: number } | null;
}

interface Change {
  id: string;
  op: string;
  kind: string;
  target: string;
  where: string;
  context: string;
  before: string | null;
  after: string | null;
  rows: string[][] | null;
  fill: Record<string, string> | null;
  summary: string;
  rationale: string;
  basis: string;
  pairs_with: string[];
  evidence: { id: string; title: string; publisher: string; url: string }[];
  status: "proposed" | "accepted" | "rejected" | "stale";
  decision: { status: string; after?: string; note?: string } | null;
}

interface Plan {
  slug: string;
  path: string;
  format: string;
  changes: Change[];
  open: { where?: string; what?: string; why?: string }[];
  reviewed: boolean;
}

type Verdict = "accepted" | "rejected" | "";
interface Draft { status: Verdict; after: string; editing: boolean }

const fileName = (path: string) => path.split("/").pop() ?? path;
const OPS: Record<string, string> = {
  replace: "Replace", insert_after: "Add after", insert_before: "Add before", delete: "Remove",
  insert_table: "Add table", add_slide: "Add slide", set_cell: "Set cell",
};

function seed(plan: Plan): Record<string, Draft> {
  return Object.fromEntries(plan.changes.map((c) => [c.id, {
    status: c.status === "accepted" || c.status === "rejected" ? c.status : "",
    after: c.decision?.after ?? c.after ?? "",
    editing: false,
  }]));
}

export default function ChangesDialog({ run, subjects, onClose, onStarted }: {
  run: string;
  subjects: Subject[];
  onClose: () => void;
  onStarted: (session: string) => void;
}) {
  const client = useQueryClient();
  const documents = subjects.filter((s) => s.role === "subject");
  const [slug, setSlug] = useState(() => (documents.find((s) => Object.keys(s.counts).length) ?? documents[0])?.slug ?? "");
  const plan = useQuery({
    queryKey: ["changes", run, slug],
    queryFn: () => api.get<Plan>(`/api/runs/${encodeURIComponent(run)}/changes/${encodeURIComponent(slug)}`),
    enabled: Boolean(slug),
  });
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [mode, setMode] = useState<"tracked" | "clean">("tracked");
  const [author, setAuthor] = useState("");
  const [notes, setNotes] = useState("");
  useEffect(() => { if (plan.data) setDrafts(seed(plan.data)); }, [plan.data]);

  const save = useMutation({
    mutationFn: () => api.put<Plan>(`/api/runs/${encodeURIComponent(run)}/changes/${encodeURIComponent(slug)}/decisions`, {
      decisions: Object.fromEntries((plan.data?.changes ?? []).map((c) => {
        const d = drafts[c.id];
        return [c.id, { status: d?.status ?? "", after: d && d.after !== (c.after ?? "") ? d.after : undefined }];
      })),
    }),
    onSuccess: (result) => {
      client.setQueryData(["changes", run, slug], result);
      void client.invalidateQueries({ queryKey: ["subjects", run] });
    },
  });
  const apply = useMutation({
    mutationFn: async () => {
      await save.mutateAsync();
      return api.post<{ session: string }>(`/api/runs/${encodeURIComponent(run)}/apply-changes`, { slug, mode, author, notes });
    },
    onSuccess: (result) => onStarted(result.session),
  });
  const busy = save.isPending || apply.isPending;

  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose, busy]);

  const changes = useMemo(() => plan.data?.changes ?? [], [plan.data]);
  const tally = useMemo(() => {
    const t = { accepted: 0, rejected: 0, undecided: 0 };
    for (const c of changes) {
      const s = drafts[c.id]?.status;
      if (s === "accepted") t.accepted += 1; else if (s === "rejected") t.rejected += 1; else t.undecided += 1;
    }
    return t;
  }, [changes, drafts]);
  const setAll = (status: Verdict) => setDrafts((cur) => Object.fromEntries(Object.entries(cur).map(([k, d]) => [k, { ...d, status }])));
  const setOne = (id: string, patch: Partial<Draft>) => setDrafts((cur) => ({ ...cur, [id]: { ...cur[id], ...patch } }));
  const decide = (c: Change, status: Verdict) => {
    // Paired changes stand or fall together: deciding one decides its partners in this document.
    const partners = c.pairs_with.filter((p) => !p.includes(":") && changes.some((x) => x.id === p));
    setDrafts((cur) => {
      const next = { ...cur, [c.id]: { ...cur[c.id], status } };
      for (const p of partners) next[p] = { ...next[p], status };
      return next;
    });
  };
  const current = documents.find((s) => s.slug === slug);
  const docx = plan.data?.format === "docx";
  const rebuild = current ? !current.editable : false;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-labelledby="changes-title" className="flex max-h-[92vh] w-full max-w-3xl flex-col rounded-xl border border-border bg-surface shadow-2xl">
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 id="changes-title" className="text-[1rem] font-semibold">Proposed changes</h2>
            <p className="mt-1 text-[0.7812rem] text-muted">Accept, reject or rewrite each change. Only accepted changes reach the document; the original file is never modified.</p>
          </div>
          <button onClick={onClose} disabled={busy} aria-label="Close" className="rounded p-1 text-muted hover:bg-panel disabled:opacity-40"><X size="1rem" /></button>
        </div>
        {documents.length > 1 && (
          <div className="flex flex-wrap gap-1 border-b border-border px-5 py-2">
            {documents.map((s) => (
              <button key={s.slug} onClick={() => setSlug(s.slug)} disabled={busy} className={clsx("max-w-[16rem] truncate rounded-md px-2.5 py-1 text-[0.75rem]", s.slug === slug ? "bg-panel font-medium text-fg" : "text-muted hover:text-fg")}>
                {fileName(s.path)}{Object.keys(s.counts).length ? "" : " · no plan"}
              </button>
            ))}
          </div>
        )}
        <div className="scroll-thin flex-1 space-y-3 overflow-y-auto px-5 py-4 text-[0.8125rem]">
          {plan.isLoading && <p className="text-faint">Loading…</p>}
          {plan.isError && <p className="text-bad">{(plan.error as Error).message}</p>}
          {plan.data && changes.length === 0 && <p className="text-muted">No changes proposed for {fileName(plan.data.path)} yet. Run /changes to propose them.</p>}
          {plan.data && changes.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-[0.75rem]">
              <span className="text-muted">{tally.accepted} accepted · {tally.rejected} rejected · {tally.undecided} undecided</span>
              {!plan.data.reviewed && <span className="text-warn">The plan has not been reviewed independently since it last changed.</span>}
              <span className="flex-1" />
              <button onClick={() => setAll("accepted")} className="rounded-md border border-border px-2 py-0.5 hover:border-accent">Accept all</button>
              <button onClick={() => setAll("rejected")} className="rounded-md border border-border px-2 py-0.5 hover:border-accent">Reject all</button>
              <button onClick={() => setAll("")} className="rounded-md border border-border px-2 py-0.5 hover:border-accent">Clear</button>
            </div>
          )}
          {changes.map((c) => {
            const d = drafts[c.id] ?? { status: "", after: c.after ?? "", editing: false };
            const rewritten = d.after !== (c.after ?? "");
            return (
              <section key={c.id} className={clsx("rounded-lg border p-3", d.status === "accepted" ? "border-accent" : d.status === "rejected" ? "border-border opacity-60" : "border-border")}>
                <div className="flex flex-wrap items-center gap-2 text-[0.6875rem] uppercase tracking-wide text-faint">
                  <span className="font-medium text-muted">{c.id}</span>
                  <span>{OPS[c.op] ?? c.op}</span>
                  <span>· {c.kind}</span>
                  {c.where && <span className="normal-case tracking-normal">· {c.where}</span>}
                  {c.status === "stale" && <span className="normal-case tracking-normal text-warn">· changed since you decided</span>}
                  {c.pairs_with.length > 0 && <span className="normal-case tracking-normal">· goes with {c.pairs_with.join(", ")}</span>}
                </div>
                {c.summary && <h3 className="mt-1 font-medium">{c.summary}</h3>}
                {c.context && <p className="mt-2 border-l-2 border-border pl-2 text-[0.75rem] text-faint">{c.op === "insert_before" ? "Before" : "After"}: {c.context}</p>}
                {c.before && <p className="mt-2 whitespace-pre-wrap rounded bg-panel px-2 py-1 text-muted line-through decoration-faint">{c.before}</p>}
                {c.op !== "delete" && (d.editing ? (
                  <textarea value={d.after} onChange={(e) => setOne(c.id, { after: e.target.value })} rows={Math.min(10, Math.max(3, Math.ceil(d.after.length / 90)))} className="mt-2 w-full resize-y rounded-md border border-accent bg-bg px-2 py-1 outline-none" />
                ) : c.after !== null && (
                  <p className="mt-2 whitespace-pre-wrap rounded bg-accent-bg px-2 py-1">{d.after}</p>
                ))}
                {c.rows && <table className="mt-2 w-full text-[0.75rem]"><tbody>{c.rows.map((r, i) => <tr key={i} className={i === 0 ? "font-medium" : ""}>{r.map((v, j) => <td key={j} className="border border-border px-1.5 py-0.5">{v}</td>)}</tr>)}</tbody></table>}
                {c.fill && <ul className="mt-2 list-disc pl-5 text-[0.75rem]">{Object.entries(c.fill).map(([k, v]) => <li key={k} className="whitespace-pre-wrap">{v}</li>)}</ul>}
                {c.rationale && <p className="mt-2 text-[0.75rem] text-muted">{c.rationale}</p>}
                {c.evidence.length > 0 && (
                  <p className="mt-1 text-[0.7188rem] text-faint">Sources: {c.evidence.map((e, i) => (
                    <span key={e.id}>{i ? "; " : ""}{e.url.startsWith("http") ? <a href={e.url} target="_blank" rel="noreferrer" className="underline hover:text-fg">{e.title || e.publisher || e.id}</a> : (e.title || e.publisher || e.id)}</span>
                  ))}</p>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-2 text-[0.75rem]">
                  <button onClick={() => decide(c, d.status === "accepted" ? "" : "accepted")} className={clsx("rounded-md border px-2.5 py-1", d.status === "accepted" ? "border-accent bg-accent text-white" : "border-border hover:border-accent")}>Accept</button>
                  <button onClick={() => decide(c, d.status === "rejected" ? "" : "rejected")} className={clsx("rounded-md border px-2.5 py-1", d.status === "rejected" ? "border-fg bg-panel" : "border-border hover:border-accent")}>Reject</button>
                  {c.op !== "delete" && c.after !== null && <button onClick={() => setOne(c.id, { editing: !d.editing })} className="rounded-md px-2 py-1 text-muted hover:text-fg">{d.editing ? "Done" : "Rewrite"}</button>}
                  {rewritten && <button onClick={() => setOne(c.id, { after: c.after ?? "", editing: false })} className="rounded-md px-2 py-1 text-muted hover:text-fg">Restore proposal</button>}
                  {rewritten && <span className="text-faint">Your wording will be used exactly.</span>}
                </div>
              </section>
            );
          })}
          {plan.data && plan.data.open.length > 0 && (
            <section className="rounded-lg border border-border p-3">
              <h3 className="font-medium">Still needed from you</h3>
              <ul className="mt-1 list-disc pl-5 text-[0.75rem] text-muted">
                {plan.data.open.map((o, i) => <li key={i}>{[o.where, o.what].filter(Boolean).join(": ")}{o.why ? ` (${o.why})` : ""}</li>)}
              </ul>
            </section>
          )}
          {plan.data && changes.length > 0 && (
            <section className="space-y-2 rounded-lg border border-border p-3">
              <h3 className="font-medium">{rebuild ? "Rebuild" : "Apply"}</h3>
              {rebuild && <p className="text-[0.75rem] text-muted">This file is a PDF, so it cannot be edited in place. The agent builds a new file in its design, carrying the accepted changes.</p>}
              {docx && (
                <div className="flex flex-wrap gap-2">
                  {([["tracked", "Tracked changes", "Every change shows in Word's review pane for you to accept there."], ["clean", "Clean copy", "The changes are made directly, as if typed in."]] as const).map(([value, label, description]) => (
                    <button key={value} type="button" onClick={() => setMode(value)} className={clsx("min-w-[12rem] flex-1 rounded-lg border p-2 text-left", mode === value ? "border-accent bg-accent-bg" : "border-border hover:border-accent")}>
                      <span className="block font-medium">{label}</span>
                      <span className="mt-0.5 block text-[0.75rem] text-muted">{description}</span>
                    </button>
                  ))}
                </div>
              )}
              {docx && mode === "tracked" && <input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Name shown on tracked changes (default: Revision)" className="w-full rounded-md border border-border bg-bg px-3 py-1.5 outline-none focus:border-accent" />}
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="Anything the agent should know (optional)" className="w-full resize-y rounded-md border border-border bg-bg px-3 py-1.5 outline-none focus:border-accent" />
            </section>
          )}
          {(save.isError || apply.isError) && <p role="alert" className="text-bad">{((save.error ?? apply.error) as Error).message}</p>}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3 text-[0.7812rem]">
          {save.isSuccess && !busy && <span className="mr-auto text-faint">Decisions saved.</span>}
          <button onClick={onClose} disabled={busy} className="rounded-md border border-border px-3 py-1.5 disabled:opacity-40">Close</button>
          <button onClick={() => save.mutate()} disabled={busy || !changes.length} className="rounded-md border border-accent px-3 py-1.5 text-accent disabled:opacity-40">{save.isPending && !apply.isPending ? "Saving…" : "Save decisions"}</button>
          <button onClick={() => apply.mutate()} disabled={busy || tally.accepted === 0} className="rounded-md bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-40">
            {apply.isPending ? "Starting…" : `${rebuild ? "Rebuild" : "Apply"} ${tally.accepted} accepted change${tally.accepted === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    </div>
  );
}
