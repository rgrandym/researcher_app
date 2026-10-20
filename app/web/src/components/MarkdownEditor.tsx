import { useEffect, useRef } from "react";
import { basicSetup } from "codemirror";
import { markdown } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
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
});

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSave?: () => void;
  onScroll?: (top: number) => void;
  initialScrollTop?: number;
}

export default function MarkdownEditor({ value, onChange, onSave, onScroll, initialScrollTop }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const callbacks = useRef({ onChange, onSave, onScroll });
  const restored = useRef(false);
  callbacks.current = { onChange, onSave, onScroll };

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
    if (restored.current || !value || !view.current) return;
    restored.current = true;
    if (initialScrollTop) view.current.scrollDOM.scrollTop = initialScrollTop;
  }, [value, initialScrollTop]);

  return <div ref={host} className="h-full min-h-0 w-full overflow-hidden" />;
}
