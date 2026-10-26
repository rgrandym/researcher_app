import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ClipboardPaste, Copy } from "lucide-react";
import type { ReactNode } from "react";

export interface AppearanceValues {
  color: Record<string, string>;
  series: string[];
  fonts: { heading: string; body: string; base_pt: number; heading_weight: number };
  chart: {
    grid: string; axis: string; line_width: number; line_style: string;
    bar_width: number; bar_corner_radius_px: number; marker_size: number;
    font_scale: number; value_labels: boolean; bar_opacity: number;
    line_opacity: number; area_fill_opacity: number; stacked_fill_opacity: number;
    label_font_scale: number; bar_fill: string; label_position: string; label_color: string;
    title_color: string; text_color: string; note_color: string; background: string;
    highlight_color: string; muted_mark_color: string;
    caption_label_color: string; caption_color: string; caption_font_size_pt: number; title_font: string; label_font: string;
  };
  table: ReportTable;
  items: { figures: Record<string, FigureAppearance>; tables: Record<string, TableAppearance> };
}

// The report's own table settings: every table starts from these, apart from the page.
export interface ReportTable {
  border: string; rule_weight_pt: number; header_bg: string; header_fg: string;
  body_bg: string; body_fg: string; stripe_bg: string; caption_fg: string;
  font_family: string; header_font: string;
  font_size_pt: number; header_font_size_pt: number; caption_font_size_pt: number;
}

export interface FigureAppearance {
  series: string[]; grid: string; axis: string; background: string;
  title_color: string; text_color: string; note_color: string; highlight_color: string; muted_mark_color: string;
  line_width: number; line_style: string; bar_width: number; bar_corner_radius_px: number; marker_size: number;
  font_scale: number; value_labels: boolean; heading_font: string; body_font: string;
  bar_opacity: number; line_opacity: number; area_fill_opacity: number; stacked_fill_opacity: number;
  label_font_scale: number; bar_fill: string; label_position: string; label_color: string;
  label_text: Record<string, string>;
}

export interface TableAppearance {
  header_bg: string; header_fg: string; border: string;
  font_size_pt: number; header_font_size_pt: number; cell_padding_em: number; rule_weight_pt: number;
  caption_fg: string; caption_font_size_pt: number;
  font_family: string; width_percent: number; body_bg: string; body_fg: string; stripe_bg: string;
  rule_style: string; borders: string;
}

type TableLook = Omit<TableAppearance, "font_size_pt" | "header_font_size_pt" | "font_family" | "width_percent" | "cell_padding_em" | "caption_fg" | "caption_font_size_pt">;

// Ready-made table designs. Each sets colours and rules; the table keeps its font, size,
// width and padding.
const TABLE_PRESETS: { name: string; look: TableLook }[] = [
  { name: "Clean rules", look: { header_bg: "#FFFFFF", header_fg: "#1F2933", body_bg: "#FFFFFF", body_fg: "#1F2933", stripe_bg: "#FFFFFF", border: "#C9D1D9", rule_weight_pt: 0.6, rule_style: "solid", borders: "horizontal" } },
  { name: "Academic", look: { header_bg: "#FFFFFF", header_fg: "#111111", body_bg: "#FFFFFF", body_fg: "#222222", stripe_bg: "#FFFFFF", border: "#111111", rule_weight_pt: 0.6, rule_style: "solid", borders: "minimal" } },
  { name: "Banded slate", look: { header_bg: "#334155", header_fg: "#FFFFFF", body_bg: "#FFFFFF", body_fg: "#1E293B", stripe_bg: "#F1F5F9", border: "#CBD5E1", rule_weight_pt: 0.5, rule_style: "solid", borders: "horizontal" } },
  { name: "Ocean", look: { header_bg: "#0F4C81", header_fg: "#FFFFFF", body_bg: "#FFFFFF", body_fg: "#102A43", stripe_bg: "#EAF2FA", border: "#9FB3C8", rule_weight_pt: 0.5, rule_style: "solid", borders: "horizontal" } },
  { name: "Full grid", look: { header_bg: "#F3F4F6", header_fg: "#111827", body_bg: "#FFFFFF", body_fg: "#111827", stripe_bg: "#FFFFFF", border: "#9CA3AF", rule_weight_pt: 0.5, rule_style: "solid", borders: "grid" } },
  { name: "Boxed teal", look: { header_bg: "#E6F4F1", header_fg: "#0B5345", body_bg: "#FFFFFF", body_fg: "#1B2631", stripe_bg: "#F7FBFA", border: "#48A999", rule_weight_pt: 0.75, rule_style: "solid", borders: "boxed" } },
  { name: "Ledger", look: { header_bg: "#FBF7EE", header_fg: "#5B4636", body_bg: "#FFFDF8", body_fg: "#3E3328", stripe_bg: "#F6EFE2", border: "#C8B79E", rule_weight_pt: 0.6, rule_style: "dotted", borders: "horizontal" } },
  { name: "Double rule", look: { header_bg: "#FFFFFF", header_fg: "#1F2937", body_bg: "#FFFFFF", body_fg: "#1F2937", stripe_bg: "#FFFFFF", border: "#1F2937", rule_weight_pt: 0.6, rule_style: "double", borders: "minimal" } },
  { name: "Charcoal", look: { header_bg: "#1F2937", header_fg: "#F9FAFB", body_bg: "#FFFFFF", body_fg: "#111827", stripe_bg: "#F9FAFB", border: "#D1D5DB", rule_weight_pt: 0.5, rule_style: "solid", borders: "header" } },
  { name: "Amber", look: { header_bg: "#B45309", header_fg: "#FFFFFF", body_bg: "#FFFFFF", body_fg: "#292524", stripe_bg: "#FEF3C7", border: "#F59E0B", rule_weight_pt: 0.5, rule_style: "dashed", borders: "horizontal" } },
];

