import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fileUrl } from "../lib/api";
import { place, rememberDraft } from "../lib/places";
import type { Subject } from "./ChangesDialog";
import DeckDesign from "./DeckDesign";
import type { DeckSelection } from "./DeckDesign";

/** Where a click on the rendered page asks the editor to open. */
export interface OfficeFocus { sheet?: string; cell?: string; slide?: number; at: number }

/** A workbook or deck rendered as a page; a click on a cell or slide calls onPick. A deck
 * with an editable master (`design`) also opens Palette and layout: boxes are moved, resized
 * and restyled on the page, and the deck's theme and colours changed, each saved to the master. */
export function OfficeHtml({ run, path, name, version, download, onPick, onEdit, editLabel = "Edit", design }: {
  run: string; path: string; name: string; version: number; download?: string; onPick: (focus: OfficeFocus) => void; onEdit: () => void; editLabel?: string;
  design?: { slug: string; master: string };
}) {
  const client = useQueryClient();
  const frame = useRef<HTMLIFrameElement>(null);
  const page = useQuery({
    queryKey: ["office-html", run, path, version],
    queryFn: () => api.get<string>(`/api/runs/${encodeURIComponent(run)}/office/html?${new URLSearchParams({ path })}`),
    refetchOnWindowFocus: false,
  });
  const [designing, setDesigning] = useState(false);
  const [selection, setSelection] = useState<DeckSelection | null>(null);
  const [pending, setPending] = useState(0);
  const [failure, setFailure] = useState("");
  const officeKey = ["office", run, design?.slug];
  const officeUrl = design ? `/api/runs/${encodeURIComponent(run)}/documents/${encodeURIComponent(design.slug)}/office` : "";
  const content = useQuery({ queryKey: officeKey, queryFn: () => api.get<Content>(officeUrl), enabled: Boolean(design && designing), refetchOnWindowFocus: false });
  // Changes are saved one after another, each against the master's latest saved time, and
  // the slide pictures are drawn again once the changes stop for a moment.
  const queue = useRef(Promise.resolve());
  const redraw = useRef<ReturnType<typeof setTimeout>>();
  const apply = (change: (data: OfficeData) => OfficeData) => {
    if (!design) return;
    setPending((n) => n + 1); setFailure("");
    queue.current = queue.current.then(async () => {
      const current = await client.ensureQueryData({ queryKey: officeKey, queryFn: () => api.get<Content>(officeUrl) });
      const data = change(current.data);
      const text = encode(data);
      const saved = await api.put<{ mtime: number }>(`/api/runs/${encodeURIComponent(run)}/file`, { path: design.master, content: text, mtime: current.mtime });
      client.setQueryData(officeKey, { ...current, data, text, mtime: saved.mtime });
      clearTimeout(redraw.current);
      redraw.current = setTimeout(() => void client.invalidateQueries({ queryKey: ["office-html", run, path] }), 1500);
    }).catch((e: Error) => {
      setFailure(`${e.message} The page shows the last saved design.`);
      void client.invalidateQueries({ queryKey: officeKey });
      void client.invalidateQueries({ queryKey: ["office-html", run, path] });
    }).finally(() => setPending((n) => n - 1));
  };
  const applyRef = useRef(apply);
  applyRef.current = apply;
  const pick = useRef(onPick);
  pick.current = onPick;
  const tellFrame = () => frame.current?.contentWindow?.postMessage({ type: "office-design", on: designing }, "*");
  useEffect(tellFrame, [designing]);
  useEffect(() => {
    const listen = (e: MessageEvent) => {
      const m = e.data as { type?: string; sheet?: string; cell?: string; slide?: number; shape?: string; box?: Box };
      if (e.source !== frame.current?.contentWindow) return;
      if (m?.type === "office-pick") pick.current({ sheet: m.sheet, cell: m.cell, slide: m.slide, at: Date.now() });
      if ((m?.type === "office-select" || m?.type === "office-box") && m.slide !== undefined && m.shape) {
        const at = { slide: m.slide, shape: m.shape };
        setSelection(at);
        if (m.type === "office-box" && m.box) {
          const box = m.box;
          applyRef.current((d) => ({
            ...d, slides: d.slides!.map((s, i) => i !== at.slide ? s : { ...s, shapes: s.shapes.map((sh) => sh.id === at.shape && sh.box ? { ...sh, box } : sh) }),
          }));
        }
      }
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, []);
  return <div className="flex h-full flex-col">
    <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-1.5 text-[0.75rem] text-muted">
      <span className="min-w-0 truncate">{name} · {designing ? "click a box to select it; drag to move, drag its corner to resize" : "click a cell or slide to edit it there"}</span>
      <div className="flex-1" />
      {page.isFetching && !page.isLoading && <span className="text-faint">Redrawing…</span>}
      {design && <button onClick={() => { setDesigning(!designing); setSelection(null); }} className={`rounded-md border px-2.5 py-1 hover:border-accent ${designing ? "border-accent text-accent" : "border-border text-fg"}`}>Palette and layout</button>}
      {download && <a className="rounded-md border border-border px-2.5 py-1 text-fg hover:border-accent" href={fileUrl(run, download)} download>Download</a>}
      <button onClick={onEdit} className="rounded-md border border-accent px-2.5 py-1 text-accent hover:bg-panel">{editLabel}</button>
    </div>
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        {page.isLoading && <p className="p-6 text-[0.8125rem] text-faint">Rendering…{path.toLowerCase().endsWith(".pptx") && " PowerPoint draws a new version of a deck once, which can take a minute or two."}</p>}
        {page.isError && <p role="alert" className="p-6 text-[0.8125rem] text-bad">{page.error.message}</p>}
        {page.data && <iframe ref={frame} title={path} sandbox="allow-scripts" srcDoc={page.data} onLoad={tellFrame} className="min-h-0 w-full flex-1 border-0 bg-white" />}
      </div>
      {design && designing && <aside className="w-72 shrink-0 border-l border-border bg-surface">
        <DeckDesign content={content.data} selection={selection} onApply={apply} pending={pending > 0} error={failure || (content.isError ? content.error.message : "")} />
      </aside>}
    </div>
  </div>;
}

type CellKind = "text" | "number" | "formula" | "boolean" | "date" | "datetime" | "time" | "error" | "readonly";
interface Cell { kind: CellKind; value: string | number | boolean }
interface Sheet { id: string; name: string; cells: Record<string, Cell> }
/** A shape's position and size on the slide, in points. */
export interface Box { x: number; y: number; w: number; h: number }
export interface TextStyle { font?: string; size?: number; color?: string; bold?: boolean; italic?: boolean; fill?: string; align?: "left" | "center" | "right" | "justify" }
export interface TextShape { id: string; kind: "text"; paragraphs: string[]; box?: Box; style?: TextStyle }
export interface TableShape { id: string; kind: "table"; rows: string[][]; box?: Box }
/** A picture, chart, video or group: it can be moved and resized, not rewritten. */
export interface ObjectShape { id: string; kind: "object"; name: string; box?: Box }
export type Shape = TextShape | TableShape | ObjectShape;
export interface Slide { id: string; shapes: Shape[] }
export interface DeckTheme { colors?: Record<string, string>; fonts?: { major?: string; minor?: string }; swap_colors?: Record<string, string>; swap_fonts?: Record<string, string> }
export interface OfficeData {
  version: 1;
  format: "xlsx" | "pptx";
  design: "preserve" | "new";
  sheets?: Sheet[];
  slides?: Slide[];
  theme?: DeckTheme;
}
export interface Content { data: OfficeData; text: string; mtime: number; source: string; palette?: { colors: string[]; fonts: string[] } }

export function encode(data: OfficeData): string {
  return `<!-- office-master:1 -->\n\n# ${data.format.toUpperCase()} document\n\n\`\`\`office\n${JSON.stringify(data, null, 2)}\n\`\`\`\n`;
}
export function decode(text: string): OfficeData {
  const match = /```office\n([\s\S]*)\n```/.exec(text);
  if (!match) throw new Error("Keep the office block containing the document data.");
  const data = JSON.parse(match[1]) as OfficeData;
  if (data.version !== 1 || !["xlsx", "pptx"].includes(data.format) || !["new", "preserve"].includes(data.design)) throw new Error("Invalid document format or design.");
  if (data.format === "xlsx" && (!Array.isArray(data.sheets) || !data.sheets.length || data.sheets.some((s) => !s || typeof s.id !== "string" || typeof s.name !== "string" || !s.cells || typeof s.cells !== "object" || Object.values(s.cells).some((c) => !c || !["text", "number", "formula", "boolean", "date", "datetime", "time", "error", "readonly"].includes(c.kind))))) throw new Error("Each workbook needs sheets with names and typed cells.");
  if (data.format === "pptx" && (!Array.isArray(data.slides) || !data.slides.length || data.slides.some((s) => !s || typeof s.id !== "string" || !Array.isArray(s.shapes) || s.shapes.some((sh) => !sh || typeof sh.id !== "string" || (sh.kind === "text" ? !Array.isArray(sh.paragraphs) || sh.paragraphs.some((p) => typeof p !== "string") : sh.kind === "object" ? typeof sh.name !== "string" : sh.kind !== "table" || !Array.isArray(sh.rows) || sh.rows.some((r) => !Array.isArray(r) || r.some((v) => typeof v !== "string"))))))) throw new Error("Each presentation needs slides with text, table or object shapes.");
  return data;
}
function column(index: number): string {
  let name = "";
  for (let n = index; n > 0; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + (n - 1) % 26) + name;
  return name;
}
function cellText(cell?: Cell): string { return cell ? String(cell.value) : ""; }
function inputCell(value: string, kind?: CellKind): Cell {
  if (kind === "text") return { kind, value };
  if (kind === "boolean") return { kind, value: value.toLowerCase() === "true" };
  if (kind === "number") return { kind, value: Number(value) };
  if (kind) return { kind, value };
  if (value.startsWith("=")) return { kind: "formula", value };
  if (/^-?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value) && !/^0\d/.test(value)) return { kind: "number", value: Number(value) };
  return { kind: "text", value };
}
const control = "rounded border border-border bg-bg px-2 py-1 text-[0.8125rem]";
const action = `${control} hover:border-accent disabled:opacity-40`;

// Buffer incomplete numeric input (a minus sign or trailing decimal point) until
// blur. Office values stay typed while the author can type a number normally.
function CellInput({ cell, label, onCommit, onFocus, className }: {
  cell?: Cell; label: string; onCommit: (value?: Cell) => void; onFocus?: () => void; className: string;
}) {
  const [value, setValue] = useState(cellText(cell));
  const saved = cellText(cell);
  useEffect(() => setValue(saved), [saved]);
  return <input aria-label={label} value={value} readOnly={cell?.kind === "readonly"} className={className} onFocus={onFocus}
    onChange={(e) => setValue(e.target.value)} onBlur={(e) => {
      if (value === cellText(cell)) return;
      if (cell?.kind === "number" && value !== "" && !Number.isFinite(Number(value))) {
        e.target.setCustomValidity("Enter a number."); e.target.reportValidity(); return;
      }
      e.target.setCustomValidity("");
      onCommit(value === "" ? undefined : inputCell(value, cell?.kind));
    }} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />;
}

function WorkbookEditor({ sheets, onChange, focus }: { sheets: Sheet[]; onChange: (sheets: Sheet[]) => void; focus?: OfficeFocus }) {
  const [index, setIndex] = useState(0);
  const [rowStart, setRowStart] = useState(1);
  const [colStart, setColStart] = useState(1);
  const [selected, setSelected] = useState("A1");
  const [address, setAddress] = useState("A1");
  const [sheetName, setSheetName] = useState("");
  const sheet = sheets[Math.min(index, sheets.length - 1)];
  // A cell clicked on the rendered page: its sheet, scrolled near it, and its input focused.
  useEffect(() => {
    const m = focus?.cell && /^([A-Z]{1,3})(\d+)$/.exec(focus.cell);
    const at = sheets.findIndex((s) => s.name === focus?.sheet);
    if (!m || at < 0) return;
    const col = [...m[1]].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0);
    setIndex(at); setSelected(m[0]); setAddress(m[0]);
    setRowStart(Math.max(1, Number(m[2]) - 3)); setColStart(Math.max(1, col - 2));
    setTimeout(() => document.querySelector<HTMLInputElement>(`input[aria-label="${CSS.escape(`${sheets[at].name}!${m[0]}`)}"]`)?.focus(), 50);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.at]);
  const current = sheet.cells[selected];
  const update = (key: string, value?: Cell) => {
    const cells = { ...sheet.cells };
    if (value) cells[key] = value;
    else delete cells[key];
    onChange(sheets.map((s) => s.id === sheet.id ? { ...s, cells } : s));
  };
  const goTo = () => {
    const m = /^([A-Z]{1,3})([1-9]\d{0,6})$/.exec(address.toUpperCase());
    if (!m) return;
    const col = [...m[1]].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0);
    const row = Number(m[2]);
    if (col > 16384 || row > 1048576) return;
    setSelected(m[0]); setRowStart(row); setColStart(col);
  };
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center gap-2">
      <label>Sheet <select aria-label="Sheet" value={index} onChange={(e) => { setIndex(Number(e.target.value)); setRowStart(1); setColStart(1); }} className={control}>
        {sheets.map((s, i) => <option key={s.id} value={i}>{s.name}</option>)}
      </select></label>
      <input aria-label="New sheet name" placeholder="New sheet name" value={sheetName} onChange={(e) => setSheetName(e.target.value)} className={control} />
      <button disabled={!sheetName.trim()} onClick={() => {
        onChange([...sheets, { id: `new-${crypto.randomUUID()}`, name: sheetName.trim(), cells: {} }]);
        setIndex(sheets.length); setSheetName(""); setRowStart(1); setColStart(1);
      }} className={action}>Add sheet</button>
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <input aria-label="Cell address" value={address} onChange={(e) => setAddress(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") goTo(); }} className={`${control} w-24`} />
      <button onClick={goTo} className={action}>Go to cell</button>
      <span className="text-muted">{selected}</span>
      <select aria-label="Cell type" value={current?.kind ?? "text"} disabled={current?.kind === "readonly"} onChange={(e) => update(selected, inputCell(cellText(current), e.target.value as CellKind))} className={control}>
        {["text", "number", "formula", "boolean", "date", "datetime", "time", "error", "readonly"].map((k) => <option key={k} value={k} disabled={k === "readonly"}>{k}</option>)}
      </select>
      <CellInput key={`${sheet.id}:${selected}`} label={`Value of ${selected}`} cell={current} onCommit={(value) => update(selected, value)} className={`${control} min-w-48 flex-1`} />
      <button disabled={!current || current.kind === "readonly"} onClick={() => update(selected)} className={action}>Clear cell</button>
    </div>
    <p className="text-[0.75rem] text-muted">Formulas appear as expressions here and recalculate when opened in Excel. Dates use ISO format. The cell type selector keeps literal text such as “=total” as text.</p>
    <div className="overflow-auto rounded border border-border">
      <table className="w-full border-collapse text-[0.8125rem]" aria-label={sheet.name}>
        <thead><tr><th className="bg-panel p-1">Row</th>{Array.from({ length: Math.min(10, 16385 - colStart) }, (_, c) => <th className="border border-border bg-panel p-1" key={c}>{column(colStart + c)}</th>)}</tr></thead>
        <tbody>{Array.from({ length: Math.min(40, 1048577 - rowStart) }, (_, r) => <tr key={r}>
          <th className="bg-panel px-2">{rowStart + r}</th>
          {Array.from({ length: Math.min(10, 16385 - colStart) }, (_, c) => {
            const key = `${column(colStart + c)}${rowStart + r}`;
            const cell = sheet.cells[key];
            return <td key={key} className="border border-border p-0"><CellInput key={`${sheet.id}:${key}`} label={`${sheet.name}!${key}`} cell={cell} onFocus={() => { setSelected(key); setAddress(key); }} onCommit={(value) => update(key, value)} className={`w-full min-w-28 bg-transparent px-2 py-1 outline-accent ${selected === key ? "bg-accent-bg" : ""}`} /></td>;
          })}
        </tr>)}</tbody>
      </table>
    </div>
    <div className="flex flex-wrap gap-2">
      <button className={action} disabled={rowStart === 1} onClick={() => setRowStart(Math.max(1, rowStart - 40))}>Previous rows</button>
      <button className={action} disabled={rowStart + 40 > 1048576} onClick={() => setRowStart(rowStart + 40)}>Next rows</button>
      <button className={action} disabled={colStart === 1} onClick={() => setColStart(Math.max(1, colStart - 10))}>Previous columns</button>
      <button className={action} disabled={colStart + 10 > 16384} onClick={() => setColStart(colStart + 10)}>Next columns</button>
    </div>
  </div>;
}

function PresentationEditor({ slides, onChange, focus }: { slides: Slide[]; onChange: (slides: Slide[]) => void; focus?: OfficeFocus }) {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (focus?.slide !== undefined && focus.slide < slides.length) setIndex(focus.slide);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.at]);
  const slide = slides[Math.min(index, slides.length - 1)];
  const update = (shapes: Slide["shapes"]) => onChange(slides.map((s) => s.id === slide.id ? { ...s, shapes } : s));
  return <div className="space-y-3">
    <div className="flex flex-wrap gap-2">
      <select aria-label="Slide" value={Math.min(index, slides.length - 1)} onChange={(e) => setIndex(Number(e.target.value))} className={control}>
        {slides.map((s, i) => <option key={s.id} value={i}>Slide {i + 1}</option>)}
      </select>
      <button className={action} onClick={() => {
        onChange([...slides, { id: `new-${crypto.randomUUID()}`, shapes: [{ id: `new-${crypto.randomUUID()}`, kind: "text", paragraphs: ["New slide"] }] }]);
        setIndex(slides.length);
      }}>Add slide</button>
      <button className={action} onClick={() => update([...slide.shapes, { id: `new-${crypto.randomUUID()}`, kind: "text", paragraphs: ["New text"] }])}>Add text box</button>
      <button className={action} disabled={index === 0} onClick={() => {
        const next = [...slides]; [next[index - 1], next[index]] = [next[index], next[index - 1]];
        onChange(next); setIndex(index - 1);
      }}>Move earlier</button>
      <button className={action} disabled={slides.length === 1} onClick={() => {
        if (window.confirm(`Remove slide ${index + 1} from the edited presentation?`)) { onChange(slides.filter((s) => s.id !== slide.id)); setIndex(Math.max(0, index - 1)); }
      }}>Remove slide</button>
    </div>
    <p className="text-[0.75rem] text-muted">Edit slide text and table cells below. Images, charts, speaker notes, and slide layout are retained in the exported deck. To move, resize or restyle a box, or change the deck's colours and fonts, use Palette and layout in the HTML tab.</p>
    <section aria-label={`Slide ${index + 1} content`} className="space-y-4 rounded border border-border bg-surface p-6 shadow-sm">
      {!slide.shapes.some((s) => s.kind !== "object") && <p className="text-muted">This slide contains no editable text or tables. Add a text box to write on it.</p>}
      {slide.shapes.map((shape, si) => shape.kind === "object" ? null : shape.kind === "text" ? <label className="block" key={shape.id}>
        <span className="text-[0.75rem] text-muted">Text box {si + 1}</span>
        <textarea aria-label={`Text box ${si + 1}`} className={`${control} mt-1 w-full resize-y leading-6`} rows={Math.max(2, shape.paragraphs.length + 1)} value={shape.paragraphs.join("\n")} onChange={(e) => update(slide.shapes.map((s) => s.id === shape.id ? { ...shape, paragraphs: e.target.value.split("\n") } : s))} />
      </label> : <div key={shape.id} className="overflow-auto"><table aria-label={`Table ${si + 1}`} className="w-full"><tbody>
        {shape.rows.map((row, ri) => <tr key={ri}>{row.map((value, ci) => <td key={ci} className="border border-border p-1">
          <textarea aria-label={`Table ${si + 1} row ${ri + 1} column ${ci + 1}`} value={value} className="w-full min-w-24 resize-y bg-transparent p-1 outline-accent" onChange={(e) => update(slide.shapes.map((s) => s.id === shape.id ? { ...shape, rows: shape.rows.map((r, i) => i === ri ? r.map((v, j) => j === ci ? e.target.value : v) : r) } : s))} />
        </td>)}</tr>)}
      </tbody></table></div>)}
    </section>
  </div>;
}

