import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Highlighter, MessageSquarePlus, Pencil, RotateCcw, Trash2, X } from "lucide-react";
import { api, q } from "../lib/api";
import { post } from "../lib/live";
import { prefs, setPref } from "../lib/prefs";

export interface Comment {
  id: string;
  doc: string;
  kind: "text" | "figure" | "table";
  target: string;
  quote: string;
  text: string;
  author: string;
  created: string;
  resolved: boolean;
  type?: "comment" | "highlight";
  color?: string;
  found: boolean;
  start: number | null;
  end: number | null;
  line: number | null;
}

/** What a new comment is attached to: a passage selected in the HTML, or a figure or table. */
export interface Anchor {
  label: string;
  selection?: { text: string; prefix: string; suffix: string; heading: string };
  element?: { kind: "figure" | "table"; number?: number; id?: string };
}

export function useComments(run: string, doc: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["comments", run, doc],
    queryFn: () => api.get<{ doc: string; comments: Comment[] }>(`/api/runs/${encodeURIComponent(run)}/comments?${q(doc ? { doc } : {})}`),
    enabled: enabled && Boolean(doc),
    refetchInterval: 15_000,
  });
}

// Highlight colours: the passage's tint in the page, and a stronger edge for the list.
export const HIGHLIGHTS: { name: string; fill: string; edge: string }[] = [
  { name: "yellow", fill: "#FFF3A0", edge: "#E5B300" },
  { name: "green", fill: "#C9F2C3", edge: "#3FA34D" },
  { name: "blue", fill: "#CFE5FF", edge: "#3B82D6" },
  { name: "pink", fill: "#FFD4E8", edge: "#D6458B" },
];
export const highlightEdge = (c: Comment) => HIGHLIGHTS.find((h) => h.name === c.color)?.edge ?? "#E5B300";
export const isHighlight = (c: Comment) => c.type === "highlight";

/** Highlight a passage, figure or table straight away, with no words. */
export function useHighlight(run: string, doc: string | undefined, onDone?: (c: Comment) => void) {
  const changed = useCommentChanged(run);
  return useMutation({
    mutationFn: ({ anchor, color }: { anchor: Anchor; color: string }) => {
      setPref("highlight_color", color);
      return api.post<Comment>(`/api/runs/${encodeURIComponent(run)}/comments`, {
        doc, text: "", author: prefs().comment_author ?? "", highlight: true, color, selection: anchor.selection, element: anchor.element,
      });
    },
    onSuccess: (c) => { changed(); onDone?.(c); },
  });
}

/** Four colour dots; the one last used is ringed. */
export function ColourDots({ onPick, current, size = "0.875rem" }: { onPick: (color: string) => void; current?: string; size?: string }) {
  return (
    <span className="flex items-center gap-1">
      {HIGHLIGHTS.map((h) => (
        <button
          key={h.name}
          onMouseDown={(e) => e.preventDefault()}
          onClick={(e) => { e.stopPropagation(); onPick(h.name); }}
          title={`Highlight ${h.name}`}
          aria-label={`Highlight ${h.name}`}
          style={{ width: size, height: size, background: h.fill, borderColor: h.edge }}
          className={clsx("rounded-full border", current === h.name && "ring-2 ring-accent ring-offset-1")}
        />
      ))}
    </span>
  );
}

function useCommentChanged(run: string) {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["comments", run] });
    void client.invalidateQueries({ queryKey: ["render", run] });
    post({ type: "comments-changed", run });
  };
}