const LINE_TYPES: [string, string][] = [["solid", "Solid"], ["dashed", "Dashed"], ["dotted", "Dotted"], ["double", "Double"]];
const LAYOUTS: [string, string][] = [
  ["horizontal", "Rule under every row"], ["grid", "Full grid"], ["minimal", "Top, header and bottom rules"],
  ["boxed", "Outer box and header rule"], ["header", "Header rule only"],
];

// A small drawing of a table in a given look: the same layouts the HTML and Word use.
function TableSwatch({ look, font }: { look: TableLook; font?: string }) {
  const width = Math.max(1, Math.round(look.rule_weight_pt * 1.6));
  const rule = `${look.rule_style === "double" ? Math.max(3, width) : width}px ${look.rule_style} ${look.border}`;
  const heavy = `${look.rule_style === "double" ? 3 : width + 1}px ${look.rule_style} ${look.border}`;
  const table: React.CSSProperties = { borderCollapse: "collapse", width: "100%", fontSize: "0.5625rem", fontFamily: font };
  if (look.borders === "minimal") Object.assign(table, { borderTop: heavy, borderBottom: heavy });
  if (look.borders === "boxed") table.border = rule;
  const cell = (header: boolean, row: number): React.CSSProperties => ({
    padding: "1px 3px",
    textAlign: "left",
    fontWeight: header ? 600 : 400,
    background: header ? look.header_bg : row % 2 ? look.stripe_bg : look.body_bg,
    color: header ? look.header_fg : look.body_fg,
    border: look.borders === "grid" ? rule : undefined,
    borderBottom: look.borders === "grid" ? rule : look.borders === "horizontal" || header ? (header && look.borders !== "horizontal" ? heavy : rule) : undefined,
  });
  return (
    <table style={table}>
      <thead><tr><th style={cell(true, 0)}>Item</th><th style={cell(true, 0)}>2025</th></tr></thead>
      <tbody>{[1, 2, 3].map((r) => <tr key={r}><td style={cell(false, r)}>Row {r}</td><td style={cell(false, r)}>{r * 12}</td></tr>)}</tbody>
    </table>
  );
}

function Presets({ onPick, font }: { onPick: (look: TableLook) => void; font?: string }) {
  return (
    <div className="grid grid-cols-2 gap-1.5">
      {TABLE_PRESETS.map((preset) => (
        <button key={preset.name} onClick={() => onPick(preset.look)} title={`Apply ${preset.name}`} className="rounded border border-border bg-white p-1.5 text-left hover:border-accent">
          <TableSwatch look={preset.look} font={font} />
          <div className="mt-1 text-[0.6875rem] text-[#1F2933]">{preset.name}</div>
        </button>
      ))}
    </div>
  );
}

