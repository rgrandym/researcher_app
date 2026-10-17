import { useEffect, useState } from "react";

export interface AppearanceValues {
  color: Record<string, string>;
  series: string[];
  fonts: { heading: string; body: string; base_pt: number; heading_weight: number };
  chart: {
    grid: string; axis: string; line_width: number; line_style: string;
    bar_width: number; bar_corner_radius_px: number; marker_size: number;
    font_scale: number; value_labels: boolean;
  };
  table: { border: string; rule_weight_pt: number };
  items: { figures: Record<string, FigureAppearance>; tables: Record<string, TableAppearance> };
}

export interface FigureAppearance {
  series: string[]; grid: string; axis: string; background: string;
  line_width: number; line_style: string; bar_width: number; bar_corner_radius_px: number; marker_size: number;
  font_scale: number; value_labels: boolean; heading_font: string; body_font: string;
}

export interface TableAppearance {
  header_bg: string; header_fg: string; border: string;
  font_size_pt: number; cell_padding_em: number; rule_weight_pt: number;
  font_family: string; width_percent: number;
}

export interface AppearanceResponse {
  style: string;
  saved_style: string | null;
  values: AppearanceValues;
  custom: boolean;
  available: { figures: { id: string; label: string }[]; tables: { id: string; label: string }[] };
}

const FONTS = ["Inter", "Avenir Next", "Charter", "Helvetica Neue", "Arial", "Source Sans 3", "Georgia", "Times New Roman"];
const COLOURS: [string, string][] = [
  ["Text", "body"], ["Headings", "ink"], ["References and links", "link"],
  ["Secondary text", "muted"], ["Accent", "accent"], ["Accent wash", "accent_soft"],
  ["Page", "surface"], ["Panel", "surface_alt"], ["Rules", "rule"],
  ["Muted marks", "mute_fill"],
];