const snippet = (c: Comment) => {
  if (c.kind === "figure") return `Figure ${c.target.slice(1)}`;
  if (c.kind === "table") return `Table ${c.target.slice(1)}: ${c.quote.replace(/\[E\d+[^\]]*\]/g, "").trim()}`;
  const plain = c.quote.replace(/\[E\d+[^\]]*\]|[*_`#>]/g, "").replace(/\s+/g, " ").trim();
  return plain.length > 140 ? `${plain.slice(0, 140)}…` : plain;
};

const when = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

function CommentCard({ run, comment, active, onSelect }: { run: string; comment: Comment; active: boolean; onSelect: (c: Comment) => void }) {
  const changed = useCommentChanged(run);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(comment.text);
  const card = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active) card.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);
  const patch = useMutation({
    mutationFn: (body: { text?: string; resolved?: boolean; color?: string }) => api.patch(`/api/runs/${encodeURIComponent(run)}/comments/${comment.id}`, body),
    onSuccess: () => { setEditing(false); changed(); },
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/runs/${encodeURIComponent(run)}/comments/${comment.id}`),
    onSuccess: changed,
  });
  return (
    <div
      ref={card}
      onClick={() => onSelect(comment)}
      className={clsx(
        "cursor-pointer rounded-md border bg-surface p-2 text-[0.75rem]",
        active ? "border-accent ring-1 ring-accent" : "border-border hover:border-accent/60",
        comment.resolved && "opacity-60",
      )}
    >
      <div style={comment.found && isHighlight(comment) ? { borderColor: highlightEdge(comment) } : undefined} className={clsx("mb-1 border-l-2 pl-2 text-[0.7188rem] text-muted", comment.found ? "border-[#E5B300]" : "border-bad")}>
        {comment.found ? snippet(comment) : <span className="text-bad">The passage is no longer in the document: “{snippet(comment)}”</span>}
      </div>
      {editing ? (
        <div onClick={(e) => e.stopPropagation()}>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} autoFocus placeholder={isHighlight(comment) ? "A note turns the highlight into a comment" : undefined} className="w-full resize-y rounded border border-border bg-bg p-1.5 outline-none focus:border-accent" />
          <div className="mt-1 flex gap-1.5">
            <button onClick={() => patch.mutate({ text })} disabled={!text.trim() || patch.isPending} className="rounded bg-accent px-2 py-0.5 text-white disabled:opacity-40">Save</button>
            <button onClick={() => { setEditing(false); setText(comment.text); }} className="rounded border border-border px-2 py-0.5">Cancel</button>
          </div>
        </div>
      ) : isHighlight(comment) ? (
        <div className="flex items-center gap-2 text-faint" onClick={(e) => e.stopPropagation()}>
          <Highlighter size="0.75rem" /> Highlight
          <div className="flex-1" />
          <ColourDots current={comment.color} size="0.75rem" onPick={(color) => patch.mutate({ color })} />
        </div>
      ) : (
        <div className="whitespace-pre-wrap">{comment.text}</div>
      )}
      <div className="mt-1.5 flex items-center gap-1 text-[0.6875rem] text-faint">
        <span className="truncate">{comment.author} · {when(comment.created)}{comment.line ? ` · line ${comment.line}` : ""}</span>
        <div className="flex-1" />
        {!editing && (
          <button onClick={(e) => { e.stopPropagation(); setEditing(true); }} title={isHighlight(comment) ? "Add a note: it becomes a comment" : "Edit the comment"} aria-label={isHighlight(comment) ? "Add a note" : "Edit the comment"} className="rounded p-0.5 hover:text-fg"><Pencil size="0.75rem" /></button>
        )}
        {!isHighlight(comment) && <button onClick={(e) => { e.stopPropagation(); patch.mutate({ resolved: !comment.resolved }); }} title={comment.resolved ? "Reopen" : "Resolve: keep it, but take it out of the document and the exports"} aria-label={comment.resolved ? "Reopen" : "Resolve"} className="rounded p-0.5 hover:text-fg">
          {comment.resolved ? <RotateCcw size="0.75rem" /> : <Check size="0.75rem" />}
        </button>}
        <button onClick={(e) => { e.stopPropagation(); if (isHighlight(comment) || window.confirm("Delete this comment?")) remove.mutate(); }} title={isHighlight(comment) ? "Remove the highlight" : "Delete"} aria-label={isHighlight(comment) ? "Remove the highlight" : "Delete the comment"} className="rounded p-0.5 hover:text-bad"><Trash2 size="0.75rem" /></button>
      </div>
      {(patch.isError || remove.isError) && <div className="mt-1 text-bad">{((patch.error ?? remove.error) as Error).message}</div>}
    </div>
  );
}

export function CommentList({ run, comments, active, onSelect, empty }: {
  run: string;
  comments: Comment[];
  active: string | null;
  onSelect: (c: Comment) => void;
  empty: string;
}) {
  const [showResolved, setShowResolved] = useState(false);
  const open = comments.filter((c) => !c.resolved);
  const shown = showResolved ? comments : open;
  return (
    <div className="space-y-2">
      {shown.length === 0 && <div className="text-[0.75rem] text-faint">{empty}</div>}
      {shown.map((c) => <CommentCard key={c.id} run={run} comment={c} active={active === c.id} onSelect={onSelect} />)}
      {comments.length > open.length && (
        <button onClick={() => setShowResolved(!showResolved)} className="text-[0.7188rem] text-muted underline">
          {showResolved ? "Hide resolved" : `Show ${comments.length - open.length} resolved`}
        </button>
      )}
    </div>
  );
}