function Choice({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (value: string) => void }) {
  return (
    <label className="flex items-center justify-between gap-2 text-[0.75rem]">{label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="max-w-44 rounded border border-border bg-surface px-2 py-1">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

export interface AppearanceResponse {
  style: string;
  saved_style: string | null;
  values: AppearanceValues;
  custom: boolean;
  available: {
    figures: { id: string; number: number | null; label: string; type: string; value_labels: { key: string; name: string; default: string }[] }[];
    tables: { id: string; number: number | null; label: string; captioned: boolean }[];
  };
}

/** A figure or table clicked in the rendered report, and the part of it clicked. */
export interface AppearancePick {
  kind: "figure" | "table";
  id?: string;
  number?: number;
  part: string;
  seq: number;
}

const FONTS = ["Inter", "Avenir Next", "Charter", "Helvetica Neue", "Arial", "Source Sans 3", "Georgia", "Times New Roman"];
// The page palette reaches the text only: charts and tables have their own colours below.
const COLOURS: [string, string][] = [
  ["Body text", "body"], ["Headings and bold text", "ink"], ["References and links", "link"],
  ["Secondary text", "muted"], ["Accent", "accent"], ["Callout wash", "accent_soft"],
  ["Page background", "surface"], ["Panels and code", "surface_alt"], ["Page rules", "rule"],
];

// The colour last copied from any colour field. Paste reads it first, since a webview may
// refuse to read the system clipboard; the system clipboard gets the code too.
let copiedColour: string | null = null;
const copiedListeners = new Set<() => void>();
const copiedStore = {
  set(value: string) { copiedColour = value; copiedListeners.forEach((listener) => listener()); },
  subscribe(listener: () => void) { copiedListeners.add(listener); return () => { copiedListeners.delete(listener); }; },
  get: () => copiedColour,
};

/** "#1a2b3c", "1A2B3C" or "#abc" as "#1A2B3C"; anything else as null. */
function parseHex(text: string): string | null {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text.trim());
  if (!m) return null;
  const hex = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  return `#${hex.toUpperCase()}`;
}

function Colour({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const copied = useSyncExternalStore(copiedStore.subscribe, copiedStore.get);
  const [text, setText] = useState(value.toUpperCase());
  const [note, setNote] = useState("");
  useEffect(() => setText(value.toUpperCase()), [value]);
  const flash = (message: string) => {
    setNote(message);
    window.setTimeout(() => setNote(""), 1200);
  };
  const commit = (raw: string) => {
    const hex = parseHex(raw);
    if (hex) onChange(hex);
    else setText(value.toUpperCase());
  };
  const copy = () => {
    const hex = value.toUpperCase();
    copiedStore.set(hex);
    navigator.clipboard?.writeText(hex).catch(() => undefined);
    flash("Copied");
  };
  const paste = async () => {
    let hex = copied;
    if (!hex) hex = parseHex(await navigator.clipboard?.readText().catch(() => "") ?? "");
    if (hex) { onChange(hex); flash("Pasted"); } else flash("No colour copied");
  };
  return (
    <div className="flex min-w-0 items-center gap-1.5 rounded border border-border bg-surface px-2 py-1.5 text-[0.75rem]">
      <input aria-label={label} type="color" value={value} onChange={(e) => onChange(e.target.value)} className="h-6 w-7 shrink-0 cursor-pointer border-0 bg-transparent p-0" />
      <span className="min-w-0 flex-1 truncate" title={label}>{note ? <span className="text-accent">{note}</span> : label}</span>
      <input aria-label={`${label}, hex code`} value={text} spellCheck={false} maxLength={7}
        onChange={(e) => { setText(e.target.value); const hex = parseHex(e.target.value); if (hex && e.target.value.replace("#", "").length === 6) onChange(hex); }}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") commit(e.currentTarget.value); }}
        className="w-[4.6rem] rounded border border-transparent bg-transparent px-1 font-mono text-[0.6875rem] text-faint hover:border-border focus:border-accent focus:text-fg focus:outline-none" />
      <button type="button" onClick={copy} title={`Copy ${value.toUpperCase()}`} aria-label={`Copy the ${label} colour`} className="rounded p-0.5 text-faint hover:bg-panel hover:text-fg">
        <Copy size="0.75rem" />
      </button>
      <button type="button" onClick={() => void paste()} title={copied ? `Paste ${copied}` : "Paste a copied colour"} aria-label={`Paste a colour into ${label}`} className="flex items-center gap-0.5 rounded p-0.5 text-faint hover:bg-panel hover:text-fg">
        <ClipboardPaste size="0.75rem" />
        {copied && <span className="h-2.5 w-2.5 rounded-sm border border-border" style={{ background: copied }} />}
      </button>
    </div>
  );
}

function NumberField({ label, value, min, max, step, onChange }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-2 text-[0.75rem]">
      <span>{label}</span>
      <input type="number" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-20 rounded border border-border bg-surface px-2 py-1 text-right font-mono" />
    </label>
  );
}

function LabelColour({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <div className="space-y-1">
    <label className="flex items-center gap-2 text-[0.75rem]">
      <input type="checkbox" checked={value === "auto"} onChange={(e) => onChange(e.target.checked ? "auto" : "#111418")} />
      Automatic label contrast
    </label>
    {value !== "auto" && <Colour label="Label text" value={value} onChange={onChange} />}
  </div>;
}

const LINE_STYLES: [string, string][] = [["solid", "Solid"], ["dashed", "Dashed"], ["dotted", "Dotted"], ["dashdot", "Dash and dot"]];
const BAR_FILLS: [string, string][] = [["solid", "Solid"], ["outline", "Outline"], ["hatched", "Hatched"]];
const LABEL_POSITIONS: [string, string][] = [["auto", "Automatic"], ["inside", "Inside"], ["outside", "Outside"]];
const FONT_CHOICES: [string, string][] = FONTS.map((font) => [font, font]);

// One part of a figure or table. A click on that part in the report opens it here and
// flashes it, so the author sees which settings reach what they clicked.
function Part({ part, title, focus, children }: { part: string; title: string; focus: { part: string; seq: number } | null; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    if (focus?.part !== part) return;
    ref.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    setFlash(true);
    const timer = window.setTimeout(() => setFlash(false), 1400);
    return () => window.clearTimeout(timer);
  }, [focus, part]);
  return (
    <section ref={ref} data-part={part} className={`scroll-mt-2 rounded border p-2 transition-colors ${flash ? "border-accent bg-accent/10" : "border-border"}`}>
      <h4 className="mb-2 text-[0.6875rem] font-semibold uppercase tracking-wide text-faint">{title}</h4>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function H3({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 text-[0.6875rem] font-semibold uppercase tracking-wide text-faint">{children}</h3>;
}

// A caption for a table that has none, written into the document by the app.
function AddCaption({ number, onAdd }: { number: number | null; onAdd: (title: string) => Promise<string> }) {
  const [title, setTitle] = useState("");
  const [state, setState] = useState<{ busy: boolean; error: string }>({ busy: false, error: "" });
  const add = () => {
    setState({ busy: true, error: "" });
    onAdd(title).then(() => setState({ busy: false, error: "" }), (e: Error) => setState({ busy: false, error: e.message }));
  };
  return (
    <div className="space-y-1.5 rounded border border-warn/60 p-2 text-[0.75rem]">
      <p className="text-muted">This table has no caption in the document, so it shows only “Table {number ?? "n"}.” and cannot be cited by name. Give it a title and the app writes a caption line above it in the document.</p>
      <input value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && title.trim()) add(); }} maxLength={300} placeholder="Caption title, e.g. Royalty per litre at list price"
        className="w-full rounded border border-border bg-surface px-2 py-1" />
      <button onClick={add} disabled={!title.trim() || state.busy} className="rounded border border-border px-2.5 py-1 hover:border-accent disabled:opacity-40">{state.busy ? "Adding…" : "Add caption to the document"}</button>
      {state.error && <div className="text-bad">{state.error}</div>}
    </div>
  );
}

export default function AppearancePanel({ data, pick, doc, onAddCaption, onApply, onReset, onRetry, busy, loading, error }: {
  data?: AppearanceResponse;
  pick?: AppearancePick | null;
  doc?: string;
  onAddCaption?: (table: string, title: string) => Promise<string>;
  onApply: (values: AppearanceValues, rememberDefault: boolean) => void;
  onReset: () => void;
  onRetry: () => void;
  busy: boolean;
  loading: boolean;
  error?: string;
}) {
  const [draft, setDraft] = useState<AppearanceValues | null>(null);
  const [selected, setSelected] = useState("report");
  const [focus, setFocus] = useState<{ part: string; seq: number } | null>(null);
  const [missed, setMissed] = useState("");
  const handled = useRef(0);
  useEffect(() => {
    if (data) setDraft(structuredClone(data.values));
  }, [data]);
  // A click in the report picks the figure or table here, and the part of it clicked.
  useEffect(() => {
    if (!pick || !data || pick.seq === handled.current) return;
    handled.current = pick.seq;
    const found = pick.kind === "table"
      ? data.available.tables.find((t) => t.id === pick.id)
      : data.available.figures.find((f) => (pick.id ? f.id === pick.id : f.number === pick.number));
    if (!found) {
      setMissed(pick.kind === "table"
        ? "That table is not in this document's list. Render the document again, then click it."
        : "That figure is not a chart from this report's data, so it has no chart settings.");
      return;
    }
    setMissed("");
    setSelected(found.id);
    setFocus({ part: pick.part, seq: pick.seq });
  }, [pick, data]);
  if (!draft) {
    if (error) return (
      <div className="flex items-center gap-3 border-b border-border p-4 text-[0.75rem]">
        <span className="text-bad">Could not load appearance controls: {error}</span>
        <button onClick={onRetry} className="rounded border border-border px-2.5 py-1 hover:border-accent">Retry</button>
      </div>
    );
    return <div className="p-4 text-[0.75rem] text-muted">{loading ? "Loading appearance controls…" : "Appearance controls are unavailable."}</div>;
  }

  const changeColor = (key: string, value: string) => setDraft((current) => current && ({
    ...current, color: { ...current.color, [key]: value },
  }));
  const changeChart = <K extends keyof AppearanceValues["chart"]>(key: K, value: AppearanceValues["chart"][K]) =>
    setDraft((current) => current && ({ ...current, chart: { ...current.chart, [key]: value } }));
  const changeFont = <K extends keyof AppearanceValues["fonts"]>(key: K, value: AppearanceValues["fonts"][K]) =>
    setDraft((current) => current && ({ ...current, fonts: { ...current.fonts, [key]: value } }));
  const changeReportTable = <K extends keyof ReportTable>(key: K, value: ReportTable[K]) =>
    setDraft((current) => current && ({ ...current, table: { ...current.table, [key]: value } }));
  const selectedFigure = selected.startsWith("F") ? selected : null;
  const selectedTable = selected.startsWith("T") ? selected : null;
  const figureMeta = data?.available.figures.find((item) => item.id === selectedFigure);
  const tableMeta = data?.available.tables.find((item) => item.id === selectedTable);
  const figureName = (id: string | null) => {
    const n = data?.available.figures.find((item) => item.id === id)?.number;
    return n ? `Figure ${n}` : "this figure";
  };
  const tableName = (id: string | null) => {
    const n = data?.available.tables.find((item) => item.id === id)?.number;
    return n ? `Table ${n}` : "this table";
  };
  const figure: FigureAppearance | null = selectedFigure ? (draft.items?.figures[selectedFigure] ?? {
    series: draft.series, grid: draft.chart.grid, axis: draft.chart.axis,
    background: draft.chart.background, title_color: draft.chart.title_color,
    text_color: draft.chart.text_color, note_color: draft.chart.note_color,
    highlight_color: draft.chart.highlight_color, muted_mark_color: draft.chart.muted_mark_color,
    line_width: draft.chart.line_width,
    line_style: draft.chart.line_style, bar_width: draft.chart.bar_width,
    bar_corner_radius_px: draft.chart.bar_corner_radius_px,
    marker_size: draft.chart.marker_size, font_scale: draft.chart.font_scale,
    value_labels: draft.chart.value_labels, heading_font: draft.chart.title_font,
    body_font: draft.chart.label_font,
    bar_opacity: draft.chart.bar_opacity, line_opacity: draft.chart.line_opacity,
    area_fill_opacity: draft.chart.area_fill_opacity, stacked_fill_opacity: draft.chart.stacked_fill_opacity,
    label_font_scale: draft.chart.label_font_scale, bar_fill: draft.chart.bar_fill,
    label_position: draft.chart.label_position, label_color: draft.chart.label_color,
    label_text: {},
  }) : null;
  // A table with no settings of its own starts from the report's table settings: what it shows now.
  const tableDefaults = (): TableAppearance => {
    const t = draft.table;
    return {
      header_bg: t.header_bg, header_fg: t.header_fg, body_bg: t.body_bg, body_fg: t.body_fg, stripe_bg: t.stripe_bg,
      border: t.border, rule_weight_pt: t.rule_weight_pt, caption_fg: t.caption_fg,
      font_family: t.font_family, font_size_pt: t.font_size_pt, header_font_size_pt: t.header_font_size_pt,
      caption_font_size_pt: t.caption_font_size_pt,
      cell_padding_em: 0.45, width_percent: 100, rule_style: "solid", borders: "horizontal",
    };
  };
  const table = selectedTable ? (draft.items?.tables[selectedTable] ?? tableDefaults()) : null;
  const tableIds = data?.available.tables.map((item) => item.id) ?? [];
  // Every table at once: a preset's look over each table's own settings, or one table's settings copied.
  const styleAllTables = (patch: (current: TableAppearance) => TableAppearance) => setDraft((current) => {
    if (!current) return current;
    const tables = { ...current.items.tables };
    for (const id of tableIds) tables[id] = patch(tables[id] ?? tableDefaults());
    return { ...current, items: { ...current.items, tables } };
  });
  const updateFigure = <K extends keyof FigureAppearance>(key: K, value: FigureAppearance[K]) => {
    if (!selectedFigure || !figure) return;
    setDraft((current) => current && ({ ...current, items: {
      ...current.items, figures: { ...current.items.figures, [selectedFigure]: { ...figure, [key]: value } },
    } }));
  };
  const updateTable = <K extends keyof TableAppearance>(key: K, value: TableAppearance[K]) => {
    if (!selectedTable || !table) return;
    setDraft((current) => current && ({ ...current, items: {
      ...current.items, tables: { ...current.items.tables, [selectedTable]: { ...table, [key]: value } },
    } }));
  };
  const clearItem = () => setDraft((current) => {
    if (!current) return current;
    const items = structuredClone(current.items);
    if (selectedFigure) delete items.figures[selectedFigure];
    if (selectedTable) delete items.tables[selectedTable];
    return { ...current, items };
  });
  const own = selectedFigure ? draft.items.figures[selectedFigure] : selectedTable ? draft.items.tables[selectedTable] : undefined;

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="font-medium">Appearance</div>
        <span className="text-[0.75rem] text-muted">Click a table or a chart in the report to style it. Changes apply to HTML, PDF, Word, and figures.</span>
      </div>
      <label className="mb-3 flex flex-col gap-1 text-[0.75rem]">
        <span>Customise</span>
        <select value={selected} onChange={(e) => { setSelected(e.target.value); setFocus(null); setMissed(""); }} className="w-full rounded border border-border bg-surface px-2 py-1.5">
          <option value="report">Entire report</option>
          {!!data?.available.figures.length && <optgroup label="Figures, in document order">
            {data.available.figures.map((item) => <option key={item.id} value={item.id}>{item.number ? `Figure ${item.number}` : item.id}: {item.label}</option>)}
          </optgroup>}
          {!!data?.available.tables.length && <optgroup label="Tables, in document order">
            {data.available.tables.map((item) => <option key={item.id} value={item.id}>{item.number ? `Table ${item.number}` : item.id}: {item.label}</option>)}
          </optgroup>}
        </select>
      </label>
      {missed && <div className="mb-3 rounded border border-warn px-2 py-1.5 text-[0.75rem] text-warn">{missed}</div>}
      <div className="mb-3 flex flex-wrap gap-2">
        {selected === "report"
          ? <button onClick={onReset} disabled={busy || !data?.custom} className="rounded border border-border px-2.5 py-1 text-[0.75rem] disabled:opacity-40">Reset report</button>
          : <button onClick={clearItem} disabled={busy || !own} className="rounded border border-border px-2.5 py-1 text-[0.75rem] disabled:opacity-40">Reset this item</button>}
        <button onClick={() => onApply(draft, selected === "report")} disabled={busy} className="rounded bg-accent px-3 py-1 text-[0.75rem] text-white disabled:opacity-40">{busy ? "Applying…" : "Apply changes"}</button>
      </div>
      {error && <div className="mb-2 text-[0.75rem] text-bad">{error}</div>}
      {selected === "report" && <p className="mb-3 text-[0.75rem] text-muted">Text, charts and tables are styled apart: a page colour never changes a chart or a table. Applied report settings become the defaults for new reports using this preset.</p>}
      {selected === "report" && <div className="grid gap-4">
        <section>
          <H3>Page text</H3>
          <div className="grid gap-1.5">
            {COLOURS.map(([label, key]) => <Colour key={key} label={label} value={draft.color[key]} onChange={(value) => changeColor(key, value)} />)}
          </div>
          <div className="mt-2 space-y-2">
            {(["heading", "body"] as const).map((key) => (
              <Choice key={key} label={key === "heading" ? "Heading font" : "Body font"} value={draft.fonts[key]} options={FONT_CHOICES} onChange={(v) => changeFont(key, v)} />
            ))}
            <NumberField label="Body size (pt)" value={draft.fonts.base_pt} min={8} max={14} step={0.5} onChange={(value) => changeFont("base_pt", value)} />
            <Choice label="Heading weight" value={String(draft.fonts.heading_weight)} options={[["400", "Regular"], ["500", "Medium"], ["600", "Semibold"], ["700", "Bold"]]} onChange={(v) => changeFont("heading_weight", Number(v))} />
          </div>
        </section>
        <section>
          <H3>Charts, every figure</H3>
          <div className="space-y-2">
            <Part part="series" title="Series colours" focus={null}>
              {draft.series.map((value, i) => (
                <Colour key={i} label={`Series ${i + 1}`} value={value} onChange={(colour) => setDraft((current) => {
                  if (!current) return current;
                  const series = [...current.series]; series[i] = colour;
                  return { ...current, series };
                })} />
              ))}
              <Colour label="Highlighted bar" value={draft.chart.highlight_color} onChange={(v) => changeChart("highlight_color", v)} />
              <Colour label="Muted bars" value={draft.chart.muted_mark_color} onChange={(v) => changeChart("muted_mark_color", v)} />
            </Part>
            <Part part="text" title="Chart text" focus={null}>
              <Colour label="Titles and key labels" value={draft.chart.title_color} onChange={(v) => changeChart("title_color", v)} />
              <Colour label="Axis and data text" value={draft.chart.text_color} onChange={(v) => changeChart("text_color", v)} />
              <Colour label="Notes and secondary text" value={draft.chart.note_color} onChange={(v) => changeChart("note_color", v)} />
              <Choice label="Title font" value={draft.chart.title_font} options={FONT_CHOICES} onChange={(v) => changeChart("title_font", v)} />
              <Choice label="Label font" value={draft.chart.label_font} options={FONT_CHOICES} onChange={(v) => changeChart("label_font", v)} />
              <NumberField label="Chart text scale" value={draft.chart.font_scale} min={0.75} max={1.6} step={0.05} onChange={(value) => changeChart("font_scale", value)} />
            </Part>
            <Part part="frame" title="Background, axes and grid" focus={null}>
              <Colour label="Chart background" value={draft.chart.background} onChange={(v) => changeChart("background", v)} />
              <Colour label="Grid" value={draft.chart.grid} onChange={(value) => changeChart("grid", value)} />
              <Colour label="Axes" value={draft.chart.axis} onChange={(value) => changeChart("axis", value)} />
            </Part>
            <Part part="lines" title="Lines" focus={null}>
              <Choice label="Line style" value={draft.chart.line_style} options={LINE_STYLES} onChange={(v) => changeChart("line_style", v)} />
              <NumberField label="Line width (pt)" value={draft.chart.line_width} min={0.7} max={5} step={0.1} onChange={(value) => changeChart("line_width", value)} />
              <NumberField label="Marker size (pt)" value={draft.chart.marker_size} min={0} max={9} step={0.5} onChange={(value) => changeChart("marker_size", value)} />
              <NumberField label="Line opacity" value={draft.chart.line_opacity} min={0.1} max={1} step={0.05} onChange={(value) => changeChart("line_opacity", value)} />
              <NumberField label="Area fill opacity" value={draft.chart.area_fill_opacity} min={0} max={0.8} step={0.05} onChange={(value) => changeChart("area_fill_opacity", value)} />
            </Part>
            <Part part="bars" title="Bars" focus={null}>
              <NumberField label="Bar width" value={draft.chart.bar_width} min={0.25} max={0.9} step={0.05} onChange={(value) => changeChart("bar_width", value)} />
              <NumberField label="Bar corner (px)" value={draft.chart.bar_corner_radius_px} min={0} max={12} step={1} onChange={(value) => changeChart("bar_corner_radius_px", value)} />
              <Choice label="Bar fill" value={draft.chart.bar_fill} options={BAR_FILLS} onChange={(v) => changeChart("bar_fill", v)} />
              <NumberField label="Bar opacity" value={draft.chart.bar_opacity} min={0.1} max={1} step={0.05} onChange={(value) => changeChart("bar_opacity", value)} />
              <NumberField label="Stacked fill opacity" value={draft.chart.stacked_fill_opacity} min={0.1} max={1} step={0.05} onChange={(value) => changeChart("stacked_fill_opacity", value)} />
            </Part>
            <Part part="labels" title="Value labels" focus={null}>
              <label className="flex items-center gap-2 text-[0.75rem]"><input type="checkbox" checked={draft.chart.value_labels} onChange={(e) => changeChart("value_labels", e.target.checked)} /> Show value labels</label>
              <Choice label="Bar label position" value={draft.chart.label_position} options={LABEL_POSITIONS} onChange={(v) => changeChart("label_position", v)} />
              <NumberField label="Label text scale" value={draft.chart.label_font_scale} min={0.6} max={1.8} step={0.05} onChange={(value) => changeChart("label_font_scale", value)} />
              <LabelColour value={draft.chart.label_color} onChange={(value) => changeChart("label_color", value)} />
            </Part>
            <Part part="caption" title="Figure captions, below each figure" focus={null}>
              <Colour label='"Figure n." label' value={draft.chart.caption_label_color} onChange={(v) => changeChart("caption_label_color", v)} />
              <Colour label="Caption text" value={draft.chart.caption_color} onChange={(v) => changeChart("caption_color", v)} />
              <NumberField label="Caption size (pt)" value={draft.chart.caption_font_size_pt} min={5} max={16} step={0.5} onChange={(v) => changeChart("caption_font_size_pt", v)} />
            </Part>
          </div>
        </section>
        <section>
          <H3>Tables, every table</H3>
          <div className="space-y-2">
            <div>
              <div className="mb-1.5 text-[0.75rem]">Table designs{tableIds.length ? `, applied to all ${tableIds.length} tables` : ""}</div>
              {tableIds.length ? <Presets font={draft.table.font_family} onPick={(look) => styleAllTables((current) => ({ ...current, ...look }))} /> :
                <div className="text-[0.6875rem] text-faint">This report has no captioned tables.</div>}
              <p className="mt-1.5 text-[0.6875rem] text-muted">To style one table, click it in the report or choose it under Customise.</p>
            </div>
            <Part part="caption" title="Captions, below each table" focus={null}>
              <Colour label="Caption text" value={draft.table.caption_fg} onChange={(v) => changeReportTable("caption_fg", v)} />
              <NumberField label="Caption size (pt)" value={draft.table.caption_font_size_pt} min={5} max={16} step={0.5} onChange={(v) => changeReportTable("caption_font_size_pt", v)} />
            </Part>
            <Part part="header" title="Header row" focus={null}>
              <Colour label="Header background" value={draft.table.header_bg} onChange={(v) => changeReportTable("header_bg", v)} />
              <Colour label="Header text" value={draft.table.header_fg} onChange={(v) => changeReportTable("header_fg", v)} />
              <NumberField label="Header text size (pt)" value={draft.table.header_font_size_pt} min={6} max={16} step={0.5} onChange={(v) => changeReportTable("header_font_size_pt", v)} />
              <Choice label="Header and caption font" value={draft.table.header_font} options={FONT_CHOICES} onChange={(v) => changeReportTable("header_font", v)} />
            </Part>
            <Part part="body" title="Body rows" focus={null}>
              <Colour label="Body background" value={draft.table.body_bg} onChange={(v) => changeReportTable("body_bg", v)} />
              <Colour label="Alternating row" value={draft.table.stripe_bg} onChange={(v) => changeReportTable("stripe_bg", v)} />
              <Colour label="Body text" value={draft.table.body_fg} onChange={(v) => changeReportTable("body_fg", v)} />
              <NumberField label="Body text size (pt)" value={draft.table.font_size_pt} min={6} max={14} step={0.5} onChange={(v) => changeReportTable("font_size_pt", v)} />
              <Choice label="Body font" value={draft.table.font_family} options={FONT_CHOICES} onChange={(v) => changeReportTable("font_family", v)} />
            </Part>
            <Part part="rules" title="Rules" focus={null}>
              <Colour label="Table rules" value={draft.table.border} onChange={(v) => changeReportTable("border", v)} />
              <NumberField label="Table rule (pt)" value={draft.table.rule_weight_pt} min={0.2} max={2} step={0.1} onChange={(v) => changeReportTable("rule_weight_pt", v)} />
            </Part>
            {!!Object.keys(draft.items.tables).length && <p className="text-[0.6875rem] text-muted">Tables with their own settings ({Object.keys(draft.items.tables).map(tableName).join(", ")}) keep them; reset a table to follow these.</p>}
          </div>
        </section>
      </div>}
      {figure && <div className="space-y-2">
        <div className="text-[0.75rem] text-muted">These settings affect only {figureName(selectedFigure)}{doc ? ` in ${doc}` : ""}. Its caption is styled under Entire report. Cite it in the text as <code className="rounded bg-panel px-1">Figure [[{selectedFigure}]]</code>.</div>
        <Part part="series" title="Series colours" focus={focus}>
          {figure.series.map((value, i) => <Colour key={i} label={`Series ${i + 1}`} value={value} onChange={(colour) => {
            const series = [...figure.series]; series[i] = colour; updateFigure("series", series);
          }} />)}
          <Colour label="Highlighted bar" value={figure.highlight_color} onChange={(v) => updateFigure("highlight_color", v)} />
          <Colour label="Muted bars" value={figure.muted_mark_color} onChange={(v) => updateFigure("muted_mark_color", v)} />
        </Part>
        <Part part="text" title="Chart text" focus={focus}>
          <Colour label="Titles and key labels" value={figure.title_color} onChange={(v) => updateFigure("title_color", v)} />
          <Colour label="Axis and data text" value={figure.text_color} onChange={(v) => updateFigure("text_color", v)} />
          <Colour label="Notes and secondary text" value={figure.note_color} onChange={(v) => updateFigure("note_color", v)} />
          <Choice label="Title font" value={figure.heading_font} options={FONT_CHOICES} onChange={(v) => updateFigure("heading_font", v)} />
          <Choice label="Label font" value={figure.body_font} options={FONT_CHOICES} onChange={(v) => updateFigure("body_font", v)} />
          <NumberField label="Text scale" value={figure.font_scale} min={0.75} max={1.6} step={0.05} onChange={(v) => updateFigure("font_scale", v)} />
        </Part>
        <Part part="frame" title="Background, axes and grid" focus={focus}>
          <Colour label="Background" value={figure.background} onChange={(v) => updateFigure("background", v)} />
          <Colour label="Grid" value={figure.grid} onChange={(v) => updateFigure("grid", v)} />
          <Colour label="Axes" value={figure.axis} onChange={(v) => updateFigure("axis", v)} />
        </Part>
        <Part part="lines" title="Lines" focus={focus}>
          <Choice label="Line style" value={figure.line_style} options={LINE_STYLES} onChange={(v) => updateFigure("line_style", v)} />
          <NumberField label="Line width (pt)" value={figure.line_width} min={0.7} max={5} step={0.1} onChange={(v) => updateFigure("line_width", v)} />
          <NumberField label="Marker size (pt)" value={figure.marker_size} min={0} max={9} step={0.5} onChange={(v) => updateFigure("marker_size", v)} />
          <NumberField label="Line opacity" value={figure.line_opacity} min={0.1} max={1} step={0.05} onChange={(v) => updateFigure("line_opacity", v)} />
          <NumberField label="Area fill opacity" value={figure.area_fill_opacity} min={0} max={0.8} step={0.05} onChange={(v) => updateFigure("area_fill_opacity", v)} />
        </Part>
        <Part part="bars" title="Bars" focus={focus}>
          <NumberField label="Bar width" value={figure.bar_width} min={0.25} max={0.9} step={0.05} onChange={(v) => updateFigure("bar_width", v)} />
          <NumberField label="Bar corner (px)" value={figure.bar_corner_radius_px} min={0} max={12} step={1} onChange={(v) => updateFigure("bar_corner_radius_px", v)} />
          <Choice label="Bar fill" value={figure.bar_fill} options={BAR_FILLS} onChange={(v) => updateFigure("bar_fill", v)} />
          <NumberField label="Bar opacity" value={figure.bar_opacity} min={0.1} max={1} step={0.05} onChange={(v) => updateFigure("bar_opacity", v)} />
          <NumberField label="Stacked fill opacity" value={figure.stacked_fill_opacity} min={0.1} max={1} step={0.05} onChange={(v) => updateFigure("stacked_fill_opacity", v)} />
        </Part>
        <Part part="labels" title="Value labels" focus={focus}>
          <label className="flex items-center gap-2 text-[0.75rem]"><input type="checkbox" checked={figure.value_labels} onChange={(e) => updateFigure("value_labels", e.target.checked)} /> Show value labels</label>
          <Choice label="Bar label position" value={figure.label_position} options={LABEL_POSITIONS} onChange={(v) => updateFigure("label_position", v)} />
          <NumberField label="Label text scale" value={figure.label_font_scale} min={0.6} max={1.8} step={0.05} onChange={(v) => updateFigure("label_font_scale", v)} />
          <LabelColour value={figure.label_color} onChange={(v) => updateFigure("label_color", v)} />
          {!!figureMeta?.value_labels.length && <details className="border-t border-border pt-2">
            <summary className="cursor-pointer text-[0.75rem] font-medium">Edit individual value labels</summary>
            <p className="my-2 text-[0.6875rem] text-muted">Leave a field empty to use the value from the chart data.</p>
            <div className="space-y-2">
              {figureMeta.value_labels.map((label) => <label key={label.key} className="flex flex-col gap-1 text-[0.6875rem]">
                <span>{label.name}</span>
                <input type="text" maxLength={120} value={figure.label_text[label.key] ?? ""} placeholder={label.default}
                  onChange={(e) => {
                    const labels = { ...figure.label_text };
                    if (e.target.value) labels[label.key] = e.target.value;
                    else delete labels[label.key];
                    updateFigure("label_text", labels);
                  }}
                  className="w-full rounded border border-border bg-surface px-2 py-1 text-[0.75rem]" />
              </label>)}
            </div>
          </details>}
        </Part>
      </div>}
      {table && <div className="space-y-2">
        <div className="text-[0.75rem] text-muted">These settings affect only {tableName(selectedTable)}{tableMeta ? ` (${tableMeta.label.length > 60 ? `${tableMeta.label.slice(0, 60)}…` : tableMeta.label})` : ""}{doc ? ` in ${doc}` : ""}, in the HTML, the PDF and Word.</div>
        {tableMeta && !tableMeta.captioned && onAddCaption && <AddCaption key={tableMeta.id} number={tableMeta.number} onAdd={async (title) => {
          const id = await onAddCaption(tableMeta.id, title);
          setSelected(id);
          return id;
        }} />}
        {tableMeta?.captioned && <p className="text-[0.6875rem] text-muted">Cite it in the text as <code className="rounded bg-panel px-1">Table [[{tableMeta.id}]]</code>: the number follows the table if tables move.</p>}
        <Part part="design" title="Designs" focus={focus}>
          <Presets font={table.font_family} onPick={(look) => setDraft((current) => current && selectedTable ? ({ ...current, items: {
            ...current.items, tables: { ...current.items.tables, [selectedTable]: { ...table, ...look } },
          } }) : current)} />
          <div className="rounded border border-border bg-white p-2"><TableSwatch look={table} font={table.font_family} /></div>
        </Part>
        <Part part="caption" title="Caption" focus={focus}>
          <Colour label="Caption text" value={table.caption_fg} onChange={(v) => updateTable("caption_fg", v)} />
          <NumberField label="Caption size (pt)" value={table.caption_font_size_pt} min={5} max={16} step={0.5} onChange={(v) => updateTable("caption_font_size_pt", v)} />
        </Part>
        <Part part="header" title="Header row" focus={focus}>
          <Colour label="Header background" value={table.header_bg} onChange={(v) => updateTable("header_bg", v)} />
          <Colour label="Header text" value={table.header_fg} onChange={(v) => updateTable("header_fg", v)} />
          <NumberField label="Header text size (pt)" value={table.header_font_size_pt} min={6} max={16} step={0.5} onChange={(v) => updateTable("header_font_size_pt", v)} />
        </Part>
        <Part part="body" title="Body rows" focus={focus}>
          <Colour label="Body background" value={table.body_bg} onChange={(v) => updateTable("body_bg", v)} />
          <Colour label="Alternating row" value={table.stripe_bg} onChange={(v) => updateTable("stripe_bg", v)} />
          <Colour label="Body text" value={table.body_fg} onChange={(v) => updateTable("body_fg", v)} />
          <NumberField label="Body text size (pt)" value={table.font_size_pt} min={6} max={14} step={0.5} onChange={(v) => updateTable("font_size_pt", v)} />
          <Choice label="Font" value={table.font_family} options={FONT_CHOICES} onChange={(v) => updateTable("font_family", v)} />
          <NumberField label="Cell padding (em)" value={table.cell_padding_em} min={0.15} max={1.2} step={0.05} onChange={(v) => updateTable("cell_padding_em", v)} />
        </Part>
        <Part part="rules" title="Rules and width" focus={focus}>
          <Colour label="Rules" value={table.border} onChange={(v) => updateTable("border", v)} />
          <NumberField label="Rule width (pt)" value={table.rule_weight_pt} min={0.2} max={2} step={0.1} onChange={(v) => updateTable("rule_weight_pt", v)} />
          <Choice label="Line type" value={table.rule_style} options={LINE_TYPES} onChange={(v) => updateTable("rule_style", v)} />
          <Choice label="Rule layout" value={table.borders} options={LAYOUTS} onChange={(v) => updateTable("borders", v)} />
          <NumberField label="Table width (%)" value={table.width_percent} min={50} max={100} step={5} onChange={(v) => updateTable("width_percent", v)} />
        </Part>
        {tableIds.length > 1 && (
          <button onClick={() => styleAllTables(() => ({ ...table }))} className="rounded border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent">
            Use these settings for all {tableIds.length} tables
          </button>
        )}
      </div>}
    </div>
  );
}