export default function OfficePane({ run, subject, edit = false, onReady, focus }: { run: string; subject: Subject; edit?: boolean; onReady: () => void; focus?: OfficeFocus }) {
  const client = useQueryClient();
  const path = subject.master ?? `${subject.slug}.md`;
  const base = `/api/runs/${encodeURIComponent(run)}/documents/${encodeURIComponent(subject.slug)}`;
  const [source, setSource] = useState(subject.deliverable?.ok && subject.deliverable.file ? subject.deliverable.file : `external_data/${subject.path}`);
  const [ready, setReady] = useState(Boolean(subject.master));
  const kept = place(run).drafts[path];
  const [text, setText] = useState(kept?.text ?? "");
  const [original, setOriginal] = useState(kept?.original ?? "");
  const [mtime, setMtime] = useState<number | null>(kept?.mtime ?? null);
  const [raw, setRaw] = useState(false);
  const [notice, setNotice] = useState("");
  const content = useQuery({ queryKey: ["office", run, subject.slug], queryFn: () => api.get<Content>(`${base}/office`), enabled: ready, refetchOnWindowFocus: false });
  useEffect(() => {
    if (content.data && !place(run).drafts[path]) {
      setText(content.data.text); setOriginal(content.data.text); setMtime(content.data.mtime);
    }
  }, [content.data, run, path]);
  useEffect(() => { if (mtime !== null) rememberDraft(run, path, { text, original, mtime }); }, [run, path, text, original, mtime]);
  const dirty = text !== original;
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const start = useMutation({
    mutationFn: () => api.post(`${base}/start`, { source }),
    onSuccess: () => { setReady(true); void client.invalidateQueries({ queryKey: ["subjects", run] }); onReady(); },
  });
  const save = useMutation({
    mutationFn: (submitted: { text: string; mtime: number | null }) => api.put<{ mtime: number }>(`/api/runs/${encodeURIComponent(run)}/file`, { path, content: submitted.text, mtime: submitted.mtime }),
    onSuccess: (result, submitted) => {
      setOriginal(submitted.text); setMtime(result.mtime); setNotice("Saved.");
      void client.invalidateQueries({ queryKey: ["office", run, subject.slug] }); onReady();
    },
  });
  const exported = useMutation({
    mutationFn: () => api.post<{ ok: boolean; files: string[]; problems: string[] }>(`${base}/export`, { formats: [subject.format] }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["subjects", run] }); void client.invalidateQueries({ queryKey: ["exports"] }); onReady(); },
  });
  if (!ready) return <div className="space-y-4 p-6 text-[0.8125rem]">
    <p>Open {subject.path} as an editable {subject.format === "xlsx" ? "spreadsheet" : "presentation"}. Your edits will be saved in this project and exported as .{subject.format}.</p>
    <label className="block">Start from <select aria-label="Starting document" value={source} onChange={(e) => setSource(e.target.value)} className={`${control} ml-2`}>
      <option value={`external_data/${subject.path}`}>Supplied file: {subject.path}</option>
      {subject.deliverable?.file && <option value={subject.deliverable.file}>Latest deliverable: {subject.deliverable.file}</option>}
    </select></label>
    <p className="text-muted">This starts editing from the selected file. Existing change plans are kept as reference; unapplied proposals are not included. Choose the latest deliverable to continue from changes already applied.</p>
    <button className={action} disabled={start.isPending} onClick={() => start.mutate()}>{start.isPending ? "Opening…" : "Open editor"}</button>
    {start.isError && <p role="alert" className="text-bad">{start.error.message}</p>}
  </div>;
  let model: OfficeData | null = null;
  let parseError = "";
  try { if (text) model = decode(text); } catch (e) { parseError = String(e); }
  const change = (data: OfficeData) => { setText(encode(data)); setNotice(""); exported.reset(); };
  const busy = save.isPending || exported.isPending;
  return <div className="flex h-full flex-col">
    <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2 text-[0.8125rem]">
      <span className="font-medium">{subject.office_file ?? subject.path}</span>
      {dirty && <span className="text-warn">Unsaved</span>}
      <div className="flex-1" />
      {edit && <button className={action} onClick={() => setRaw(!raw)}>{raw ? "Visual editor" : "Edit source"}</button>}
      <button className={action} disabled={!dirty || busy} onClick={() => setText(original)}>Revert</button>
      <button className={action} disabled={!dirty || busy || mtime === null} onClick={() => save.mutate({ text, mtime })}>Save</button>
      <button className={action} disabled={dirty || busy || !model} title={dirty ? "Save your edits before exporting" : undefined} onClick={() => exported.mutate()}>{exported.isPending ? "Exporting…" : `Export .${subject.format}`}</button>
    </div>
    <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4 text-[0.8125rem]">
      {(content.isLoading || (!text && !content.isError)) && <p>Loading…</p>}
      {model && <label className="flex flex-wrap items-center gap-2">Export design
        <select aria-label="Export design" value={model.design} disabled={busy} onChange={(e) => change({ ...model, design: e.target.value as OfficeData["design"] })} className={control}>
          <option value="preserve">Preserve supplied design</option>
          <option value="new">Create new design: clean theme</option>
        </select>
        <span className="text-[0.75rem] text-muted">{model.design === "new" ? "Aptos typography, navy headings, and a light palette; content and layout retained." : "Keep the selected file’s styles, layout, and native objects."}</span>
      </label>}
      {notice && <p className="text-good">{notice}</p>}
      {(save.isError || exported.isError || content.isError) && <div role="alert" className="text-bad">
        {(save.error ?? exported.error ?? content.error)?.message}
        {save.isError && <button className={`${action} ml-2`} onClick={async () => {
          if (!window.confirm("Reload the saved document and discard your unsaved edits?")) return;
          const result = await content.refetch();
          if (result.data) { setText(result.data.text); setOriginal(result.data.text); setMtime(result.data.mtime); save.reset(); }
        }}>Reload saved document</button>}
      </div>}
      {exported.data && <div className="space-y-1">
        <p className={exported.data.ok ? "text-good" : "text-bad"}>{exported.data.ok ? "Exported and checked by reopening the native file." : "Export failed."}</p>
        {exported.data.files.map((file) => <a key={file} className="block text-accent underline" href={fileUrl(run, file)} download>{file.split("/").pop()}</a>)}
        {exported.data.problems.map((problem) => <p key={problem} className="text-bad">{problem}</p>)}
      </div>}
      {(raw || parseError) ? <>
        {parseError && <p role="alert" className="text-bad">{parseError}</p>}
        <textarea aria-label="Office document source" className="h-[65vh] w-full rounded border border-border bg-bg p-3 font-mono text-[0.8125rem]" value={text} onChange={(e) => setText(e.target.value)} />
      </> : model?.format === "xlsx" ? <WorkbookEditor sheets={model.sheets ?? []} focus={focus} onChange={(sheets) => change({ ...model, sheets })} />
        : model?.format === "pptx" ? <PresentationEditor slides={model.slides ?? []} focus={focus} onChange={(slides) => change({ ...model, slides })} /> : null}
    </div>
  </div>;
}