function Colour({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="flex min-w-0 items-center gap-2 rounded border border-border bg-surface px-2 py-1.5 text-[0.75rem]">
      <input aria-label={label} type="color" value={value} onChange={(e) => onChange(e.target.value)} className="h-6 w-7 shrink-0 cursor-pointer border-0 bg-transparent p-0" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className="font-mono text-[0.6875rem] text-faint">{value.toUpperCase()}</span>
    </label>
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

export default function AppearancePanel({ data, onApply, onReset, onRetry, busy, loading, error }: {
  data?: AppearanceResponse;
  onApply: (values: AppearanceValues) => void;
  onReset: () => void;
  onRetry: () => void;
  busy: boolean;
  loading: boolean;
  error?: string;
}) {
  const [draft, setDraft] = useState<AppearanceValues | null>(null);
  const [selected, setSelected] = useState("report");
  useEffect(() => {
    if (data) setDraft(structuredClone(data.values));
  }, [data]);
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
  const selectedFigure = selected.startsWith("F") ? selected : null;
  const selectedTable = selected.startsWith("T") ? selected : null;
  const figure = selectedFigure ? (draft.items?.figures[selectedFigure] ?? {
    series: draft.series, grid: draft.chart.grid, axis: draft.chart.axis,
    background: draft.color.surface, line_width: draft.chart.line_width,
    line_style: draft.chart.line_style, bar_width: draft.chart.bar_width,
    bar_corner_radius_px: draft.chart.bar_corner_radius_px,
    marker_size: draft.chart.marker_size, font_scale: draft.chart.font_scale,
    value_labels: draft.chart.value_labels, heading_font: draft.fonts.heading,
    body_font: draft.fonts.body,
  }) : null;
  const table = selectedTable ? (draft.items?.tables[selectedTable] ?? {
    header_bg: draft.color.surface_alt, header_fg: draft.color.ink,
    border: draft.table.border, font_size_pt: Number((draft.fonts.base_pt * 0.86).toFixed(1)),
    cell_padding_em: 0.45, rule_weight_pt: draft.table.rule_weight_pt,
    font_family: draft.fonts.body, width_percent: 100,
  }) : null;
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

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="font-medium">Appearance</div>
        <span className="text-[0.75rem] text-muted">Drag the left edge to resize. Changes apply to HTML, PDF, and figures.</span>
      </div>
      <label className="mb-3 flex flex-col gap-1 text-[0.75rem]">
        <span>Customise</span>
        <select value={selected} onChange={(e) => setSelected(e.target.value)} className="w-full rounded border border-border bg-surface px-2 py-1.5">
          <option value="report">Entire report</option>
          {data?.available.figures.map((item) => <option key={item.id} value={item.id}>Figure {item.id.slice(1)}: {item.label}</option>)}
          {data?.available.tables.map((item) => <option key={item.id} value={item.id}>Table {item.id.slice(1)}: {item.label}</option>)}
        </select>
      </label>
      <div className="mb-3 flex flex-wrap gap-2">
        {selected === "report"
          ? <button onClick={onReset} disabled={busy || !data?.custom} className="rounded border border-border px-2.5 py-1 text-[0.75rem] disabled:opacity-40">Reset report</button>
          : <button onClick={clearItem} disabled={busy || !(selectedFigure ? draft.items.figures[selectedFigure] : draft.items.tables[selectedTable!])} className="rounded border border-border px-2.5 py-1 text-[0.75rem] disabled:opacity-40">Reset this item</button>}
        <button onClick={() => onApply(draft)} disabled={busy} className="rounded bg-accent px-3 py-1 text-[0.75rem] text-white disabled:opacity-40">{busy ? "Applying…" : "Apply changes"}</button>
      </div>
      {error && <div className="mb-2 text-[0.75rem] text-bad">{error}</div>}
      {selected === "report" && <div className="grid gap-4">
        <section>
          <h3 className="mb-2 text-[0.6875rem] font-semibold uppercase tracking-wide text-faint">Page palette</h3>
          <div className="grid gap-1.5">
            {COLOURS.map(([label, key]) => <Colour key={key} label={label} value={draft.color[key]} onChange={(value) => changeColor(key, value)} />)}
          </div>
        </section>
        <section>
          <h3 className="mb-2 text-[0.6875rem] font-semibold uppercase tracking-wide text-faint">Charts</h3>
          <div className="mb-3 grid gap-1.5">
            {draft.series.map((value, i) => (
              <Colour key={i} label={`Series ${i + 1}`} value={value} onChange={(colour) => setDraft((current) => {
                if (!current) return current;
                const series = [...current.series]; series[i] = colour;
                return { ...current, series };
              })} />
            ))}
            <Colour label="Grid" value={draft.chart.grid} onChange={(value) => changeChart("grid", value)} />
            <Colour label="Axes" value={draft.chart.axis} onChange={(value) => changeChart("axis", value)} />
          </div>
          <div className="space-y-2">
            <label className="flex items-center justify-between gap-2 text-[0.75rem]">Line style
              <select value={draft.chart.line_style} onChange={(e) => changeChart("line_style", e.target.value)} className="rounded border border-border bg-surface px-2 py-1">
                <option value="solid">Solid</option><option value="dashed">Dashed</option>
                <option value="dotted">Dotted</option><option value="dashdot">Dash and dot</option>
              </select>
            </label>
            <NumberField label="Line width (pt)" value={draft.chart.line_width} min={0.7} max={5} step={0.1} onChange={(value) => changeChart("line_width", value)} />
            <NumberField label="Marker size (pt)" value={draft.chart.marker_size} min={0} max={9} step={0.5} onChange={(value) => changeChart("marker_size", value)} />
            <NumberField label="Bar width" value={draft.chart.bar_width} min={0.25} max={0.9} step={0.05} onChange={(value) => changeChart("bar_width", value)} />
            <NumberField label="Bar corner (px)" value={draft.chart.bar_corner_radius_px} min={0} max={12} step={1} onChange={(value) => changeChart("bar_corner_radius_px", value)} />
            <NumberField label="Chart text scale" value={draft.chart.font_scale} min={0.75} max={1.6} step={0.05} onChange={(value) => changeChart("font_scale", value)} />
            <label className="flex items-center gap-2 text-[0.75rem]"><input type="checkbox" checked={draft.chart.value_labels} onChange={(e) => changeChart("value_labels", e.target.checked)} /> Show value labels</label>
          </div>
        </section>
        <section>
          <h3 className="mb-2 text-[0.6875rem] font-semibold uppercase tracking-wide text-faint">Type and tables</h3>
          <div className="space-y-2">
            {(["heading", "body"] as const).map((key) => (
              <label key={key} className="flex items-center justify-between gap-2 text-[0.75rem]">
                <span className="capitalize">{key} font</span>
                <select value={draft.fonts[key]} onChange={(e) => changeFont(key, e.target.value)} className="max-w-40 rounded border border-border bg-surface px-2 py-1">
                  {FONTS.map((font) => <option key={font}>{font}</option>)}
                </select>
              </label>
            ))}
            <NumberField label="Body size (pt)" value={draft.fonts.base_pt} min={8} max={14} step={0.5} onChange={(value) => changeFont("base_pt", value)} />
            <label className="flex items-center justify-between gap-2 text-[0.75rem]">Heading weight
              <select value={draft.fonts.heading_weight} onChange={(e) => changeFont("heading_weight", Number(e.target.value))} className="rounded border border-border bg-surface px-2 py-1">
                <option value={400}>Regular</option><option value={500}>Medium</option>
                <option value={600}>Semibold</option><option value={700}>Bold</option>
              </select>
            </label>
            <Colour label="Table rules" value={draft.table.border} onChange={(value) => setDraft((current) => current && ({ ...current, table: { ...current.table, border: value } }))} />
            <NumberField label="Table rule (pt)" value={draft.table.rule_weight_pt} min={0.2} max={2} step={0.1} onChange={(value) => setDraft((current) => current && ({ ...current, table: { ...current.table, rule_weight_pt: value } }))} />
          </div>
        </section>
      </div>}
      {figure && <div className="space-y-3">
        <div className="text-[0.75rem] text-muted">These settings affect only Figure {selectedFigure?.slice(1)}.</div>
        {figure.series.map((value, i) => <Colour key={i} label={`Series ${i + 1}`} value={value} onChange={(colour) => {
          const series = [...figure.series]; series[i] = colour; updateFigure("series", series);
        }} />)}
        <Colour label="Background" value={figure.background} onChange={(v) => updateFigure("background", v)} />
        <Colour label="Grid" value={figure.grid} onChange={(v) => updateFigure("grid", v)} />
        <Colour label="Axes" value={figure.axis} onChange={(v) => updateFigure("axis", v)} />
        <label className="flex items-center justify-between gap-2 text-[0.75rem]">Line style
          <select value={figure.line_style} onChange={(e) => updateFigure("line_style", e.target.value)} className="rounded border border-border bg-surface px-2 py-1">
            <option value="solid">Solid</option><option value="dashed">Dashed</option>
            <option value="dotted">Dotted</option><option value="dashdot">Dash and dot</option>
          </select>
        </label>
        <NumberField label="Line width (pt)" value={figure.line_width} min={0.7} max={5} step={0.1} onChange={(v) => updateFigure("line_width", v)} />
        <NumberField label="Marker size (pt)" value={figure.marker_size} min={0} max={9} step={0.5} onChange={(v) => updateFigure("marker_size", v)} />
        <NumberField label="Bar width" value={figure.bar_width} min={0.25} max={0.9} step={0.05} onChange={(v) => updateFigure("bar_width", v)} />
        <NumberField label="Bar corner (px)" value={figure.bar_corner_radius_px} min={0} max={12} step={1} onChange={(v) => updateFigure("bar_corner_radius_px", v)} />
        <NumberField label="Text scale" value={figure.font_scale} min={0.75} max={1.6} step={0.05} onChange={(v) => updateFigure("font_scale", v)} />
        {(["heading_font", "body_font"] as const).map((key) => <label key={key} className="flex items-center justify-between gap-2 text-[0.75rem]">
          <span>{key === "heading_font" ? "Heading font" : "Label font"}</span>
          <select value={figure[key]} onChange={(e) => updateFigure(key, e.target.value)} className="max-w-40 rounded border border-border bg-surface px-2 py-1">
            {FONTS.map((font) => <option key={font}>{font}</option>)}
          </select>
        </label>)}
        <label className="flex items-center gap-2 text-[0.75rem]"><input type="checkbox" checked={figure.value_labels} onChange={(e) => updateFigure("value_labels", e.target.checked)} /> Show value labels</label>
      </div>}
      {table && <div className="space-y-3">
        <div className="text-[0.75rem] text-muted">These settings affect only Table {selectedTable?.slice(1)}.</div>
        <Colour label="Header background" value={table.header_bg} onChange={(v) => updateTable("header_bg", v)} />
        <Colour label="Header text" value={table.header_fg} onChange={(v) => updateTable("header_fg", v)} />
        <Colour label="Rules" value={table.border} onChange={(v) => updateTable("border", v)} />
        <NumberField label="Text size (pt)" value={table.font_size_pt} min={6} max={14} step={0.5} onChange={(v) => updateTable("font_size_pt", v)} />
        <label className="flex items-center justify-between gap-2 text-[0.75rem]">Font
          <select value={table.font_family} onChange={(e) => updateTable("font_family", e.target.value)} className="max-w-40 rounded border border-border bg-surface px-2 py-1">
            {FONTS.map((font) => <option key={font}>{font}</option>)}
          </select>
        </label>
        <NumberField label="Table width (%)" value={table.width_percent} min={50} max={100} step={5} onChange={(v) => updateTable("width_percent", v)} />
        <NumberField label="Cell padding (em)" value={table.cell_padding_em} min={0.15} max={1.2} step={0.05} onChange={(v) => updateTable("cell_padding_em", v)} />
        <NumberField label="Rule width (pt)" value={table.rule_weight_pt} min={0.2} max={2} step={0.1} onChange={(v) => updateTable("rule_weight_pt", v)} />
      </div>}
    </div>
  );
}
