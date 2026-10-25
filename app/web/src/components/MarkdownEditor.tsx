import { useEffect, useRef } from "react";
import { basicSetup } from "codemirror";
import { markdown } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, type DecorationSet } from "@codemirror/view";
import { linter, lintGutter, type Diagnostic } from "@codemirror/lint";
import { tags } from "@lezer/highlight";

const highlighting = HighlightStyle.define([
  { tag: tags.heading, color: "var(--accent)", fontWeight: "700" },
  { tag: tags.strong, color: "var(--text-primary)", fontWeight: "700" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: tags.link, color: "var(--accent)", textDecoration: "underline" },
  { tag: tags.url, color: "var(--text-muted)" },
  { tag: tags.monospace, color: "var(--good)" },
  { tag: tags.quote, color: "var(--text-secondary)" },
  { tag: tags.meta, color: "var(--text-muted)" },
]);

function markdownDiagnostics(view: EditorView): Diagnostic[] {
  const diagnostics: Diagnostic[] = [];
  let fence: { from: number; marker: string } | null = null;
  for (let n = 1; n <= view.state.doc.lines; n++) {
    const line = view.state.doc.line(n);
    const trimmed = line.text.trimStart();
    const marker = trimmed.match(/^(`{3,}|~{3,})/);
    if (marker) {
      if (!fence) fence = { from: line.from + line.text.indexOf(marker[0]), marker: marker[0] };
      else if (marker[0][0] === fence.marker[0] && marker[0].length >= fence.marker.length) fence = null;
      continue;
    }
    if (fence) continue;
    const repeated = /\b([A-Za-z]{2,})\s+\1\b/giu.exec(line.text);
    if (repeated) {
      const second = line.from + repeated.index + repeated[0].length - repeated[1].length;
      diagnostics.push({
        from: second,
        to: second + repeated[1].length,
        severity: "warning",
        message: "Repeated word. Remove it if this was accidental.",
        actions: [{ name: "Remove repeated word", apply: (v) => v.dispatch({ changes: { from: line.from + repeated.index + repeated[1].length, to: second + repeated[1].length } }) }],
      });
    }
    const brokenLink = /\[[^\]]+\]\(([^)]*)$/u.exec(line.text);
    if (brokenLink) diagnostics.push({
      from: line.from + brokenLink.index,
      to: line.to,
      severity: "error",
      message: "This Markdown link is missing a closing parenthesis.",
      actions: [{ name: "Add )", apply: (v) => v.dispatch({ changes: { from: line.to, insert: ")" } }) }],
    });
  }
  if (fence) diagnostics.push({
    from: fence.from,
    to: fence.from + fence.marker.length,
    severity: "error",
    message: "This code fence has no closing fence.",
    actions: [{ name: "Close fence", apply: (v) => v.dispatch({ changes: { from: v.state.doc.length, insert: `\n${fence!.marker}\n` } }) }],
  });
  return diagnostics;
}

/** A commented passage, highlighted in the text. */
export interface EditorMark {
  id: string;
  from: number;
  to: number;
  title: string;
  active: boolean;
  tone?: string; // a highlight's colour; comments have none
}

// The highlights move with the text as it is edited; a new set replaces them.
const setMarks = StateEffect.define<EditorMark[]>();
const marksField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(marks, tr) {
    marks = marks.map(tr.changes);
    for (const effect of tr.effects) {
      if (!effect.is(setMarks)) continue;
      const length = tr.state.doc.length;
      marks = Decoration.set(
        effect.value
          .filter((m) => m.from < m.to && m.to <= length)
          .map((m) => Decoration.mark({
            class: [m.tone ? `cm-hl cm-hl-${m.tone}` : "cm-comment", m.active ? "cm-comment-active" : ""].join(" ").trim(),
            attributes: { "data-cid": m.id, title: m.title },
          }).range(m.from, m.to)),
        true,
      );
    }
    return marks;
  },
  provide: (field) => EditorView.decorations.from(field),
});

const editorTheme = EditorView.theme({
  "&": {
    height: "100%",
    backgroundColor: "var(--bg)",
    color: "var(--text-primary)",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "0.8125rem",
  },
  ".cm-scroller": { overflow: "auto", fontFamily: "inherit" },
  ".cm-content": { padding: "1.25rem", caretColor: "var(--editor-caret)" },
  ".cm-cursor, .cm-dropCursor": {
    borderLeftColor: "var(--editor-caret) !important",
    borderLeftWidth: "2px",
  },
  ".cm-line": { lineHeight: "1.5rem" },
  ".cm-gutters": {
    backgroundColor: "var(--bg)",
    color: "var(--text-muted)",
    borderRight: "1px solid var(--border)",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "var(--bg-panel)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "var(--editor-selection) !important",
  },
  ".cm-content ::selection, &.cm-focused .cm-content ::selection": {
    backgroundColor: "var(--editor-selection) !important",
  },
  ".cm-lintRange-error": { textDecoration: "underline wavy var(--bad)" },
  ".cm-comment": { backgroundColor: "rgba(255, 212, 59, 0.28)", borderBottom: "2px solid rgba(214, 160, 0, 0.75)", cursor: "pointer" },
  ".cm-hl": { cursor: "pointer", borderRadius: "2px" },
  ".cm-hl-yellow": { backgroundColor: "rgba(255, 230, 80, 0.45)" },
  ".cm-hl-green": { backgroundColor: "rgba(110, 210, 100, 0.35)" },
  ".cm-hl-blue": { backgroundColor: "rgba(90, 160, 255, 0.3)" },
  ".cm-hl-pink": { backgroundColor: "rgba(255, 110, 170, 0.3)" },
  ".cm-comment-active": { backgroundColor: "rgba(255, 196, 0, 0.55)", outline: "1px solid rgba(214, 160, 0, 0.9)" },
});

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSave?: () => void;
  onScroll?: (top: number) => void;
  initialScrollTop?: number;
  marks?: EditorMark[];
  onMarkClick?: (id: string) => void;
  // Select this range and scroll it to the middle; a new `key` repeats it.
  focus?: { from: number; to: number; key: number } | null;
}

export default function MarkdownEditor({ value, onChange, onSave, onScroll, initialScrollTop, marks, onMarkClick, focus }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const callbacks = useRef({ onChange, onSave, onScroll, onMarkClick });
  const restored = useRef(false);
  callbacks.current = { onChange, onSave, onScroll, onMarkClick };

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      doc: value,
      parent: host.current,
      extensions: [
        basicSetup,
        markdown(),
        linter(markdownDiagnostics, { delay: 400 }),
        lintGutter(),
        syntaxHighlighting(highlighting),
        EditorView.lineWrapping,
        marksField,
        EditorView.contentAttributes.of({ spellcheck: "true", lang: "en-GB", autocorrect: "on" }),
        editorTheme,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) callbacks.current.onChange(update.state.doc.toString());
        }),
        EditorView.domEventHandlers({
          keydown: (event) => {
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
              event.preventDefault();
              callbacks.current.onSave?.();
              return true;
            }
            return false;
          },
          click: (event) => {
            const mark = (event.target as HTMLElement | null)?.closest?.("[data-cid]");
            if (mark) callbacks.current.onMarkClick?.(mark.getAttribute("data-cid") ?? "");
            return false;
          },
        }),
      ],
    });
    const saveScroll = () => callbacks.current.onScroll?.(editor.scrollDOM.scrollTop);
    editor.scrollDOM.addEventListener("scroll", saveScroll);
    view.current = editor;
    return () => {
      editor.scrollDOM.removeEventListener("scroll", saveScroll);
      editor.destroy();
      view.current = null;
    };
    // The editor is created once; prop changes are synced below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const editor = view.current;
    if (!editor || editor.state.doc.toString() === value) return;
    editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
  }, [value]);

  useEffect(() => {
    view.current?.dispatch({ effects: setMarks.of(marks ?? []) });
  }, [marks]);

  useEffect(() => {
    const editor = view.current;
    if (!editor || !focus) return;
    const to = Math.min(focus.to, editor.state.doc.length);
    const from = Math.min(focus.from, to);
    editor.dispatch({ selection: { anchor: from, head: to }, effects: EditorView.scrollIntoView(from, { y: "center" }) });
    editor.focus();
  }, [focus]);

  useEffect(() => {
    if (restored.current || !value || !view.current) return;
    restored.current = true;
    if (initialScrollTop) view.current.scrollDOM.scrollTop = initialScrollTop;
  }, [value, initialScrollTop]);

  return <div ref={host} className="h-full min-h-0 w-full overflow-hidden" />;
}
