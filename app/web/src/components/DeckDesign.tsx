import { useEffect, useState } from "react";
import type { Box, Content, DeckTheme, OfficeData, Shape, TextStyle } from "./OfficePane";

/** The box picked on the rendered deck: the slide's position in the deck and the shape's key. */
export interface DeckSelection { slide: number; shape: string }

const THEME_NAMES: [string, string][] = [
  ["dk1", "Text dark"], ["lt1", "Background light"], ["dk2", "Dark 2"], ["lt2", "Light 2"],
  ["accent1", "Accent 1"], ["accent2", "Accent 2"], ["accent3", "Accent 3"], ["accent4", "Accent 4"],
  ["accent5", "Accent 5"], ["accent6", "Accent 6"], ["hlink", "Link"], ["folHlink", "Visited link"],
];
const control = "rounded border border-border bg-bg px-1.5 py-0.5 text-[0.75rem]";
const action = `${control} hover:border-accent disabled:opacity-40`;

/** A value typed into a field is committed on Enter or when the field loses focus. */
function Field({ label, value, onCommit, type = "text", list, width = "w-full" }: {
  label: string; value: string; onCommit: (value: string) => void; type?: string; list?: string; width?: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return <label className="flex items-center justify-between gap-2">
    <span className="text-muted">{label}</span>
    <input aria-label={label} type={type} list={list} value={draft} step="any" className={`${control} ${width}`}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => { if (draft !== value) onCommit(draft); }}
      onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
  </label>;
}

/** A colour picked with the system picker, committed when the picker closes. */
function Colour({ label, value, onCommit }: { label: string; value?: string; onCommit: (hex: string) => void }) {
  const [draft, setDraft] = useState(`#${value ?? "000000"}`);
  useEffect(() => setDraft(`#${value ?? "000000"}`), [value]);
  return <label className="flex items-center justify-between gap-2">
    <span className="text-muted">{label}</span>
    <span className="flex items-center gap-1">
      <span className="font-mono text-[0.6875rem] text-faint">{value ? draft.slice(1).toUpperCase() : "inherited"}</span>
      <input aria-label={label} type="color" value={draft} className="h-6 w-8 cursor-pointer rounded border border-border bg-bg"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { const hex = draft.slice(1).toUpperCase(); if (hex !== value) onCommit(hex); }} />
    </span>
  </label>;
}

