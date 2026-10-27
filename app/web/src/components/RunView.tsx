import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Circle, Code2, Download, ExternalLink, FileDown, FolderSearch, ListChecks, MessageSquare, MessageSquarePlus, Minus, Palette, PanelRight, PanelRightClose, Pencil, Plus, RefreshCw, RotateCcw, Trash2, Undo2, Upload, X } from "lucide-react";
import Panel, { CENTER, PANELS } from "./Panel";
import { api, ApiError, fileUrl, getText, q, renderedUrl } from "../lib/api";
import { bytes, day } from "../lib/format";
import type { RunDetail, SessionDetail } from "../lib/types";
import { forget, place, remember, rememberDraft, rememberScroll } from "../lib/places";
import { prefs, setPref } from "../lib/prefs";
import { useUi } from "../stores/ui";
import Markdown from "./Markdown";
import AppearancePanel from "./AppearancePanel";
import type { AppearancePick, AppearanceResponse, AppearanceValues } from "./AppearancePanel";
import SessionView from "./SessionView";
import CritiqueQuestionsDialog, { type CritiqueAnswers, type CritiqueQuestion } from "./CritiqueQuestionsDialog";
import ChangesDialog, { type Subject } from "./ChangesDialog";
import OfficePane, { OfficeHtml, type OfficeFocus } from "./OfficePane";
import CommentsPanel, { ColourDots, CommentList, useComments, useHighlight, type Anchor, type Comment } from "./CommentsPanel";
import type { EditorMark } from "./MarkdownEditor";
import { listen, openPopout, post } from "../lib/live";
import { subscribe } from "../lib/socket";

const MarkdownEditor = lazy(() => import("./MarkdownEditor"));

const TEXT = /\.(md|txt|jsonl|json|csv|tsv|py|ya?ml|bib)$/i;
type Tab = "document" | "chat" | "html" | "edit" | "file";
interface OfficeOutput { path: string; slug: string; version: string; format: "xlsx" | "pptx"; label: string; editable_master?: string | null }

interface Rendered {
  html: string;
  figures: { name: string; files: Record<string, string> }[];
  cached: boolean;
  built: number;
  log: string;
}

interface Exported {
  files: string[];
  folder: string;
  check: string;
  comments: number;
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
      <a className="text-[0.8125rem] text-accent underline" href={fileUrl(run, path)} target="_blank" rel="noreferrer">
        Open {path}
      </a>
    );
  }
  if (text.isLoading) return <div className="text-faint">Loading…</div>;
  if (text.isError) return <div className="text-bad">{(text.error as Error).message}</div>;
  const body = String(text.data ?? "");
  if (path.endsWith(".md")) return <Markdown text={body} run={run} />;
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
              <pre key={i} className={clsx("whitespace-pre-wrap rounded bg-panel p-2 font-mono text-[0.7188rem]", bad && "border border-bad text-bad")}>
                {pretty}
              </pre>
            );
          })}
      </div>
    );
  }
  return <pre className="whitespace-pre-wrap font-mono text-[0.75rem]">{body}</pre>;
}

// Where each comment sits in the editor's text. On the saved text the server's offsets hold;
// after edits the quoted Markdown is looked for, nearest where it was.
function placeComments(list: Comment[] | undefined, text: string, saved: boolean, active: string | null): EditorMark[] {
  const out: EditorMark[] = [];
  for (const c of list ?? []) {
    if (c.resolved || !c.found || c.start === null || c.end === null) continue;
    let from = c.start;
    let to = c.end;
    if (!saved || text.slice(from, to) !== c.quote) {
      let best = -1;
      for (let at = text.indexOf(c.quote); at >= 0 && c.quote; at = text.indexOf(c.quote, at + 1)) {
        if (best < 0 || Math.abs(at - c.start) < Math.abs(best - c.start)) best = at;
      }
      if (best < 0) continue;
      from = best;
      to = best + c.quote.length;
    }
    const highlight = c.type === "highlight";
    out.push({ id: c.id, from, to, title: highlight ? "Highlight" : `${c.author}: ${c.text}`, active: c.id === active, tone: highlight ? c.color ?? "yellow" : undefined });
  }
  return out;
}

interface HandEdits {
  pending: boolean;
  sections: string[];
  added: number;
  removed: number;
  notes: boolean;
  auto: boolean;
}

/** Saved hand edits no agent has absorbed: keep them as written, or have the agent absorb them. */
function HandEditsBar({ run, path, dirty, onAbsorb }: { run: string; path: string; dirty: boolean; onAbsorb?: (session: string) => void }) {
  const client = useQueryClient();
  const edits = useQuery({
    queryKey: ["edits", run, path],
    queryFn: () => api.get<HandEdits>(`/api/runs/${encodeURIComponent(run)}/edits?${q({ doc: path })}`),
    refetchInterval: 10_000,
  });
  const [note, setNote] = useState("");
  const keep = useMutation({
    mutationFn: () => api.post<{ learned: string[] }>(`/api/runs/${encodeURIComponent(run)}/edits/keep`, { doc: path }),
    onSuccess: () => {
      setNote("Kept as written. No agent turn ran; your text is now the baseline the next round works from.");
      void client.invalidateQueries({ queryKey: ["edits", run, path] });
    },
  });
  const absorb = useMutation({
    mutationFn: () => api.post<{ session: string }>(`/api/runs/${encodeURIComponent(run)}/edits/absorb`, { doc: path }),
    onSuccess: (r) => {
      setNote("Started /user-edits in the project's Chat tab.");
      void client.invalidateQueries({ queryKey: ["edits", run, path] });
      onAbsorb?.(r.session);
    },
  });
  const e = edits.data;
  if (!e?.pending) {
    return note ? <div className="border-b border-border px-4 py-1.5 text-[0.75rem] text-good">{note}</div> : null;
  }
  const busy = keep.isPending || absorb.isPending;
  const where = e.sections.length ? e.sections.slice(0, 4).join(", ") + (e.sections.length > 4 ? ` and ${e.sections.length - 4} more` : "") : "the document";
  return (
    <div className="border-b border-border bg-panel/60 px-4 py-2 text-[0.75rem]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-full bg-warn" />
        <span className="min-w-0 flex-1">
          Your edits since the agent last wrote: <span className="font-medium">{where}</span>
          <span className="text-faint"> · +{e.added} / −{e.removed} words</span>
        </span>
        <button
          onClick={() => keep.mutate()}
          disabled={dirty || busy}
          title={dirty ? "Save first" : "For finished, precise edits: closes them by script, with no agent turn"}
          className={clsx("rounded-md px-2.5 py-1 disabled:opacity-40", e.notes ? "border border-border hover:border-accent" : "bg-accent text-white")}
        >
          {keep.isPending ? "Keeping…" : "Keep as written"}
        </button>
        <button
          onClick={() => absorb.mutate()}
          disabled={dirty || busy}
          title={dirty ? "Save first" : "For notes, stubs and inserted pieces: /user-edits works them into the document"}
          className={clsx("rounded-md px-2.5 py-1 disabled:opacity-40", e.notes ? "bg-accent text-white" : "border border-border hover:border-accent")}
        >
          {absorb.isPending ? "Starting…" : "Absorb with the agent"}
        </button>
      </div>
      {e.notes && <div className="mt-1 text-muted">Part of what you added reads like a note for the agent, so absorbing it is suggested.</div>}
      {dirty && <div className="mt-1 text-muted">Save first: these act on the saved file.</div>}
      {(keep.isError || absorb.isError) && <pre className="mt-1 whitespace-pre-wrap text-bad">{((keep.error ?? absorb.error) as Error).message}</pre>}
    </div>
  );
}

