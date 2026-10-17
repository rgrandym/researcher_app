import { useEffect, useRef } from "react";
import { basicSetup } from "codemirror";
import { markdown } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
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

const editorTheme = EditorView.theme({
  "&": {
    height: "100%",
    backgroundColor: "var(--bg)",
    color: "var(--text-primary)",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "0.8125rem",
  },
  ".cm-scroller": { overflow: "auto", fontFamily: "inherit" },
  ".cm-content": { padding: "1.25rem", caretColor: "var(--text-primary)" },
  ".cm-line": { lineHeight: "1.5rem" },
  ".cm-gutters": {
    backgroundColor: "var(--bg)",
    color: "var(--text-muted)",
    borderRight: "1px solid var(--border)",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "var(--bg-panel)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "var(--accent-bg) !important",
  },
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
        syntaxHighlighting(highlighting),
        EditorView.lineWrapping,
        EditorView.contentAttributes.of({ spellcheck: "true" }),
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
