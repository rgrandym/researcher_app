import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { prefs, setPref } from "../lib/prefs";

// A side panel the author can drag to resize and collapse.
//
// Its width is a share of the window, held between `min` pixels and `max` (a share and a
// pixel cap), so moving the window from a large monitor to a laptop shrinks every panel in
// proportion. The middle column beside a panel holds at least CENTER_MIN of their shared
// container (its class below): when panels would take more, they shrink together down to
// their `min`, so the middle is never squeezed whatever widths were dragged. Dragging the inner edge sets the share, which
// is remembered; a double-click on the edge returns it to the default. Below `overlayBelow`
// pixels of window, an open panel floats over the content instead of squeezing it.

export interface PanelSize {
  id: string;
  share: number; // default share of the window's width
  min: number; // pixels at the 16px base size; scaled with it (index.css, html font-size)
  max: number; // share of the window's width
  maxPx: number; // and never wider than this, at the 16px base size
}

export const PANELS = {
  sidebar: { id: "sidebar", share: 0.16, min: 190, max: 0.2, maxPx: 340 },
  activity: { id: "activity", share: 0.22, min: 260, max: 0.26, maxPx: 500 },
  runPanel: { id: "runPanel", share: 0.18, min: 200, max: 0.24, maxPx: 400 },
  figures: { id: "figures", share: 0.15, min: 170, max: 0.22, maxPx: 360 },
  appearance: { id: "appearance", share: 0.26, min: 280, max: 0.34, maxPx: 600 },
  nav: { id: "nav", share: 0.15, min: 180, max: 0.2, maxPx: 320 },
} satisfies Record<string, PanelSize>;

// The middle column's class, next to any Panel: it keeps at least 62% of the container.
export const CENTER = "min-w-[62%] flex-1";

// The interface's base size relative to 16px: html's font-size follows the window's width.
const baseScale = () => (parseFloat(getComputedStyle(document.documentElement).fontSize) || 16) / 16;

export function useViewportWidth(): { vw: number; scale: number } {
  const read = () => ({ vw: window.innerWidth, scale: baseScale() });
  const [view, setView] = useState(read);
  useEffect(() => {
    const onResize = () => setView(read());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return view;
}

const clampWidth = (size: PanelSize, share: number, vw: number, scale: number) =>
  Math.round(Math.max(size.min * scale, Math.min(share * vw, size.max * vw, size.maxPx * scale)));

export default function Panel({
  size,
  side,
  overlayBelow = 0,
  onClose,
  className,
  children,
}: {
  size: PanelSize;
  side: "left" | "right";
  overlayBelow?: number;
  onClose?: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  const { vw, scale } = useViewportWidth();
  const [share, setShare] = useState(() => prefs().panel_widths?.[size.id] ?? size.share);
  const [dragging, setDragging] = useState(false);
  const start = useRef<{ x: number; width: number } | null>(null);
  const width = clampWidth(size, share, vw, scale);
  // Float over the content only when the window is genuinely narrow, measured in base-size
  // units, so a zoomed window and a small one are judged alike.
  const overlay = vw < overlayBelow * scale;

  const save = (next: number) => setPref("panel_widths", { ...(prefs().panel_widths ?? {}), [size.id]: next });

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    start.current = { x: e.clientX, width };
    setDragging(true);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!start.current) return;
    const dx = e.clientX - start.current.x;
    const next = start.current.width + (side === "left" ? dx : -dx);
    setShare(clampWidth(size, next / vw, vw, scale) / vw);
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (!start.current) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    start.current = null;
    setDragging(false);
    save(share);
  };
  const reset = () => {
    setShare(size.share);
    save(size.share);
  };

  return (
    <>
      {/* A visible backdrop: it takes the clicks and the scroll while the panel floats, so it
          must look like it, and a click on it closes the panel. */}
      {overlay && onClose && <div className="absolute inset-0 z-20 bg-black/45 backdrop-blur-[1px]" onClick={onClose} title="Close the panel" />}
      <aside
        // A basis, not a fixed width: beside a CENTER column the panel gives way, down to `min`.
        style={overlay ? { width } : { flexBasis: width, minWidth: Math.min(size.min * scale, width) }}
        className={clsx(
          "relative flex shrink flex-col",
          side === "left" ? "border-r" : "border-l",
          "border-border",
          dragging && "select-none",
          className,
          // Floating over the content: opaque, whatever the panel's own tint.
          overlay && clsx("absolute bottom-0 top-0 z-30 !bg-panel shadow-xl", side === "left" ? "left-0" : "right-0"),
        )}
      >
        {children}
        <div
          role="separator"
          aria-orientation="vertical"
          title="Drag to resize · double-click to reset"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onDoubleClick={reset}
          className={clsx(
            "absolute bottom-0 top-0 z-10 w-1.5 cursor-col-resize transition-colors hover:bg-accent/40",
            side === "left" ? "-right-[3px]" : "-left-[3px]",
            dragging && "bg-accent/60",
          )}
        />
      </aside>
    </>
  );
}