export default function DeckDesign({ content, selection, onApply, pending, error }: {
  content?: Content; selection: DeckSelection | null; onApply: (change: (data: OfficeData) => OfficeData) => void; pending: boolean; error: string;
}) {
  const [fromColour, setFromColour] = useState("");
  const [toColour, setToColour] = useState("#000000");
  const [fromFont, setFromFont] = useState("");
  const [toFont, setToFont] = useState("");
  if (!content) return <div className="p-4 text-[0.75rem] text-faint">Loading the deck…</div>;
  const data = content.data;
  const slide = selection ? data.slides?.[selection.slide] : undefined;
  const shape = slide?.shapes.find((s) => s.id === selection?.shape);
  const palette = content.palette ?? { colors: [], fonts: [] };
  const theme: DeckTheme = data.theme ?? {};

  const setShape = (next: Shape) => onApply((d) => ({
    ...d, slides: d.slides!.map((s) => s.id === slide!.id ? { ...s, shapes: s.shapes.map((sh) => sh.id === next.id ? next : sh) } : s),
  }));
  const setBox = (key: keyof Box, value: string) => {
    if (!shape?.box || !Number.isFinite(Number(value))) return;
    setShape({ ...shape, box: { ...shape.box, [key]: Math.round(Number(value) * 100) / 100 } });
  };
  const setStyle = (patch: TextStyle) => { if (shape?.kind === "text") setShape({ ...shape, style: { ...shape.style, ...patch } }); };
  const setTheme = (patch: DeckTheme) => onApply((d) => ({ ...d, theme: { ...d.theme, ...patch } }));
  const style = shape?.kind === "text" ? shape.style ?? {} : undefined;

  return <div className="scroll-thin h-full space-y-4 overflow-y-auto p-3 text-[0.75rem]">
    <datalist id="deck-fonts">{[...new Set([...palette.fonts, theme.fonts?.major, theme.fonts?.minor].filter(Boolean))].map((f) => <option key={f} value={f} />)}</datalist>
    {error && <p role="alert" className="text-bad">{error}</p>}
    {pending && <p className="text-faint">Saving… the slide pictures redraw shortly after.</p>}

    <section className="space-y-1.5">
      <h3 className="font-semibold">Selected box</h3>
      {!selection && <p className="text-muted">Click a box on a slide to select it. Drag to move it, drag its corner to resize it, and use the arrow keys to nudge it (Shift moves 10 pt).</p>}
      {selection && !shape && <p className="text-muted">This box was added in the editor and has no saved position yet. Export the deck, then open the new version to arrange it.</p>}
      {shape && <>
        <p className="text-muted">Slide {selection!.slide + 1} · {shape.kind === "object" ? shape.name : shape.kind === "table" ? "Table" : `Text: “${shape.paragraphs.join(" ").slice(0, 40)}”`}</p>
        {shape.box ? <div className="grid grid-cols-2 gap-1.5">
          {(["x", "y", "w", "h"] as const).map((k) => <Field key={k} label={{ x: "Left", y: "Top", w: "Width", h: "Height" }[k] + " (pt)"} type="number" width="w-20" value={String(shape.box![k])} onCommit={(v) => setBox(k, v)} />)}
        </div> : <p className="text-muted">This box sits inside a group; move the group instead.</p>}
        {style && <div className="space-y-1.5 border-t border-border pt-2">
          <Field label="Font" list="deck-fonts" value={style.font ?? ""} onCommit={(v) => v.trim() && setStyle({ font: v.trim() })} />
          <Field label="Size (pt)" type="number" width="w-20" value={style.size !== undefined ? String(style.size) : ""} onCommit={(v) => Number(v) >= 1 && Number(v) <= 400 && setStyle({ size: Number(v) })} />
          <Colour label="Text colour" value={style.color} onCommit={(color) => setStyle({ color })} />
          <Colour label="Fill" value={style.fill} onCommit={(fill) => setStyle({ fill })} />
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1"><input type="checkbox" checked={Boolean(style.bold)} onChange={(e) => setStyle({ bold: e.target.checked })} /> Bold</label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={Boolean(style.italic)} onChange={(e) => setStyle({ italic: e.target.checked })} /> Italic</label>
            <select aria-label="Alignment" value={style.align ?? ""} onChange={(e) => e.target.value && setStyle({ align: e.target.value as TextStyle["align"] })} className={control}>
              <option value="" disabled>Alignment</option>
              {["left", "center", "right", "justify"].map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          {palette.colors.length > 0 && <div>
            <span className="text-muted">Deck colours (click for text colour)</span>
            <div className="mt-1 flex flex-wrap gap-1">{palette.colors.map((c) => <button key={c} title={c} aria-label={`Text colour ${c}`} onClick={() => setStyle({ color: c })} className="h-5 w-5 rounded border border-border" style={{ background: `#${c}` }} />)}</div>
          </div>}
        </div>}
      </>}
    </section>

    <section className="space-y-1.5 border-t border-border pt-3">
      <h3 className="font-semibold">Deck theme</h3>
      <p className="text-muted">The colours and fonts slides take when a box does not set its own.</p>
      <Field label="Heading font" list="deck-fonts" value={theme.fonts?.major ?? ""} onCommit={(v) => v.trim() && setTheme({ fonts: { ...theme.fonts, major: v.trim() } })} />
      <Field label="Body font" list="deck-fonts" value={theme.fonts?.minor ?? ""} onCommit={(v) => v.trim() && setTheme({ fonts: { ...theme.fonts, minor: v.trim() } })} />
      {THEME_NAMES.filter(([k]) => theme.colors?.[k]).map(([k, name]) => <Colour key={k} label={name} value={theme.colors![k]} onCommit={(hex) => setTheme({ colors: { ...theme.colors, [k]: hex } })} />)}
    </section>

    <section className="space-y-1.5 border-t border-border pt-3">
      <h3 className="font-semibold">Replace across the deck</h3>
      <p className="text-muted">Most decks set colours and fonts box by box. A replacement changes every box that uses the old value.</p>
      <div className="flex flex-wrap gap-1">{palette.colors.map((c) => <button key={c} title={c} aria-label={`Replace ${c}`} onClick={() => { setFromColour(c); setToColour(`#${c}`); }} className={`h-5 w-5 rounded border ${fromColour === c ? "border-accent ring-2 ring-accent" : "border-border"}`} style={{ background: `#${c}` }} />)}</div>
      {fromColour && <div className="flex items-center gap-2">
        <span className="font-mono">{fromColour}</span>→
        <input aria-label="Replacement colour" type="color" value={toColour} onChange={(e) => setToColour(e.target.value)} className="h-6 w-8 rounded border border-border bg-bg" />
        <button className={action} onClick={() => { setTheme({ swap_colors: { ...theme.swap_colors, [fromColour]: toColour.slice(1).toUpperCase() } }); setFromColour(""); }}>Replace</button>
      </div>}
      <div className="flex flex-wrap items-center gap-1.5">
        <select aria-label="Font to replace" value={fromFont} onChange={(e) => setFromFont(e.target.value)} className={control}>
          <option value="">Font…</option>
          {palette.fonts.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>→
        <input aria-label="Replacement font" list="deck-fonts" value={toFont} onChange={(e) => setToFont(e.target.value)} placeholder="New font" className={`${control} w-28`} />
        <button className={action} disabled={!fromFont || !toFont.trim()} onClick={() => { setTheme({ swap_fonts: { ...theme.swap_fonts, [fromFont]: toFont.trim() } }); setFromFont(""); setToFont(""); }}>Replace</button>
      </div>
      {[...Object.entries(theme.swap_colors ?? {}).map(([a, b]) => ["swap_colors", a, b, true] as const), ...Object.entries(theme.swap_fonts ?? {}).map(([a, b]) => ["swap_fonts", a, b, false] as const)].map(([key, a, b, isColour]) =>
        <div key={key + a} className="flex items-center gap-2">
          {isColour ? <><span className="h-4 w-4 rounded border border-border" style={{ background: `#${a}` }} />→<span className="h-4 w-4 rounded border border-border" style={{ background: `#${b}` }} /></> : <span>{a} → {b}</span>}
          <button className="text-faint hover:text-bad" onClick={() => { const rest = { ...theme[key] }; delete rest[a]; setTheme({ [key]: rest }); }}>Undo</button>
        </div>)}
    </section>
  </div>;
}