function Composer({ run, doc, anchor, onDone }: { run: string; doc: string; anchor: Anchor; onDone: (id: string | null) => void }) {
  const changed = useCommentChanged(run);
  const [text, setText] = useState("");
  const [author, setAuthor] = useState(() => prefs().comment_author ?? "");
  const highlight = useHighlight(run, doc, (c) => onDone(c.id));
  const create = useMutation({
    mutationFn: () => api.post<Comment>(`/api/runs/${encodeURIComponent(run)}/comments`, { doc, text, author, selection: anchor.selection, element: anchor.element }),
    onSuccess: (c) => {
      if (author !== (prefs().comment_author ?? "")) setPref("comment_author", author);
      changed();
      onDone(c.id);
    },
  });
  return (
    <div className="mb-3 rounded-md border border-accent bg-surface p-2 text-[0.75rem]">
      <div className="mb-1.5 flex items-center gap-1 font-medium">
        <MessageSquarePlus size="0.8125rem" className="text-accent" /> New comment
        <div className="flex-1" />
        <button onClick={() => onDone(null)} title="Cancel" aria-label="Cancel the comment" className="rounded p-0.5 text-faint hover:text-fg"><X size="0.75rem" /></button>
      </div>
      <div className="mb-1.5 border-l-2 border-[#E5B300] pl-2 text-[0.7188rem] text-muted">{anchor.label}</div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && text.trim()) create.mutate(); }}
        rows={4}
        autoFocus
        placeholder="What should change here?"
        className="w-full resize-y rounded border border-border bg-bg p-1.5 outline-none focus:border-accent"
      />
      <div className="mt-1.5 flex items-center gap-1.5 text-[0.7188rem] text-muted">
        <Highlighter size="0.75rem" /> Or just highlight it:
        <ColourDots current={prefs().highlight_color ?? "yellow"} onPick={(color) => highlight.mutate({ anchor, color })} />
      </div>
      <div className="mt-1.5 flex items-center gap-1.5">
        <input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Your name" aria-label="Your name" maxLength={80} className="min-w-0 flex-1 rounded border border-border bg-bg px-1.5 py-0.5 outline-none focus:border-accent" />
        <button onClick={() => create.mutate()} disabled={!text.trim() || create.isPending} title="Add the comment (⌘ Enter)" className="rounded bg-accent px-2.5 py-0.5 text-white disabled:opacity-40">
          {create.isPending ? "Adding…" : "Comment"}
        </button>
      </div>
      {(create.isError || highlight.isError) && <div className="mt-1 text-bad">{((create.error ?? highlight.error) as Error).message}</div>}
    </div>
  );
}

/** The HTML view's comments panel: the new comment being written, then every comment. */
export default function CommentsPanel({ run, doc, anchor, active, onAnchorDone, onSelect, onClose }: {
  run: string;
  doc: string;
  anchor: Anchor | null;
  active: string | null;
  onAnchorDone: (id: string | null) => void;
  onSelect: (c: Comment) => void;
  onClose: () => void;
}) {
  const comments = useComments(run, doc);
  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[0.6875rem] font-medium uppercase tracking-wide text-faint">Comments</span>
        <span className="text-[0.6875rem] text-faint">{comments.data ? comments.data.comments.filter((c) => !c.resolved).length : ""}</span>
        <div className="flex-1" />
        <button onClick={onClose} title="Close the comments panel" aria-label="Close the comments panel" className="rounded p-0.5 text-faint hover:text-fg"><X size="0.8125rem" /></button>
      </div>
      <p className="mb-3 text-[0.7188rem] text-muted">
        Select text in the document, then pick a colour to highlight it or choose Comment; or click a figure or a table. Both show in the Edit tab. Comments travel to Word as Word comments and to the PDF as footnotes; highlights are yours alone and stay out of exports.
      </p>
      {anchor && <Composer key={anchor.label} run={run} doc={doc} anchor={anchor} onDone={onAnchorDone} />}
      {comments.isError && <div className="text-[0.75rem] text-bad">{(comments.error as Error).message}</div>}
      {comments.data && <CommentList run={run} comments={comments.data.comments} active={active} onSelect={onSelect} empty="No comments yet." />}
    </div>
  );
}