export function EditPane({ run, path, isMaster, onSaved, popout = false, onPopout, onAbsorb }: {
  run: string;
  path: string;
  isMaster: boolean;
  onSaved: () => void;
  popout?: boolean;
  onPopout?: () => void;
  onAbsorb?: (session: string) => void;
}) {
  const client = useQueryClient();
  const kept = place(run).drafts[path];
  const [text, setText] = useState(kept?.text ?? "");
  const [original, setOriginal] = useState(kept?.original ?? "");
  const [mtime, setMtime] = useState<number | null>(kept?.mtime ?? null);
  const [message, setMessage] = useState("");
  const [conflict, setConflict] = useState(false);
  const [selectedSection, setSelectedSection] = useState("");
  const comments = useComments(run, path, isMaster);
  const [commentsOpen, setCommentsOpenState] = useState(() => place(run).editComments ?? true);
  const setCommentsOpen = (open: boolean) => {
    setCommentsOpenState(open);
    remember(run, { editComments: open });
  };
  const [activeComment, setActiveComment] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ from: number; to: number; key: number } | null>(null);
  const current = useRef({ text, original });
  current.current = { text, original };
  const finalSections = useQuery({
    queryKey: ["final-sections", run, path],
    queryFn: () => api.get<{ heading: string; final: boolean }[]>(`/api/runs/${encodeURIComponent(run)}/final-sections`),
    enabled: isMaster,
  });
  const selectedFinal = finalSections.data?.find((section) => section.heading === selectedSection)?.final ?? false;
  const setFinal = useMutation({
    mutationFn: (final: boolean) => api.put(`/api/runs/${encodeURIComponent(run)}/final-sections`, { heading: selectedSection, final }),
    onSuccess: () => void finalSections.refetch(),
  });
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
  // A popped-out editor shows its changes in the main window's HTML view as they are typed.
  useEffect(() => {
    if (!popout || !original) return;
    const timer = setTimeout(() => post({ type: "draft", run, path, text, dirty: text !== original }), 700);
    return () => clearTimeout(timer);
  }, [popout, run, path, text, original]);
  const marks = useMemo(
    // `original` moves when the file loads or saves: the highlights are placed on that text.
    () => placeComments(comments.data?.comments, current.current.text, current.current.text === original, activeComment),
    [comments.data, activeComment, original],
  );
  const showComment = (id: string, tell: boolean) => {
    setActiveComment(id);
    const mark = placeComments(comments.data?.comments, current.current.text, current.current.text === current.current.original, id).find((m) => m.id === id);
    if (mark) setFocus({ from: mark.from, to: mark.to, key: Date.now() });
    if (tell) post({ type: "focus-comment", run, id, to: "html" });
  };
  const showRef = useRef(showComment);
  showRef.current = showComment;
  useEffect(
    () =>
      listen((m) => {
        if (m.type === "focus-comment" && m.run === run && m.to === "editor") {
          setCommentsOpen(true);
          showRef.current(m.id, false);
        } else if (m.type === "comments-changed" && m.run === run) void comments.refetch();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [run],
  );
  const save = useMutation({
    mutationFn: () => api.put<{ mtime: number }>(`/api/runs/${encodeURIComponent(run)}/file`, { path, content: text, mtime }),
    onSuccess: (r) => {
      setMtime(r.mtime);
      setOriginal(text);
      setMessage("Saved. The HTML view re-renders from this file.");
      void client.invalidateQueries({ queryKey: ["edits", run, path] });
      onSaved();
      post({ type: "saved", run, path });
      void finalSections.refetch();
      void comments.refetch();
    },
    onError: (e) => {
      setConflict(e instanceof ApiError && e.status === 409 && e.message.includes("changed on disk"));
      setMessage((e as Error).message);
    },
  });
  const dirty = text !== original;
  const openCount = comments.data?.comments.filter((c) => !c.resolved).length ?? 0;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-[0.7812rem]">
        <span className="font-mono">{path}</span>
        {dirty && <span className="text-warn">unsaved</span>}
        {isMaster && (finalSections.data?.length ?? 0) > 0 && (
          <>
            <select aria-label="Report section" value={selectedSection} onChange={(e) => setSelectedSection(e.target.value)} className="max-w-56 rounded-md border border-border bg-surface px-2 py-1">
              <option value="">Select section</option>
              {finalSections.data?.map((section) => <option key={section.heading} value={section.heading}>{section.final ? "Final: " : ""}{section.heading}</option>)}
            </select>
            <button disabled={!selectedSection || (dirty && !selectedFinal) || setFinal.isPending} onClick={() => setFinal.mutate(!selectedFinal)} className="rounded-md border border-border px-2.5 py-1 disabled:opacity-40" title={dirty && !selectedFinal ? "Save the report before marking this section final" : undefined}>
              {selectedFinal ? "Reopen section" : "Mark final"}
            </button>
          </>
        )}
        <div className="flex-1" />
        {isMaster && (
          <button onClick={() => setCommentsOpen(!commentsOpen)} title={commentsOpen ? "Hide the comments" : "Show the comments"} className={clsx("flex items-center gap-1 rounded-md border px-2.5 py-1", commentsOpen ? "border-accent text-accent" : "border-border hover:border-accent")}>
            <MessageSquare size="0.8125rem" /> Comments{openCount ? ` · ${openCount}` : ""}
          </button>
        )}
        {onPopout && (
          <button onClick={onPopout} title="Open the editor in its own window, to edit on one screen and watch the HTML on another" className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 hover:border-accent">
            <ExternalLink size="0.8125rem" /> Pop out
          </button>
        )}
        {popout && (
          <button onClick={() => window.close()} title="Close this window; unsaved text goes back to the main window" className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 hover:border-accent">
            <Undo2 size="0.8125rem" /> Back to the main window
          </button>
        )}
        <button onClick={() => setText(original)} disabled={!dirty} className="rounded-md border border-border px-2.5 py-1 disabled:opacity-40">
          Revert
        </button>
        <button onClick={() => save.mutate()} disabled={!dirty || save.isPending} className="rounded-md bg-accent px-3 py-1 text-white disabled:opacity-40">
          Save
        </button>
      </div>
      {message && (
        <div className={clsx("border-b border-border px-4 py-1.5 text-[0.75rem]", conflict ? "text-bad" : "text-muted")}>
          {message}
          {conflict && (
            <button onClick={() => void load()} className="ml-2 underline">
              Reload from disk
            </button>
          )}
        </div>
      )}
      {setFinal.isError && <div className="border-b border-border px-4 py-1 text-[0.75rem] text-bad">{(setFinal.error as Error).message}</div>}
      {isMaster && <HandEditsBar run={run} path={path} dirty={dirty} onAbsorb={onAbsorb} />}
      <div className="relative flex min-h-0 flex-1">
        <div className={`min-h-0 ${CENTER}`}>
          {path.endsWith(".md") ? (
            <Suspense fallback={<div className="p-5 text-muted">Loading editor…</div>}>
              <MarkdownEditor
                key={path}
                value={text}
                onChange={setText}
                onSave={() => { if (dirty) save.mutate(); }}
                onScroll={(top) => rememberScroll(run, `edit:${path}`, top)}
                initialScrollTop={place(run).scroll[`edit:${path}`]}
                marks={marks}
                focus={focus}
                onMarkClick={(id) => { setCommentsOpen(true); setActiveComment(id); post({ type: "focus-comment", run, id, to: "html" }); }}
              />
            </Suspense>
          ) : (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "s") {
                  e.preventDefault();
                  if (dirty) save.mutate();
                }
              }}
              spellCheck
              className="h-full w-full resize-none bg-bg p-5 font-mono text-[0.8125rem] leading-6 outline-none"
            />
          )}
        </div>
        {isMaster && commentsOpen && (
          <Panel size={PANELS.editComments} side="right" overlayBelow={760} onClose={() => setCommentsOpen(false)} className="bg-panel/50">
            <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-3">
              <div className="mb-2 text-[0.6875rem] font-medium uppercase tracking-wide text-faint">Comments</div>
              {comments.data && (
                <CommentList
                  run={run}
                  comments={comments.data.comments}
                  active={activeComment}
                  onSelect={(c) => showComment(c.id, true)}
                  empty="No comments. Add them in the HTML tab: select text, or click a figure or a table."
                />
              )}
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}

const READABLE_SKIP = ".cmt-note, .cmt-ref, a[href^='#ref-'], a.footnote-ref";
const BLOCKS = "p, li, td, th, h1, h2, h3, h4, h5, h6, figcaption, blockquote, dd, dt, caption";

/** Text as a reader sees it: no comment notes, no rendered citations or note markers. */
function readable(node: Node): string {
  const holder = document.createElement("div");
  holder.appendChild(node);
  holder.querySelectorAll(READABLE_SKIP).forEach((el) => el.remove());
  return (holder.textContent ?? "").replace(/\s+/g, " ").trim();
}

function elementOf(node: Node): Element | null {
  return node instanceof Element ? node : node.parentElement;
}

/** A passage selected in the rendered page, with what the server needs to find it in the Markdown. */
function selectionAnchor(range: Range): Anchor | null {
  const text = readable(range.cloneContents());
  if (text.length < 2) return null;
  const page = range.startContainer.ownerDocument;
  const startBlock = elementOf(range.startContainer)?.closest(BLOCKS);
  const endBlock = elementOf(range.endContainer)?.closest(BLOCKS);
  let prefix = "";
  let suffix = "";
  if (page && startBlock) {
    const before = page.createRange();
    before.setStart(startBlock, 0);
    before.setEnd(range.startContainer, range.startOffset);
    prefix = readable(before.cloneContents()).slice(-120);
  }
  if (page && endBlock) {
    const after = page.createRange();
    after.setStart(range.endContainer, range.endOffset);
    after.setEnd(endBlock, endBlock.childNodes.length);
    suffix = readable(after.cloneContents()).slice(0, 120);
  }
  const heading = elementOf(range.startContainer)?.closest("section")?.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6");
  return {
    label: text.length > 160 ? `${text.slice(0, 160)}…` : text,
    selection: { text, prefix, suffix, heading: heading ? readable(heading.cloneNode(true)) : "" },
  };
}

/** A click on a figure or a table, by the number its caption gives it. */
function elementAnchor(target: Element): Anchor | null {
  const figure = target.closest("figure");
  if (figure) {
    const m = /Figure (\d+)\./.exec(figure.querySelector("figcaption")?.textContent ?? "");
    return m ? { label: `Figure ${m[1]}`, element: { kind: "figure", number: Number(m[1]) } } : null;
  }
  const table = target.closest("table");
  if (table) {
    // The render gives every captioned table its id, whether the caption is above or below.
    // An untitled table's id (Tx…) exists only in the render, so it is found by its header row.
    const tagged = /^report-table-(T(?!x[0-9a-f]{6})\w+)$/.exec(table.id);
    if (tagged) {
      const caption = [table.previousElementSibling, table.nextElementSibling].map((el) => /^\s*Table (\d+)\./.exec(el?.textContent ?? "")).find(Boolean);
      return { label: caption ? `Table ${caption[1]}` : "This table", element: { kind: "table", id: tagged[1] } };
    }
    // A table with no caption is found by its header row.
    const header = table.querySelector("tr");
    const text = header ? readable(header.cloneNode(true)) : "";
    if (!text) return null;
    const heading = table.closest("section")?.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6");
    return {
      label: `Table with columns: ${text.length > 120 ? `${text.slice(0, 120)}…` : text}`,
      selection: { text, prefix: "", suffix: "", heading: heading ? readable(heading.cloneNode(true)) : "" },
    };
  }
  return null;
}

/** A click on a figure or a table while the palette is open: which one, and which part. */
function appearanceTarget(target: Element): Omit<AppearancePick, "seq"> | null {
  const caption = target.closest("p.table-caption");
  if (caption) return { kind: "table", id: caption.id.replace(/^report-caption-/, ""), part: "caption" };
  const table = target.closest("table");
  if (table) {
    const part = target.closest("th, thead") ? "header" : target.closest("td") ? "body" : "rules";
    const tagged = /^report-table-(T\w+)$/.exec(table.id);
    return { kind: "table", id: tagged?.[1], part };
  }
  const figure = target.closest("figure");
  if (figure) {
    const m = /Figure (\d+)\./.exec(figure.querySelector("figcaption")?.textContent ?? "");
    return { kind: "figure", number: m ? Number(m[1]) : undefined, part: target.closest("figcaption") ? "text" : "series" };
  }
  return null;
}

const PICKING_CSS = `
body.cmt-picking figure:hover, body.cmt-picking table:hover { outline: 2px dashed #E5B300; outline-offset: 3px; cursor: copy; }
body.ap-picking figure:hover, body.ap-picking table:hover, body.ap-picking p.table-caption:hover { outline: 2px dashed #2F6FEB; outline-offset: 3px; cursor: pointer; }
body.ap-picking th:hover, body.ap-picking td:hover { box-shadow: inset 0 0 0 2px rgba(47, 111, 235, 0.45); }
mark.cmt, mark.hl, sup.cmt-ref { cursor: pointer; }
`;

function HtmlPane({ run, doc, version }: { run: string; doc: string | undefined; version: number }) {
  const client = useQueryClient();
  const styles = useQuery({ queryKey: ["styles"], queryFn: () => api.get<{ name: string; description: string }[]>("/api/styles"), staleTime: Infinity });
  const [style, setStyleState] = useState(() => place(run).style ?? "meridian");
  const [appearanceOpen, setAppearanceOpenState] = useState(() => place(run).panel === "appearance");
  const appearanceOpenRef = useRef(appearanceOpen);
  const [appearancePick, setAppearancePick] = useState<AppearancePick | null>(null);
  const setAppearanceOpen = (next: boolean | ((open: boolean) => boolean)) =>
    setAppearanceOpenState((open) => {
      const value = typeof next === "function" ? next(open) : next;
      appearanceOpenRef.current = value;
      frame.current?.contentDocument?.body?.classList.toggle("ap-picking", value);
      if (value) remember(run, { panel: "appearance" });
      else if (place(run).panel === "appearance") remember(run, { panel: null });
      return value;
    });
  const [appearanceNotice, setAppearanceNotice] = useState("");
  const appearanceLoaded = useRef(false);
  const [cite, setCiteState] = useState(() => place(run).cite ?? true);
  const [zoom, setZoomState] = useState(() => place(run).zoom ?? 100);
  const setZoom = (value: number) => {
    setZoomState(value);
    remember(run, { zoom: value });
  };
  const frame = useRef<HTMLIFrameElement>(null);
  const area = useRef<HTMLDivElement>(null);
  const [commentsOpen, setCommentsOpenState] = useState(() => place(run).panel === "comments");
  const commentsOpenRef = useRef(commentsOpen);
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [bubble, setBubble] = useState<{ x: number; y: number; anchor: Anchor } | null>(null);
  const addHighlight = useHighlight(run, doc, (c) => {
    frame.current?.contentDocument?.getSelection()?.removeAllRanges();
    activeRef.current = c.id;
    setActiveComment(c.id);
  });
  const [activeComment, setActiveComment] = useState<string | null>(null);
  const activeRef = useRef<string | null>(null);
  // The unsaved text of an editor popped out into another window, rendered as it changes.
  const [liveText, setLiveText] = useState<string | null>(null);
  const [withComments, setWithCommentsState] = useState(() => prefs().export_comments ?? true);
  const setWithComments = (on: boolean) => {
    setWithCommentsState(on);
    setPref("export_comments", on);
  };
  const setCommentsOpen = (open: boolean) => {
    setCommentsOpenState(open);
    commentsOpenRef.current = open;
    frame.current?.contentDocument?.body?.classList.toggle("cmt-picking", open);
    if (open) remember(run, { panel: "comments" });
    else if (place(run).panel === "comments") remember(run, { panel: null });
    if (open) {
      setAppearanceOpen(false);
      setFiguresOpen(false);
    } else setAnchor(null);
  };
  const highlight = (id: string | null, scroll: boolean) => {
    const page = frame.current?.contentDocument;
    if (!page) return;
    page.querySelectorAll(".cmt-active").forEach((el) => el.classList.remove("cmt-active"));
    if (!id) return;
    const marks = Array.from(page.querySelectorAll<HTMLElement>("mark.cmt, mark.hl")).filter((m) => (m.dataset.c ?? "").split(" ").includes(id));
    marks.forEach((m) => m.classList.add("cmt-active"));
    if (scroll) marks[0]?.scrollIntoView({ block: "center", behavior: "smooth" });
  };
  const focusComment = (id: string, scroll: boolean) => {
    setActiveComment(id);
    activeRef.current = id;
    highlight(id, scroll);
  };
  const applyZoom = (value: number) => {
    const body = frame.current?.contentDocument?.body;
    if (body) body.style.zoom = `${value}%`;
  };
  const changeZoom = (value: number) => {
    const next = Math.max(50, Math.min(200, value));
    setZoom(next);
    applyZoom(next);
  };
  const setStyle = (v: string) => {
    setStyleState(v);
    remember(run, { style: v });
  };
  const setCite = (v: boolean) => {
    setCiteState(v);
    remember(run, { cite: v });
  };
  const appearance = useQuery({
    queryKey: ["appearance", run, doc, style, version],
    queryFn: () => api.get<AppearanceResponse>(`/api/runs/${encodeURIComponent(run)}/appearance?${q({ style, ...(doc ? { doc } : {}) })}`),
    retry: false,
  });
  useEffect(() => {
    if (appearanceLoaded.current || !appearance.data) return;
    appearanceLoaded.current = true;
    if (!place(run).style && appearance.data.saved_style) {
      setStyleState(appearance.data.saved_style);
      remember(run, { style: appearance.data.saved_style });
    }
  }, [appearance.data, run]);
  const focusRef = useRef(focusComment);
  focusRef.current = focusComment;
  const openRef = useRef(setCommentsOpen);
  openRef.current = setCommentsOpen;
  useEffect(
    () =>
      listen((m) => {
        if (m.run !== run) return;
        if (m.type === "draft" && m.path === doc) setLiveText(m.dirty ? m.text : null);
        else if ((m.type === "saved" || m.type === "popout-closed") && m.path === doc) setLiveText(null);
        else if (m.type === "focus-comment" && m.to === "html") {
          if (!commentsOpenRef.current) openRef.current(true);
          focusRef.current(m.id, true);
        }
      }),
    [run, doc],
  );
  // The rendered page is served from this app's own address, so its scroll can be read
  // and put back: the author returns to the paragraph they were reading. Selecting text in
  // it, or clicking a figure or a table while the comments are open, starts a comment.
  const onFrameLoad = (frame: HTMLIFrameElement) => {
    const page = frame.contentDocument;
    if (page?.body) {
      page.body.style.zoom = `${zoom}%`;
      page.body.classList.toggle("cmt-picking", commentsOpenRef.current);
      page.body.classList.toggle("ap-picking", appearanceOpenRef.current);
      const css = page.createElement("style");
      css.textContent = PICKING_CSS;
      page.head.appendChild(css);
      highlight(activeRef.current, false);
    }
    const win = frame.contentWindow;
    if (!win || !page) return;
    const top = place(run).scroll.html;
    if (top) win.scrollTo(0, top);
    let pending = false;
    win.addEventListener("scroll", () => {
      setBubble(null);
      if (pending) return;
      pending = true;
      win.requestAnimationFrame(() => {
        pending = false;
        rememberScroll(run, "html", win.scrollY);
      });
    });
    page.addEventListener("mousedown", () => setBubble(null));
    page.addEventListener("mouseup", (event) => {
      win.setTimeout(() => {
        const selection = page.getSelection();
        if (selection && !selection.isCollapsed && selection.rangeCount) {
          const range = selection.getRangeAt(0);
          const found = selectionAnchor(range);
          const box = area.current?.getBoundingClientRect();
          if (!found || !box) return;
          const rect = range.getBoundingClientRect();
          const at = frame.getBoundingClientRect();
          setBubble({
            x: Math.min(Math.max(at.left - box.left + rect.right - 80, 8), box.width - 200),
            y: Math.min(Math.max(at.top - box.top + rect.bottom + 8, 8), box.height - 40),
            anchor: found,
          });
          return;
        }
        const target = event.target as Element | null;
        const mark = target?.closest?.("mark.cmt, mark.hl, sup.cmt-ref") as HTMLElement | null;
        const id = mark?.dataset.c?.split(" ")[0];
        if (id) {
          if (!commentsOpenRef.current) openRef.current(true);
          focusRef.current(id, false);
          post({ type: "focus-comment", run, id, to: "editor" });
          return;
        }
        if (commentsOpenRef.current && target) {
          const found = elementAnchor(target);
          if (found) setAnchor(found);
        } else if (appearanceOpenRef.current && target) {
          const found = appearanceTarget(target);
          if (found) setAppearancePick({ ...found, seq: Date.now() });
        }
      }, 0);
    });
  };
  const [exported, setExported] = useState<Exported | null>(null);
  // Every export leaves a button per file in the toolbar until the author removes it.
  const [allLinks, setAllLinks] = useState(() => prefs().export_links ?? {});
  const links = allLinks[run] ?? [];
  const [linkError, setLinkError] = useState("");
  const setLinks = (next: string[]) => {
    const all = { ...allLinks, [run]: next };
    if (!next.length) delete all[run];
    setAllLinks(all);
    setPref("export_links", all);
  };
  const openLink = (path: string) => {
    setLinkError("");
    api.post("/api/exports/open", { path }).catch((e: Error) => setLinkError(`${path.split("/").pop()}: ${e.message}`));
  };
  const [figuresOpen, setFiguresOpenState] = useState(() => prefs().figures_open ?? true);
  const setFiguresOpen = (open: boolean) => {
    setFiguresOpenState(open);
    setPref("figures_open", open);
  };
  const [saved, setSaved] = useState("");
  const rendered = useQuery({
    queryKey: ["render", run, doc, style, cite, version],
    queryFn: () => api.post<Rendered>(`/api/runs/${encodeURIComponent(run)}/render`, { doc, style, cite }),
    // Picks up edits made outside the app (VS Code, an agent). The server answers from its
    // cache until the source changes, and the frame reloads only when `built` moves. A failed
    // render stops the polling, so a broken document is not rebuilt every few seconds.
    staleTime: 0,
    refetchInterval: (query) => (query.state.status === "error" ? false : 3_000),
    retry: false,
  });
  const live = useQuery({
    queryKey: ["render-live", run, doc, style, cite, liveText],
    queryFn: () => api.post<Rendered>(`/api/runs/${encodeURIComponent(run)}/render-live`, { doc, style, cite, content: liveText }),
    enabled: liveText !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });
  const saveAppearance = useMutation({
    mutationFn: ({ values, rememberDefault }: { values: AppearanceValues; rememberDefault: boolean }) =>
      api.put<AppearanceResponse>(`/api/runs/${encodeURIComponent(run)}/appearance`, { style, values, remember_default: rememberDefault, doc }),
    onSuccess: () => {
      setAppearanceNotice("Appearance saved for this report.");
      setExported(null);
      void client.invalidateQueries({ queryKey: ["appearance", run] });
      void rendered.refetch();
    },
  });
  // The author's caption for an uncaptioned table, written into the document.
  const addCaption = useMutation({
    mutationFn: ({ table, title }: { table: string; title: string }) =>
      api.post<{ id: string }>(`/api/runs/${encodeURIComponent(run)}/table-caption`, { doc, table, title }),
    onSuccess: () => {
      setAppearanceNotice("Caption added to the document.");
      void client.invalidateQueries({ queryKey: ["appearance", run] });
      void client.invalidateQueries({ queryKey: ["run-file", run] });
      void rendered.refetch();
    },
  });
  const resetAppearance = useMutation({
    mutationFn: () => api.del(`/api/runs/${encodeURIComponent(run)}/appearance`),
    onSuccess: () => {
      setAppearanceNotice("Preset restored for this report.");
      setExported(null);
      void client.invalidateQueries({ queryKey: ["appearance", run] });
      void rendered.refetch();
    },
  });
  const exportRun = useMutation({
    mutationFn: (formats: string[]) => api.post<Exported>(`/api/runs/${encodeURIComponent(run)}/export`, { doc, style, cite, formats, comments: withComments }),
    onSuccess: (r) => {
      setExported(r);
      setLinks([...r.files, ...links.filter((f) => !r.files.includes(f))]);
    },
  });
  const saveFigures = useMutation({
    mutationFn: () => api.post<{ saved: string[] }>(`/api/runs/${encodeURIComponent(run)}/figures/save`, { doc, style, cite }),
    onSuccess: (r) => setSaved(`${r.saved.length} file(s) saved to export/${style}/figures/.`),
  });
  const showingLive = liveText !== null && Boolean(live.data);
  const data = showingLive ? live.data : rendered.data;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2 text-[0.7812rem]">
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
        <button onClick={() => { if (!appearanceOpen) void appearance.refetch(); setAppearanceOpen((open) => !open); setFiguresOpen(false); setCommentsOpen(false); }} className={clsx("ml-2 flex items-center gap-1 rounded-md border border-border px-2.5 py-1 hover:border-accent", appearanceOpen && "border-accent text-accent")}>
          <Palette size="0.8125rem" /> Palette and layout
        </button>
        {doc && (
          <button onClick={() => setCommentsOpen(!commentsOpen)} title="Comment on the document: select text, or click a figure or a table" className={clsx("flex items-center gap-1 rounded-md border border-border px-2.5 py-1 hover:border-accent", commentsOpen && "border-accent text-accent")}>
            <MessageSquare size="0.8125rem" /> Comments
          </button>
        )}
        <button onClick={() => void rendered.refetch()} title="Render again" className="rounded-md p-1 text-faint hover:text-fg">
          <RefreshCw size="0.8125rem" className={clsx((rendered.isFetching || live.isFetching) && "animate-spin")} />
        </button>
        {links.map((f) => (
          <span key={f} className="flex items-center rounded-md border border-border hover:border-accent">
            <button onClick={() => openLink(f)} title={`Open ${f}`} className="flex items-center gap-1 py-1 pl-2 pr-1">
              <FileDown size="0.75rem" className="text-faint" />
              {f.split("/").pop()}
              <span className="text-faint">· {f.split("/").slice(-2, -1)[0]}</span>
            </button>
            <button onClick={() => setLinks(links.filter((x) => x !== f))} title="Remove this button (the file stays)" aria-label={`Remove ${f}`} className="py-1 pl-0.5 pr-1.5 text-faint hover:text-fg">
              <X size="0.6875rem" />
            </button>
          </span>
        ))}
        <div className="flex-1" />
        <div className="flex items-center rounded-md border border-border" aria-label="Report zoom">
          <button onClick={() => changeZoom(zoom - 10)} disabled={zoom <= 50} title="Zoom report out" aria-label="Zoom report out" className="p-1.5 disabled:opacity-40"><Minus size="0.8125rem" /></button>
          <span className="min-w-10 text-center tabular-nums">{zoom}%</span>
          <button onClick={() => changeZoom(zoom + 10)} disabled={zoom >= 200} title="Zoom report in" aria-label="Zoom report in" className="p-1.5 disabled:opacity-40"><Plus size="0.8125rem" /></button>
          <button onClick={() => changeZoom(100)} disabled={zoom === 100} title="Reset report zoom" aria-label="Reset report zoom" className="border-l border-border p-1.5 disabled:opacity-40"><RotateCcw size="0.75rem" /></button>
        </div>
        {data && data.figures.length > 0 && !figuresOpen && (
          <button onClick={() => { setAppearanceOpen(false); setCommentsOpen(false); setFiguresOpen(true); }} title="Show the figures panel" className="rounded-md p-1 text-faint hover:text-fg">
            <PanelRight size="0.875rem" />
          </button>
        )}
        <label className="flex items-center gap-1 text-faint" title="Exports carry the open comments: Word comments in Word, footnotes in the PDF, highlights in the HTML">
          <input type="checkbox" checked={withComments} onChange={(e) => setWithComments(e.target.checked)} /> Comments in exports
        </label>
        <button onClick={() => exportRun.mutate(["html"])} disabled={exportRun.isPending} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 hover:border-accent disabled:opacity-40">
          <FileDown size="0.8125rem" /> Export HTML
        </button>
        <button onClick={() => exportRun.mutate(["docx"])} disabled={exportRun.isPending} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 hover:border-accent disabled:opacity-40">
          <FileDown size="0.8125rem" /> Export Word
        </button>
        <button onClick={() => exportRun.mutate(["html", "pdf"])} disabled={exportRun.isPending} className="flex items-center gap-1 rounded-md bg-accent px-2.5 py-1 text-white disabled:opacity-40">
          <FileDown size="0.8125rem" /> {exportRun.isPending ? "Exporting…" : "Export PDF"}
        </button>
      </div>
      {showingLive && (
        <div className="flex items-center gap-2 border-b border-border bg-[#FFF8DB] px-4 py-1 text-[0.75rem] text-[#5C4600] dark:bg-[#3A3214] dark:text-[#F5E3A3]">
          Showing the unsaved text from the editor window{live.isFetching ? " · updating…" : ""}. Save there to keep it.
        </div>
      )}
      {live.isError && liveText !== null && <div className="border-b border-border px-4 py-1 text-[0.75rem] text-bad">The unsaved text could not be rendered: {(live.error as Error).message}</div>}
      {appearanceNotice && <div className="border-b border-border px-4 py-1 text-[0.75rem] text-good">{appearanceNotice}</div>}
      {linkError && (
        <div className="flex items-center gap-2 border-b border-border px-4 py-1 text-[0.75rem] text-bad">
          <span className="flex-1">Could not open {linkError}. Export again, or remove the button.</span>
          <button onClick={() => setLinkError("")} title="Clear" aria-label="Clear" className="text-faint hover:text-fg"><X size="0.75rem" /></button>
        </div>
      )}
      {(exported || exportRun.isError) && (
        <div className="relative border-b border-border px-4 py-2 pr-9 text-[0.75rem]">
          <button onClick={() => { setExported(null); exportRun.reset(); }} title="Clear this message" aria-label="Clear this message" className="absolute right-3 top-2 rounded p-0.5 text-faint hover:text-fg">
            <X size="0.8125rem" />
          </button>
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
                  {exported.comments > 0 && <span className="text-muted">· {exported.comments} comment{exported.comments === 1 ? "" : "s"} included</span>}
                </div>
                <pre className={clsx("mt-1 whitespace-pre-wrap text-[0.7188rem]", exported.check.startsWith("Export check passed") ? "text-good" : "text-warn")}>{exported.check}</pre>
              </>
            )
          )}
        </div>
      )}
      <div ref={area} className="relative flex min-h-0 flex-1">
        <div className={`bg-white ${CENTER}`}>
          {rendered.isFetching && !data && <div className="p-6 text-[0.8125rem] text-faint">Rendering the figures and the HTML…</div>}
          {rendered.isError && !showingLive && <pre className="whitespace-pre-wrap p-6 text-[0.7812rem] text-bad">{(rendered.error as Error).message}</pre>}
          {data && <iframe ref={frame} key={`${data.html}@${data.built}`} title="HTML" src={renderedUrl(run, style, cite, data.html, false, data.built)} onLoad={(e) => onFrameLoad(e.currentTarget)} className="h-full w-full border-0" />}
        </div>
        {bubble && (
          <div style={{ left: bubble.x, top: bubble.y }} className="absolute z-40 flex items-center gap-2 rounded-md border border-border bg-surface py-1 pl-2 pr-1 shadow-lg">
            <ColourDots
              current={prefs().highlight_color ?? "yellow"}
              onPick={(color) => { addHighlight.mutate({ anchor: bubble.anchor, color }); setBubble(null); }}
            />
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => { setAnchor(bubble.anchor); setBubble(null); if (!commentsOpen) setCommentsOpen(true); }}
              className="flex items-center gap-1 rounded bg-accent px-2 py-0.5 text-[0.75rem] text-white"
            >
              <MessageSquarePlus size="0.8125rem" /> Comment
            </button>
          </div>
        )}
        {addHighlight.isError && (
          <div className="absolute left-3 top-3 z-40 max-w-md rounded-md border border-bad bg-surface px-3 py-1.5 text-[0.75rem] text-bad shadow">
            {(addHighlight.error as Error).message}
            <button onClick={() => addHighlight.reset()} className="ml-2 underline">Close</button>
          </div>
        )}
        {commentsOpen && doc && (
          <Panel size={PANELS.comments} side="right" overlayBelow={760} onClose={() => setCommentsOpen(false)} className="bg-panel">
            <CommentsPanel
              run={run}
              doc={doc}
              anchor={anchor}
              active={activeComment}
              onAnchorDone={(id) => { setAnchor(null); if (id) { activeRef.current = id; setActiveComment(id); } }}
              onSelect={(c) => { focusComment(c.id, true); post({ type: "focus-comment", run, id: c.id, to: "editor" }); }}
              onClose={() => setCommentsOpen(false)}
            />
          </Panel>
        )}
        {appearanceOpen && (
          <Panel size={PANELS.appearance} side="right" overlayBelow={740} onClose={() => setAppearanceOpen(false)} className="bg-panel">
            <AppearancePanel
              key={`${style}/${doc ?? ""}`}
              data={appearance.data}
              pick={appearancePick}
              doc={doc}
              onAddCaption={doc ? (table, title) => addCaption.mutateAsync({ table, title }).then((r) => r.id) : undefined}
              onApply={(values, rememberDefault) => saveAppearance.mutate({ values, rememberDefault })}
              onReset={() => resetAppearance.mutate()}
              onRetry={() => void appearance.refetch()}
              busy={saveAppearance.isPending || resetAppearance.isPending}
              loading={appearance.isPending || appearance.isFetching}
              error={(saveAppearance.error as Error | null)?.message || (resetAppearance.error as Error | null)?.message || (appearance.error as Error | null)?.message}
            />
          </Panel>
        )}
        {data && data.figures.length > 0 && figuresOpen && (
          <Panel size={PANELS.figures} side="right" overlayBelow={900} onClose={() => setFiguresOpen(false)} className="bg-panel/50">
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-3 text-[0.75rem]">
            <div className="mb-2 flex items-center">
              <span className="text-[0.6875rem] font-medium uppercase tracking-wide text-faint">Figures</span>
              <button onClick={() => saveFigures.mutate()} className="ml-auto text-[0.7188rem] text-accent underline" title={`Copy every figure to export/${style}/figures/`}>
                Save all
              </button>
              <button onClick={() => setFiguresOpen(false)} title="Collapse the figures panel" className="ml-1.5 rounded-md p-0.5 text-faint hover:bg-panel hover:text-fg">
                <PanelRightClose size="0.875rem" />
              </button>
            </div>
            {saved && <div className="mb-2 text-[0.7188rem] text-good">{saved}</div>}
            {data.figures.map((f) => (
              <div key={f.name} className="mb-3">
                {f.files.png && <img src={renderedUrl(run, style, cite, f.files.png, false, data.built)} alt={f.name} className="w-full rounded border border-border bg-white" />}
                <div className="mt-1 flex items-center gap-2">
                  <span className="font-medium">{f.name}</span>
                  {Object.entries(f.files).map(([kind, path]) => (
                    <a key={kind} href={renderedUrl(run, style, cite, path, true)} className="flex items-center gap-0.5 text-accent">
                      <Download size="0.6875rem" /> {kind.toUpperCase()}
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
          </Panel>
        )}
      </div>
    </div>
  );
}

/** The editor alone, in a window of its own (opened by Pop out). */
export function PopoutEdit({ run, path }: { run: string; path: string }) {
  const [ready, setReady] = useState(false);
  const detail = useQuery({ queryKey: ["run", run], queryFn: () => api.get<RunDetail>(`/api/runs/${encodeURIComponent(run)}`) });
  useEffect(() => {
    document.title = `${path} · ${run}`;
    let done = false;
    const finish = () => {
      if (!done) {
        done = true;
        setReady(true);
      }
    };
    // The main window hands over any unsaved text, and gets it back when this window closes.
    const stop = listen((m) => {
      if (m.type === "handoff" && m.run === run && m.path === path) {
        // The main window's text is the current one, even when it has none.
        if (!done) rememberDraft(run, path, m.draft);
        finish();
      } else if (m.type === "popout-ping" && m.run === run) post({ type: "popout-here", run, path });
      else if (m.type === "return" && m.run === run && m.path === path) window.close();
    });
    post({ type: "popout-ready", run, path });
    const timer = setTimeout(() => {
      if (!done) rememberDraft(run, path, null);
      finish();
    }, 800);
    const leave = () => post({ type: "popout-closed", run, path, draft: place(run).drafts[path] ?? null });
    window.addEventListener("pagehide", leave);
    return () => {
      stop();
      clearTimeout(timer);
      window.removeEventListener("pagehide", leave);
    };
  }, [run, path]);
  if (detail.isError) return <div className="p-6 text-bad">{(detail.error as Error).message}</div>;
  if (!ready || !detail.data) return <div className="p-6 text-faint">Opening the editor…</div>;
  return (
    <div className="h-full bg-bg">
      <EditPane run={run} path={path} isMaster={detail.data.meta.masters.includes(path)} onSaved={() => undefined} popout />
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
  // Which master the Document, HTML and Edit tabs show, when the run has more than one
  // (a revision run's audit and its revised documents).
  const [doc, setDocState] = useState<string | undefined>(kept.doc);
  const setDoc = (d: string) => {
    setDocState(d);
    remember(name, { doc: d });
    setEditPath(undefined);
  };
  const reader = useRef<HTMLDivElement>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const [aiImport, setAiImport] = useState(false);
  const [fileMessage, setFileMessage] = useState("");
  const readerKey = tab === "file" ? `file:${selected ?? ""}` : "document";
  const [version, setVersion] = useState(0);
  // Documents being edited in a window of their own (Pop out), by path.
  const [popped, setPopped] = useState<string[]>([]);
  useEffect(() => {
    const stop = listen((m) => {
      if (m.run !== name) return;
      if (m.type === "popout-ready") {
        post({ type: "handoff", run: name, path: m.path, draft: place(name).drafts[m.path] ?? null });
        rememberDraft(name, m.path, null);
        setPopped((p) => (p.includes(m.path) ? p : [...p, m.path]));
      } else if (m.type === "popout-here") {
        setPopped((p) => (p.includes(m.path) ? p : [...p, m.path]));
      } else if (m.type === "popout-closed") {
        if (m.draft) rememberDraft(name, m.path, m.draft);
        setPopped((p) => p.filter((x) => x !== m.path));
      } else if (m.type === "saved") {
        setVersion((v) => v + 1);
        void client.invalidateQueries({ queryKey: ["run", name] });
        void client.invalidateQueries({ queryKey: ["run-file", name] });
      }
    });
    post({ type: "popout-ping", run: name });
    return stop;
  }, [name, client]);
  const [panelOpen, setPanelOpenState] = useState(() => prefs().run_panel_open);
  const setPanelOpen = (open: boolean) => {
    setPanelOpenState(open);
    setPref("run_panel_open", open);
  };
  // The project's conversation, opened (or created) when the Chat tab is first shown.
  const [chat, setChat] = useState<string | null>(null);
  const [critiqueReview, setCritiqueReview] = useState<{ path: string; questions: CritiqueQuestion[] } | null>(null);
  // Documents this project improves (revision runs), and the dialog where the author decides on their changes.
  // Both are read again only when a file in the run changed, rather than on a timer of their own.
  const changed = useMemo(() => Math.max(0, ...(run.data?.files ?? []).map((f) => f.mtime)), [run.data]);
  const subjects = useQuery({
    queryKey: ["subjects", name, changed],
    queryFn: () => api.get<{ subjects: Subject[] }>(`/api/runs/${encodeURIComponent(name)}/subjects`),
    placeholderData: keepPreviousData,
  });
  // Workbooks and decks the project delivered that have no editable copy yet.
  const officeOutputs = useQuery({
    queryKey: ["office-outputs", name, changed],
    queryFn: () => api.get<{ outputs: OfficeOutput[] }>(`/api/runs/${encodeURIComponent(name)}/office/outputs`),
    placeholderData: keepPreviousData,
  });
  // When any task ends, read the run again at once: a document it wrote or changed is in the
  // menu and the HTML tab without waiting for the next poll or reopening the project.
  // After it, the app makes the edited documents' exports again; show those too when ready.
  useEffect(() => subscribe((m) => {
    if (!((m.type === "state" && !m.running) || (m.type === "exports" && m.run === name))) return;
    void client.invalidateQueries({ queryKey: ["run", name] });
    void client.invalidateQueries({ queryKey: ["run-file", name] });
  }), [name, client]);
  const [officeFocus, setOfficeFocus] = useState<OfficeFocus | undefined>();
  const [changesOpen, setChangesOpen] = useState(false);
  const openOffice = useMutation({
    mutationFn: ({ path }: { path: string; then: Tab }) => api.post<{ master: string }>(`/api/runs/${encodeURIComponent(name)}/documents/open`, { path }),
    onSuccess: async (result, { then }) => {
      await Promise.all(["subjects", "run", "office-outputs"].map((key) => client.invalidateQueries({ queryKey: [key, name] })));
      setDoc(result.master); setEditPath(undefined); setTab(then);
    },
  });
  const refreshExports = useMutation({
    mutationFn: (doc: string) => api.post<{ results: { doc: string; files: string[]; problem: string | null }[] }>(`/api/runs/${encodeURIComponent(name)}/exports/refresh`, { doc }),
    onSettled: () => void client.invalidateQueries({ queryKey: ["run", name] }),
  });
  const refreshProblems = refreshExports.isError ? [(refreshExports.error as Error).message] : (refreshExports.data?.results ?? []).flatMap((r) => (r.problem ? [r.problem] : []));
  const planned = (subjects.data?.subjects ?? []).filter((s) => s.role === "subject" && (s.master || Object.keys(s.counts).length > 0));
  const revisedOnly = planned.length > 0 && planned.every((s) => s.master);
  const undecided = planned.reduce((n, s) => n + (s.counts.proposed ?? 0) + (s.counts.stale ?? 0), 0);
  const openChat = useMutation({
    mutationFn: (fresh: boolean) => api.post<SessionDetail>(`/api/runs/${encodeURIComponent(name)}/chat`, { new: fresh }),
    onSuccess: (s) => {
      setChat(s.id);
      void client.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
  useEffect(() => {
    setChat(null);
    setCritiqueReview(null);
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
      forget(name);
      void client.invalidateQueries({ queryKey: ["runs"] });
      void client.invalidateQueries({ queryKey: ["exports"] });
      void client.invalidateQueries({ queryKey: ["sessions"] });
      setView({ kind: "home" });
    },
  });
  const importFiles = useMutation({
    mutationFn: async (files: File[]) => {
      const saved: string[] = [];
      for (const file of files) {
        try {
          if (file.size > 25_000_000) throw new Error(`${file.name} is larger than 25 MB.`);
          const data = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
            reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
            reader.readAsDataURL(file);
          });
          const path = `${aiImport ? "ai_reports/" : ""}${file.name}`;
          const result = await api.post<{ path: string }>(`/api/runs/${encodeURIComponent(name)}/external-data`, { path, data });
          saved.push(result.path);
        } catch (e) {
          throw new Error(`${saved.length} file${saved.length === 1 ? "" : "s"} imported. ${String((e as Error).message)}`);
        }
      }
      return saved;
    },
    onSuccess: (saved) => {
      setFileMessage(`Imported ${saved.length} file${saved.length === 1 ? "" : "s"} into external_data/. Agents will find them on the next source scan.`);
      void client.invalidateQueries({ queryKey: ["run", name] });
    },
    onError: (e) => {
      setFileMessage((e as Error).message);
      void client.invalidateQueries({ queryKey: ["run", name] });
    },
  });
  const removeFile = useMutation({
    mutationFn: (path: string) => api.del<{ trash: string }>(`/api/runs/${encodeURIComponent(name)}/external-data?${q({ path: path.slice("external_data/".length) })}`),
    onSuccess: (result) => {
      setFileMessage(`Moved to ${result.trash}.`);
      setSelected(undefined);
      if (tab === "file") setTab("document");
      void client.invalidateQueries({ queryKey: ["run", name] });
    },
    onError: (e) => setFileMessage((e as Error).message),
  });
  const loadCritiqueQuestions = useMutation({
    mutationFn: (path: string) => api.get<{ questions: CritiqueQuestion[] }>(`/api/runs/${encodeURIComponent(name)}/critique-questions?${q({ path })}`),
    onSuccess: (result, path) => setCritiqueReview({ path, questions: result.questions }),
  });
  const applyCritique = useMutation({
    mutationFn: (body: CritiqueAnswers & { path: string }) => api.post<{ session: string }>(`/api/runs/${encodeURIComponent(name)}/apply-critique`, body),
    onSuccess: (result) => {
      setCritiqueReview(null);
      setChat(result.session);
      setTab("chat");
      void client.invalidateQueries({ queryKey: ["sessions"] });
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
  const present = new Set(data.files.map((f) => f.path));
  const officeSubjects = (subjects.data?.subjects ?? []).filter((s) => s.role === "subject" && ["xlsx", "pptx"].includes(s.format));
  const outputs = officeOutputs.data?.outputs ?? [];
  const masterDocs = [...new Set([...data.meta.masters.filter((m) => present.has(m)), ...officeSubjects.map((s) => s.master ?? `${s.slug}.md`), ...outputs.map((o) => o.path)])];
  const otherDocs = (data.readable ?? []).filter((m) => !masterDocs.includes(m));
  const docs = [...masterDocs, ...otherDocs];
  const shown = doc && docs.includes(doc) ? doc : primary ?? docs[0];
  const officeSubject = officeSubjects.find((s) => (s.master ?? `${s.slug}.md`) === shown);
  const officeOutput = outputs.find((o) => o.path === shown);
  const office = Boolean(officeSubject || officeOutput);
  const docLabel = (m: string) => {
    const output = outputs.find((o) => o.path === m);
    if (output) return output.label;
    const subject = officeSubjects.find((s) => (s.master ?? `${s.slug}.md`) === m);
    if (subject) return `${subject.office_file ?? subject.path}${subject.master ? " (editable)" : " (open editor)"}`;
    const entry = data.meta.documents?.find((d) => d.master === m);
    const source = entry && subjects.data?.subjects.find((s) => s.slug === entry.slug)?.path;
    if (source) return `${source.replace(/\.[^.]+$/, "")} (revised)`;
    return data.meta.documents?.length && m === "report.md" ? "Audit (report.md)" : m;
  };
  // Exports and delivered files older than their document. The app makes them again after a
  // task; these are the ones still waiting, or that it could not make (`blocked`).
  const staleCopies = (m: string) => (data.stale ?? []).filter((s) => s.doc === m);
  const shownStale = shown ? staleCopies(shown) : [];
  const shownBlocked = shownStale.filter((s) => s.blocked);
  const editing = editPath ?? shown;
  const critiqueFailed = Boolean(selected && data.critique_failed_at && data.critique_failed_at >= (data.files.find((item) => item.path === selected)?.mtime ?? 0));
  const onSaved = () => {
    setVersion((v) => v + 1);
    void client.invalidateQueries({ queryKey: ["office-outputs", name] });
    void client.invalidateQueries({ queryKey: ["run", name] });
    void client.invalidateQueries({ queryKey: ["run-file", name] });
  };
  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: "document", label: "Document", show: true },
    { id: "chat", label: "Chat", show: true },
    { id: "html", label: "HTML", show: Boolean(shown) },
    { id: "edit", label: "Edit", show: Boolean(editing) },
    { id: "file", label: selected ?? "File", show: Boolean(selected) },
  ];

  return (
    <div className="relative flex h-full">
      <div className={`flex flex-col ${CENTER}`}>
        <div className="flex items-center gap-2 border-b border-border px-5 py-2">
          <div className="min-w-0 flex-1">
            <div className="text-[0.7188rem] text-faint">
              Research · {data.evidence_rows} evidence rows · {data.notes} notes
            </div>
            <div className="truncate text-[0.9375rem] font-medium">{name}</div>
          </div>
          {planned.length > 0 && (
            <button onClick={() => setChangesOpen(true)} title="Review the proposed changes to this project's documents" className={clsx("flex items-center gap-1 rounded-md border px-2.5 py-1 text-[0.75rem]", undecided ? "border-accent text-accent hover:bg-panel" : "border-border hover:border-accent")}>
              <ListChecks size="0.8125rem" /> {revisedOnly ? "Revised document" : "Changes"}{undecided ? ` · ${undecided} to decide` : ""}
            </button>
          )}
          <button onClick={() => void api.post(`/api/runs/${encodeURIComponent(name)}/vscode`)} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent">
            <Code2 size="0.8125rem" /> VS Code
          </button>
          <button onClick={() => void api.post(`/api/runs/${encodeURIComponent(name)}/reveal`)} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent">
            <FolderSearch size="0.8125rem" /> Finder
          </button>
          {tab !== "chat" && (
            <button
              onClick={() => setPanelOpen(!panelOpen)}
              title={panelOpen ? "Collapse the stages and files panel" : "Show the stages and files panel"}
              className={clsx("rounded-md p-1.5 hover:bg-panel hover:text-fg", panelOpen ? "text-accent" : "text-faint")}
            >
              <PanelRight size="1rem" />
            </button>
          )}
          <button
            onClick={() => {
              if (window.confirm(`Remove ${name}? Its folder moves to the Trash, where you can still restore it. Its conversations and cached renders are deleted.`)) remove.mutate();
            }}
            className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[0.75rem] text-bad hover:border-bad"
          >
            <Trash2 size="0.8125rem" /> Remove
          </button>
        </div>
        {remove.isError && <div className="border-b border-border px-5 py-1.5 text-[0.75rem] text-bad">{(remove.error as Error).message}</div>}
        {refreshProblems.length > 0 && <div className="whitespace-pre-wrap border-b border-border px-5 py-1.5 text-[0.75rem] text-bad">{refreshProblems.join("\n")}</div>}
        <div className="flex gap-1 border-b border-border px-4 py-1.5">
          {tabs
            .filter((t) => t.show)
            .map((t) =>
              t.id === "file" ? (
                <span key={t.id} className={clsx("flex max-w-[17.5rem] items-center rounded-md text-[0.7812rem]", tab === t.id ? "bg-panel font-medium text-fg" : "text-muted hover:text-fg")}>
                  <button onClick={() => setTab(t.id)} className="truncate py-1 pl-3 pr-1">
                    {t.label}
                  </button>
                  <button
                    onClick={() => {
                      setSelected(undefined);
                      setTab("document");
                    }}
                    title="Close this file"
                    aria-label="Close this file"
                    className="mr-1 rounded p-0.5 text-faint hover:bg-surface hover:text-fg"
                  >
                    <X size="0.75rem" />
                  </button>
                </span>
              ) : (
                <button key={t.id} onClick={() => setTab(t.id)} className={clsx("max-w-[16rem] truncate rounded-md px-3 py-1 text-[0.7812rem]", tab === t.id ? "bg-panel font-medium text-fg" : "text-muted hover:text-fg")}>
                  {t.label}
                </button>
              ),
            )}
          {shownStale.length > 0 && tab !== "file" && tab !== "chat" && (
            <button
              disabled={refreshExports.isPending || shownBlocked.length === shownStale.length}
              onClick={() => refreshExports.mutate(shown!)}
              title={[
                ...shownStale.filter((s) => s.kind === "merge").map((s) => `${s.files[0]} was made outside the editor. Click to merge it into this document, then export.`),
                shownStale.some((s) => s.kind !== "merge") ? `Older than the document:\n${shownStale.filter((s) => s.kind !== "merge").flatMap((s) => s.files).join("\n")}` : "",
                ...shownBlocked.map((s) => s.blocked!),
                shownBlocked.length < shownStale.length ? "Click to make them again, as they were last made." : "",
              ].filter(Boolean).join("\n\n")}
              className={clsx("rounded-md border border-warn px-1.5 py-0.5 text-[0.6875rem] text-warn enabled:hover:bg-panel disabled:cursor-help", docs.length <= 1 && "ml-auto")}
            >
              {refreshExports.isPending ? "Updating exports…" : shownBlocked.length === shownStale.length ? "Export out of date: needs a decision" : "Update exports"}
            </button>
          )}
          {docs.length > 1 && tab !== "file" && tab !== "chat" && (
            <label className={clsx("flex items-center gap-1.5 text-[0.75rem] text-muted", shownStale.length === 0 && "ml-auto")}>
              Showing
              <select value={shown} onChange={(e) => { setDoc(e.target.value); setEditPath(undefined); }} title="The document the Document, HTML and Edit tabs show" className="max-w-[18rem] truncate rounded-md border border-border bg-bg px-1.5 py-0.5 text-fg outline-none focus:border-accent">
                {otherDocs.length > 0 ? (
                  <>
                    <optgroup label="Documents">{masterDocs.map((m) => <option key={m} value={m}>{docLabel(m)}{staleCopies(m).length ? " · export out of date" : ""}</option>)}</optgroup>
                    <optgroup label="Other documents">{otherDocs.map((m) => <option key={m} value={m}>{m}</option>)}</optgroup>
                  </>
                ) : (
                  masterDocs.map((m) => <option key={m} value={m}>{docLabel(m)}{staleCopies(m).length ? " · export out of date" : ""}</option>)
                )}
              </select>
            </label>
          )}
          {tab === "file" && selected?.endsWith(".md") && !selected.startsWith("export/") && (
            <button
              onClick={() => {
                setEditPath(selected);
                setTab("edit");
              }}
              className="ml-2 flex items-center gap-1 text-[0.75rem] text-accent"
            >
              <Pencil size="0.75rem" /> Edit this file
            </button>
          )}
          {tab === "file" && selected?.startsWith("external_data/") && /\.(xlsx|pptx)$/i.test(selected) && <button disabled={openOffice.isPending} onClick={() => openOffice.mutate({ path: selected, then: "html" })} className="ml-auto rounded-md border border-accent px-2.5 py-1 text-[0.75rem] text-accent disabled:opacity-40">{openOffice.isPending ? "Opening…" : "Open editable document"}</button>}
          {tab === "file" && selected && /^critique[\w-]*\.md$/.test(selected) && (
            <button onClick={() => { applyCritique.reset(); loadCritiqueQuestions.mutate(selected); }} disabled={loadCritiqueQuestions.isPending || critiqueFailed} title={critiqueFailed ? "Run /critique again with an independent critic first" : undefined} className="ml-auto rounded-md border border-accent px-2.5 py-1 text-[0.75rem] text-accent hover:bg-panel disabled:opacity-40">
              {critiqueFailed ? "Independent review required" : loadCritiqueQuestions.isPending ? "Preparing questions…" : "Apply feedback to article"}
            </button>
          )}
        </div>
        {tab === "file" && selected && /^critique[\w-]*\.md$/.test(selected) && critiqueFailed && (
          <div className="border-b border-border px-4 py-1.5 text-[0.75rem] text-warn">This critique needs an independent review. Run /critique again before applying its findings.</div>
        )}
        {applyCritique.isError && <div className="border-b border-border px-4 py-1.5 text-[0.75rem] text-bad">{(applyCritique.error as Error).message}</div>}
        {openOffice.isError && <div role="alert" className="border-b border-border px-4 py-1.5 text-[0.75rem] text-bad">{openOffice.error.message}</div>}
        {loadCritiqueQuestions.isError && <div className="border-b border-border px-4 py-1.5 text-[0.75rem] text-bad">{(loadCritiqueQuestions.error as Error).message}</div>}
        <div className="min-h-0 flex-1">
          {tab === "chat" &&
            (chat ? (
              <SessionView key={chat} id={chat} embedded onNew={() => openChat.mutate(true)} />
            ) : (
              <div className="p-6 text-[0.8125rem] text-faint">{openChat.isError ? (openChat.error as Error).message : "Opening the project's conversation…"}</div>
            ))}
          {office && (tab === "html" || tab === "document") && (
            <OfficeHtml
              key={shown}
              run={name}
              path={officeSubject ? (officeSubject.master ?? `external_data/${officeSubject.path}`) : officeOutput!.path}
              name={officeSubject ? (officeSubject.office_file ?? officeSubject.path) : officeOutput!.label}
              version={version}
              download={officeOutput?.path ?? officeSubject?.deliverable?.file ?? undefined}
              editLabel={officeSubject?.master ? "Edit" : "Start editing"}
              onEdit={() => { setOfficeFocus(undefined); setEditPath(undefined); setTab("edit"); }}
              onPick={(focus) => { setOfficeFocus(focus); setEditPath(undefined); setTab("edit"); }}
              design={officeSubject?.master && officeSubject.format === "pptx" ? { slug: officeSubject.slug, master: officeSubject.master } : undefined}
            />
          )}
          {officeSubject && tab === "edit" && editing === shown && <OfficePane key={officeSubject.slug} run={name} subject={officeSubject} edit focus={officeFocus} onReady={onSaved} />}
          {officeOutput?.editable_master && tab === "edit" && editing === shown && (
            <div className="space-y-3 p-6 text-[0.8125rem]">
              <p>{officeOutput.label} was made outside the editor. The editable document for this deck is built from an earlier file and does not include this version, so editing it would not change this file.</p>
              <button onClick={() => { setDoc(officeOutput.editable_master!); setEditPath(undefined); }} className="rounded-md border border-accent px-2.5 py-1 text-accent">Show the editable document</button>
            </div>
          )}
          {officeOutput && !officeOutput.editable_master && tab === "edit" && editing === shown && (
            <div className="space-y-3 p-6 text-[0.8125rem]">
              <p>{officeOutput.label} was delivered by this project. Editing starts a working copy here; the delivered file stays as it is, and exporting writes the next version beside it.</p>
              <button disabled={openOffice.isPending} onClick={() => openOffice.mutate({ path: officeOutput.path, then: "edit" })} className="rounded-md border border-accent px-2.5 py-1 text-accent disabled:opacity-40">{openOffice.isPending ? "Opening…" : "Start editing"}</button>
            </div>
          )}
          {tab === "html" && !office && <HtmlPane run={name} doc={shown} version={version} />}
          {tab === "edit" && editing && !(office && editing === shown) && (popped.includes(editing) ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-[0.8125rem] text-muted">
              <div>{editing} is open in its own window. Its unsaved changes show in the HTML tab as you type.</div>
              <div className="flex gap-2">
                <button onClick={() => setTab("html")} className="rounded-md border border-border px-3 py-1 hover:border-accent">Show the HTML</button>
                <button onClick={() => post({ type: "return", run: name, path: editing })} className="flex items-center gap-1 rounded-md border border-border px-3 py-1 hover:border-accent">
                  <Undo2 size="0.8125rem" /> Bring the editor back here
                </button>
              </div>
            </div>
          ) : (
            <EditPane
              run={name}
              path={editing}
              isMaster={data.meta.masters.includes(editing)}
              onSaved={onSaved}
              onPopout={() => {
                if (openPopout(name, editing)) setTab("html");
              }}
              onAbsorb={(session) => {
                setChat(session);
                setTab("chat");
                void client.invalidateQueries({ queryKey: ["sessions"] });
              }}
            />
          ))}
          {((tab === "document" && !office) || tab === "file") && (
            <div ref={reader} onScroll={(e) => rememberScroll(name, readerKey, e.currentTarget.scrollTop)} className="scroll-thin h-full overflow-y-auto">
              <div className="mx-auto max-w-3xl px-8 py-6">
                {tab === "file" && selected ? (
                  <FileViewer run={name} path={selected} />
                ) : shown && shown !== primary ? (
                  <FileViewer run={name} path={shown} />
                ) : data.master ? (
                  <Markdown text={data.master} run={name} />
                ) : (
                  <div className="text-[0.8125rem] text-faint">No master document yet ({data.meta.masters.join(", ")}).</div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
      {tab !== "chat" && panelOpen && (
      <Panel size={PANELS.runPanel} side="right" overlayBelow={1000} onClose={() => setPanelOpen(false)} className="bg-panel/50">
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-4 text-[0.7812rem]">
        <div className="mb-1.5 flex items-center text-[0.6875rem] font-medium uppercase tracking-wide text-faint">
          Stages
          <button onClick={() => setPanelOpen(false)} title="Collapse the panel" className="ml-auto rounded-md p-0.5 normal-case hover:bg-panel hover:text-fg">
            <PanelRightClose size="0.875rem" />
          </button>
        </div>
        {data.stages.map((s) => (
          <div key={s.stage} className="flex items-center gap-1.5 py-0.5" title={s.detail}>
            {s.ok ? <Check size="0.75rem" className="text-good" /> : <Circle size="0.625rem" className="mx-0.5 text-faint" />}
            <span className={s.ok ? "" : "text-faint"}>{s.stage}</span>
            <span className="ml-auto truncate pl-2 text-[0.6875rem] text-faint">{s.detail}</span>
          </div>
        ))}
        <div className="mb-1.5 mt-4 flex items-center gap-2 text-[0.6875rem] font-medium uppercase tracking-wide text-faint">
          <span>Files</span>
          <button onClick={() => importInput.current?.click()} disabled={importFiles.isPending} className="ml-auto flex items-center gap-1 rounded border border-border px-1.5 py-0.5 normal-case hover:border-accent disabled:opacity-40" title="Add source files to this project">
            <Upload size="0.6875rem" /> Import
          </button>
          <input ref={importInput} type="file" multiple className="hidden" onChange={(e) => { const files = Array.from(e.target.files ?? []); e.target.value = ""; if (files.length) importFiles.mutate(files); }} />
        </div>
        <label className="mb-1.5 flex items-center gap-1.5 text-[0.6875rem] text-faint">
          <input type="checkbox" checked={aiImport} onChange={(e) => setAiImport(e.target.checked)} /> AI generated material (leads only)
        </label>
        {fileMessage && <div className="mb-2 text-[0.6875rem] text-muted">{fileMessage}</div>}
        <div className="space-y-0.5">
          {data.files.map((f) => (
            <div key={f.path} className="flex items-center gap-1">
            <button
              onClick={() => {
                setSelected(f.path);
                setTab("file");
              }}
              className={clsx("flex min-w-0 flex-1 items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-panel", selected === f.path && tab === "file" && "bg-panel")}
            >
              <span className={clsx("min-w-0 flex-1 truncate", f.path === primary && "font-medium")}>{f.path}</span>
              <span className="shrink-0 text-[0.6562rem] text-faint">
                {bytes(f.size)} · {day(f.mtime)}
              </span>
            </button>
            {f.path.startsWith("external_data/") && !["README.md", "WANTED.md", "ai_reports/README.md"].includes(f.path.slice("external_data/".length)) && (
              <button title={`Remove ${f.path}`} className="shrink-0 rounded p-1 text-faint hover:text-bad" disabled={removeFile.isPending} onClick={() => { if (window.confirm(`Move ${f.path} to this project's recoverable .trash folder? Any evidence already drawn from it will need checking.`)) removeFile.mutate(f.path); }}>
                <Trash2 size="0.75rem" />
              </button>
            )}
            </div>
          ))}
        </div>
      </div>
      </Panel>
      )}
      {critiqueReview && (
        <CritiqueQuestionsDialog
          key={critiqueReview.path}
          questions={critiqueReview.questions}
          submitting={applyCritique.isPending}
          error={applyCritique.isError ? (applyCritique.error as Error).message : ""}
          onClose={() => setCritiqueReview(null)}
          onSubmit={(answers) => applyCritique.mutate({ path: critiqueReview.path, ...answers })}
        />
      )}
      {changesOpen && subjects.data && (
        <ChangesDialog
          run={name}
          subjects={subjects.data.subjects}
          onClose={() => setChangesOpen(false)}
          onOpenFile={(path) => {
            setChangesOpen(false);
            setSelected(path);
            setTab("file");
          }}
          onStarted={(session) => {
            setChangesOpen(false);
            setChat(session);
            setTab("chat");
            void client.invalidateQueries({ queryKey: ["sessions"] });
          }}
        />
      )}
    </div>
  );
}
