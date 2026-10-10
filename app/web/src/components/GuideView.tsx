import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import Markdown, { slug } from "./Markdown";
import Panel, { CENTER, PANELS } from "./Panel";

export default function GuideView() {
  // Read on every open, so edits to USERGUIDE.md show without a rebuild.
  const guide = useQuery({ queryKey: ["guide"], queryFn: () => api.get<string>("/api/guide"), staleTime: 0 });
  const text = guide.data ?? "";
  const headings = [...text.replace(/```[\s\S]*?```/g, "").matchAll(/^(#{1,3})\s+(.+)$/gm)].map((m) => ({ level: m[1].length, title: m[2].replace(/[*`]/g, "").trim() }));

  return (
    <div className="flex h-full">
      <Panel size={PANELS.nav} side="left">
      <nav className="scroll-thin min-h-0 flex-1 overflow-y-auto p-4 text-[0.7812rem]">
        <div className="mb-2 text-[0.6875rem] font-medium uppercase tracking-wide text-faint">Contents</div>
        {headings.map((h, i) => (
          <button
            key={i}
            onClick={() => document.getElementById(slug(h.title))?.scrollIntoView({ behavior: "smooth" })}
            className="block w-full truncate rounded px-1.5 py-0.5 text-left text-muted hover:bg-panel hover:text-fg"
            style={{ paddingLeft: `${(h.level - 1) * 12 + 6}px` }}
          >
            {h.title}
          </button>
        ))}
      </nav>
      </Panel>
      <div className={`scroll-thin overflow-y-auto ${CENTER}`}>
        <div className="mx-auto max-w-3xl px-8 py-6">
          {guide.isLoading ? <div className="text-faint">Loading…</div> : <Markdown text={text} />}
        </div>
      </div>
    </div>
  );
}
