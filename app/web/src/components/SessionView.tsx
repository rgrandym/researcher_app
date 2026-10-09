import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { PanelRight, PanelRightClose, Plus, X } from "lucide-react";
import { api } from "../lib/api";
import { label } from "../lib/format";
import { send } from "../lib/socket";
import type { Activity, SessionDetail } from "../lib/types";
import { useUi } from "../stores/ui";
import ActivityPanel from "./ActivityPanel";
import { attachNote } from "./Home";
import PromptBar, { type Attached, useConnections, useSettings } from "./PromptBar";
import Transcript from "./Transcript";

/** A conversation. `embedded`: inside a project's Chat tab, where the project view supplies
 * the header and the side panel, and `onNew` starts another conversation on the project. */
export default function SessionView({ id, embedded = false, onNew }: { id: string; embedded?: boolean; onNew?: () => void }) {
  const { events, running, errors, activityOpen: activityPref, toggleActivity, loadEvents, setRunning, setError, nextConnection, setNextConnection, setView } = useUi();
  const activityOpen = activityPref;
  const client = useQueryClient();
  const settings = useSettings();
  const connections = useConnections();
  const detail = useQuery({ queryKey: ["session", id], queryFn: () => api.get<SessionDetail>(`/api/sessions/${id}`) });
  const isRunning = running[id] ?? detail.data?.running ?? false;
  const activity = useQuery({
    queryKey: ["activity", id],
    queryFn: () => api.get<Activity>(`/api/sessions/${id}/activity`),
    refetchInterval: isRunning ? 4_000 : false,
    enabled: activityOpen,
  });
  const keep = useMutation({
    mutationFn: () => api.post(`/api/sessions/${id}/keep`),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["session", id] }),
  });
  const bottom = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (detail.data) {
      loadEvents(id, detail.data.events);
      setRunning(id, detail.data.running);
    }
  }, [detail.data, id, loadEvents, setRunning]);

  const list = events[id] ?? [];
  useEffect(() => {
    const el = scroller.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 240) bottom.current?.scrollIntoView({ block: "end" });
  }, [list.length]);

  const segments = detail.data?.segments ?? [];
  const last = segments[segments.length - 1];
  const openSegment = Boolean(last && last.ended === null);
  const connection = nextConnection[id] ?? last?.provider ?? settings.data?.default_connection ?? "claude-sub";

  const onSend = async (text: string, files: Attached[]) => {
    try {
      const note = await attachNote(id, files);
      send({ type: "send", session: id, text: text + note, connection });
      setError(id, "");
    } catch (e) {
      setError(id, (e as Error).message);
    }
  };

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        {embedded && (
          <div className="flex items-center gap-2 border-b border-border px-5 py-1.5 text-[12px] text-faint">
            <span className="min-w-0 flex-1 truncate">
              Conversation about this project
              {segments.length > 0 && ` · ${segments.map((s) => label(s.provider)).join(" → ")}`}
            </span>
            {onNew && (
              <button onClick={onNew} disabled={isRunning} className="flex items-center gap-1 rounded-md border border-border px-2 py-0.5 hover:border-accent disabled:opacity-40" title="Start another conversation on this project">
                <Plus size={12} /> New conversation
              </button>
            )}
            <button onClick={() => setView({ kind: "session", id })} className="underline hover:text-fg" title="Open this conversation full width">
              Open full
            </button>
            <button onClick={toggleActivity} title={activityOpen ? "Collapse the activity panel" : "Show the activity panel: progress and agents"} className={clsx("rounded-md p-1 hover:bg-panel hover:text-fg", activityOpen && "text-accent")}>
              <PanelRight size={15} />
            </button>
          </div>
        )}
        {!embedded && (
        <div className="flex items-center gap-2 border-b border-border px-5 py-2">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14px] font-medium">{detail.data?.title ?? "…"}</div>
            <div className="flex flex-wrap gap-1.5 text-[11.5px] text-faint">
              {segments.map((s, i) => (
                <span key={i}>
                  {i > 0 && "→ "}
                  {label(s.provider)}
                </span>
              ))}
              {(detail.data?.runs ?? []).map((r) => (
                <button key={r} onClick={() => setView({ kind: "run", name: r })} className="rounded bg-panel px-1.5 hover:text-fg">
                  {r}
                </button>
              ))}
            </div>
          </div>
          <button onClick={toggleActivity} title={activityOpen ? "Collapse the activity panel" : "Show the activity panel"} className={clsx("rounded-md p-1.5 hover:bg-panel hover:text-fg", activityOpen ? "text-accent" : "text-faint")}>
            <PanelRight size={16} />
          </button>
        </div>
        )}
        <div ref={scroller} className="scroll-thin min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-6 py-6">
            <Transcript sid={id} events={list} running={isRunning} openSegment={openSegment} connections={connections.data ?? []} />
            {isRunning && <div className="mt-3 h-2 w-2 animate-pulse rounded-full bg-accent" />}
            <div ref={bottom} />
          </div>
        </div>
        <div className="mx-auto w-full max-w-3xl px-6 pb-4">
          {detail.data?.stale && !isRunning && (
            <div className="mb-2 flex items-center gap-2 rounded-lg border border-warn/50 px-3 py-2 text-[12.5px]">
              <span className="flex-1">The workspace configuration changed after this session started. The next message starts a fresh {label(last?.provider)} session with a handoff packet.</span>
              <button onClick={() => keep.mutate()} className="text-[12px] text-muted underline">
                Keep the old session
              </button>
            </div>
          )}
          {errors[id] && (
            <div className="mb-2 flex items-center gap-2 rounded-lg border border-bad/50 px-3 py-2 text-[12.5px] text-bad">
              <span className="flex-1">{errors[id]}</span>
              <button onClick={() => setError(id, "")}>
                <X size={13} />
              </button>
            </div>
          )}
          {last && connection !== last.provider && !isRunning && (
            <div className="mb-1 text-[12px] text-faint">The next message hands this session over to {label(connection)} with a handoff packet.</div>
          )}
          <PromptBar
            onSend={onSend}
            onStop={() => send({ type: "stop", session: id })}
            running={isRunning}
            connection={connection}
            onConnection={(c) => setNextConnection(id, c)}
            contextPercent={activity.data?.cost.context_percent}
            costUsd={activity.data?.cost.total_usd}
            placeholder={embedded ? "Ask about this project, or type / for a command" : "Reply, or type / for a command"}
            autoFocus
          />
        </div>
      </div>
      {activityOpen && (
        <aside className="flex w-[22rem] shrink-0 flex-col border-l border-border bg-panel/50">
          <div className="flex items-center border-b border-border px-4 py-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wide text-faint">Activity</span>
            <button onClick={toggleActivity} title="Collapse the panel" className="ml-auto rounded-md p-1 text-faint hover:bg-panel hover:text-fg">
              <PanelRightClose size={15} />
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <ActivityPanel sid={id} data={activity.data} />
          </div>
        </aside>
      )}
    </div>
  );
}
