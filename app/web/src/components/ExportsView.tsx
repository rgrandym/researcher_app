import { useQuery } from "@tanstack/react-query";
import { FileText, FolderSearch } from "lucide-react";
import { api } from "../lib/api";
import { bytes, day } from "../lib/format";
import type { ExportFile } from "../lib/types";

export default function ExportsView() {
  const exports = useQuery({ queryKey: ["exports"], queryFn: () => api.get<ExportFile[]>("/api/exports") });
  const groups = new Map<string, Map<string, ExportFile[]>>();
  for (const e of exports.data ?? []) {
    const run = groups.get(e.run) ?? new Map<string, ExportFile[]>();
    run.set(e.style, [...(run.get(e.style) ?? []), e]);
    groups.set(e.run, run);
  }
  const runs = [...groups.keys()].sort().reverse();

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-8 py-6">
        <h1 className="mb-1 text-[18px] font-medium">Exports</h1>
        <p className="mb-5 text-[13px] text-muted">Files under each run's export folder. Click one to open it in its own app.</p>
        {exports.isLoading && <div className="text-faint">Loading…</div>}
        {runs.length === 0 && !exports.isLoading && <div className="text-[13px] text-faint">No exports yet. Ask for one with /export.</div>}
        {runs.map((run) => (
          <div key={run} className="mb-6">
            <div className="mb-2 text-[13px] font-medium">{run}</div>
            {[...groups.get(run)!.entries()].map(([style, files]) => (
              <div key={style} className="mb-2 ml-1">
                {style && <div className="mb-1 text-[11.5px] uppercase tracking-wide text-faint">{style}</div>}
                {files.map((f) => (
                  <div key={f.path} className="group flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-panel">
                    <FileText size={14} className="text-faint" />
                    <button onClick={() => void api.post("/api/exports/open", { path: f.path })} className="min-w-0 flex-1 truncate text-left text-[13px]">
                      {f.name}
                    </button>
                    <span className="text-[11px] text-faint">
                      {bytes(f.size)} · {day(f.mtime)}
                    </span>
                    <button title="Show in Finder" onClick={() => void api.post("/api/exports/reveal", { path: f.path })} className="text-faint opacity-0 hover:text-fg group-hover:opacity-100">
                      <FolderSearch size={14} />
                    </button>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
