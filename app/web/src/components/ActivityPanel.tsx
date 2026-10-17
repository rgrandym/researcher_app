import { useEffect, useState } from "react";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Circle, Globe, LayoutGrid, Rows3 } from "lucide-react";
import { api } from "../lib/api";
import { prefs, setPref } from "../lib/prefs";
import { clock, elapsed, resetLabel, tokens } from "../lib/format";
import type { Activity, AgentRow, AppEvent, Usage, UsageWindow } from "../lib/types";
import { PermissionRequestCard } from "./Transcript";

// ------------------------------------------------------------------ the current task's stepper

// The steps of the task the latest message started (backend/activity.py TASK_STEPS): each
// task begins at its first step, whatever the run already holds. Below it, the run itself.
function Stepper({ data, walker }: { data: Activity; walker: string }) {
  const [details, setDetails] = useState(false);
  const runName = data.task?.run || data.pipeline?.run || data.project || data.progress[0]?.run;
  const run = data.progress.find((p) => p.run === runName) ?? data.progress[0];
  const task = data.task;
  if (!task && !run) return <div className="text-faint">No task yet.</div>;
  const steps = task?.steps ?? [];
  const stages = run ? (run.round ? run.round.stages : run.stages) : [];
  return (
    <div>
      {task && (
        <>
          <div className="flex items-baseline gap-1.5">
            <span className="font-medium text-fg">{task.label}</span>
            <span className={clsx("text-[0.6875rem]", task.running ? "text-accent" : "text-faint")}>
              {task.running ? "in progress" : "finished"} · {clock(task.started)}
            </span>
          </div>
          <div className="truncate text-[0.6875rem] text-faint" title={task.text}>
            {task.text}
          </div>
          <div className="mt-2.5 flex items-start">
            {steps.map((st, i) => {
              const isDone = st.state === "done";
              const isNow = st.state === "current";
              const skipped = st.state === "skipped";
              const before = i > 0 ? steps[i - 1].state : "";
              return (
                <div key={st.label} className="flex flex-1 flex-col items-center">
                  <div className="relative flex w-full items-center">
                    <div className={clsx("h-0.5 flex-1", i === 0 ? "opacity-0" : isDone || isNow || skipped ? (before === "skipped" ? "bg-border" : "bg-good") : "bg-border")} />
                    <div
                      className={clsx(
                        "relative flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 text-[0.625rem] font-semibold",
                        isDone ? "border-good bg-good text-bg" : isNow ? "border-accent text-accent" : skipped ? "border-dashed border-border text-faint" : "border-border text-faint",
                      )}
                      title={skipped ? "Skipped: this task finished without this step" : undefined}
                    >
                      {isDone ? <Check size="0.75rem" strokeWidth={3} /> : skipped ? "–" : i + 1}
                      {isNow && task.running && <span className="absolute -inset-1 animate-ping rounded-full border border-accent opacity-40" />}
                    </div>
                    <div className="relative h-0.5 flex-1 bg-border">
                      {/* The agent walking toward the next step while this one is worked on. */}
                      {isNow && task.running && i < steps.length - 1 && (
                        <span className="walker pointer-events-none absolute -top-[0.7rem] text-[0.875rem] leading-none" aria-hidden>
                          {walker}
                        </span>
                      )}
                    </div>
                  </div>
                  <span className={clsx("mt-1 text-[0.6875rem]", isNow ? "font-medium text-accent" : isDone ? "text-fg" : "text-faint", skipped && "line-through")} title={st.label}>
                    {st.label}
                  </span>
                </div>
              );
            })}
          </div>
        </>
      )}
      {run && (
        <>
          <div className={clsx("flex items-center text-[0.6875rem] text-faint", task ? "mt-3 border-t border-border pt-2" : "")}>
            <span className="min-w-0 truncate" title={run.run}>
              {run.run}
              {run.round && <span className="text-accent"> · expansion {run.round.name}</span>}
              {" · "}
              {run.evidence_rows} evidence rows · {run.round ? `${run.round.notes} notes this round` : `${run.notes} notes`}
            </span>
            <button onClick={() => setDetails(!details)} className="ml-auto shrink-0 pl-2 underline hover:text-fg">
              {details ? "hide stages" : "run stages"}
            </button>
          </div>
          {details && (
            <div className="mt-1 space-y-0.5">
              {stages.map((st) => (
                <div key={st.stage} className="flex items-center gap-1.5" title={st.detail}>
                  {st.ok ? <Check size="0.75rem" className="text-good" /> : <Circle size="0.625rem" className="ml-0.5 mr-0.5 text-faint" />}
                  <span className={st.ok ? "" : "text-faint"}>{st.stage}</span>
                  <span className="ml-auto truncate pl-2 text-[0.6875rem] text-faint">{st.detail}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ agents: cards, swimlanes, list

const KINDS: { match: RegExp; label: string; color: string; emoji: string }[] = [
  { match: /scout/i, label: "Scout", color: "#4f8fd6", emoji: "🔎" },
  { match: /verif/i, label: "Verifier", color: "#3d9a6a", emoji: "🔬" },
  { match: /critic/i, label: "Critic", color: "#c9822b", emoji: "🧐" },
  { match: /writer/i, label: "Writer", color: "#9b6bd1", emoji: "✍️" },
  { match: /explore|plan/i, label: "Explorer", color: "#3aa5a5", emoji: "🧭" },
];

function kind(a: AgentRow) {
  if (a.type === "main") return { label: "Main thread", color: "var(--accent)", emoji: "🤖" };
  return KINDS.find((k) => k.match.test(a.type)) ?? { label: a.type, color: "#7a8394", emoji: "🛠️" };
}

type Mode = "cards" | "lanes";

function useNow(active: boolean): number {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

function StatusDot({ status, color }: { status: string; color: string }) {
  if (status === "running")
    return (
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" style={{ background: color }} />
        <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: color }} />
      </span>
    );
  return <span className={clsx("h-2 w-2 rounded-full", status === "failed" ? "bg-bad" : "bg-good")} />;
}

function Cards({ agents, now, task }: { agents: AgentRow[]; now: number; task: Activity["task"] }) {
  return (
    <div className="space-y-2">
      {agents.map((a) => {
        const k = kind(a);
        const last = a.calls[a.calls.length - 1];
        return (
          <div key={a.id} className={clsx("rounded-lg border bg-surface p-2.5", a.status === "running" ? "border-accent/50 shadow-sm" : "agent-leaving border-border")} style={{ borderLeft: `3px solid ${k.color}` }}>
            <div className="flex items-center gap-1.5">
              <StatusDot status={a.status} color={k.color} />
              <span className="font-medium" style={{ color: k.color }}>
                {k.emoji} {k.label}
              </span>
              <span className={clsx("ml-auto text-[0.6875rem]", a.status === "running" ? "text-accent" : a.status === "failed" ? "text-bad" : "text-faint")}>{a.status}</span>
            </div>
            {a.type !== "main" && <div className="mt-0.5 line-clamp-2 text-[0.7188rem] text-fg">{a.description}</div>}
            <div className="mt-1 flex flex-wrap gap-x-2 text-[0.6875rem] text-faint">
              {a.started && <span>{elapsed(a.started, a.ended ?? now)}</span>}
              <span title={`${a.tokens_in.toLocaleString()} input, ${a.tokens_out.toLocaleString()} output tokens`}>
                {a.tokens_in + a.tokens_out ? `${tokens(a.tokens_in)} in / ${tokens(a.tokens_out)} out` : "tokens pending"}
              </span>
              <span className="flex items-center gap-0.5">
                <Globe size="0.625rem" /> {a.web}
              </span>
              <span>{a.calls_total} action{a.calls_total === 1 ? "" : "s"}</span>
              {a.type === "main" && task?.steps.length ? <span>{task.steps.filter((step) => step.state === "done").length} of {task.steps.length} steps</span> : null}
            </div>
            {last && a.status === "running" && (
              <div className="mt-1 truncate text-[0.6875rem] text-muted" title={last.summary}>
                <span className="text-fg">{last.name}</span> {last.summary}
              </div>
            )}
            {a.status !== "idle" && <ProgressTrack a={a} task={task} thin />}
          </div>
        );
      })}
    </div>
  );
}

// A known task fraction takes priority. With no known total, each action moves the
// track toward its end, as in the job search app.
function progressOf(a: AgentRow, task: Activity["task"]): number {
  if (a.status !== "running") return 1;
  if (a.type === "main") {
    const steps = task?.steps ?? [];
    if (steps.length) {
      const done = steps.filter((s) => s.state === "done" || s.state === "skipped").length;
      return Math.min(0.97, Math.max(0.04, done / steps.length));
    }
  }
  return 0.05 + 0.87 * (1 - Math.exp(-a.calls_total / 12));
}

function ProgressTrack({ a, task, thin }: { a: AgentRow; task: Activity["task"]; thin?: boolean }) {
  const k = kind(a);
  const p = progressOf(a, task);
  const live = a.status === "running";
  return (
    <div className={clsx("relative rounded-full bg-panel", thin ? "mt-2.5 h-1" : "mt-2 h-1.5")}>
      <div
        className={clsx("track-fill absolute left-0 top-0 h-full rounded-full", live && "lane-running")}
        style={{ width: `${p * 100}%`, backgroundColor: a.status === "failed" ? "var(--bad)" : k.color }}
      />
      {/* The agent itself, riding the front of its progress: it moves when the agent works. */}
      <span
        className={clsx("rider pointer-events-none absolute leading-none", thin ? "-top-[0.6rem] text-[0.75rem]" : "-top-[0.65rem] text-[0.875rem]", live && "rider-live")}
        style={{ left: `${p * 100}%` }}
        aria-hidden
      >
        {a.status === "failed" ? "💥" : k.emoji}
      </span>
    </div>
  );
}

const LINGER_S = 5;

function Tracks({ agents, now, task }: { agents: AgentRow[]; now: number; task: Activity["task"] }) {
  if (!agents.length) return null;
  return (
    <div className="space-y-3 pt-1">
      {agents.map((a) => {
        const k = kind(a);
        const end = a.ended ?? now;
        const last = a.calls[a.calls.length - 1];
        return (
          <div key={a.id} className={clsx(a.status !== "running" && "agent-leaving")} title={`${k.label}${a.description && a.type !== "main" ? `: ${a.description}` : ""}`}>
            <div className="flex items-center gap-1.5 text-[0.6875rem]">
              <span style={{ color: k.color }} className="shrink-0 font-medium">
                {k.label}
              </span>
              <span className="min-w-0 flex-1 truncate text-faint">
                {a.type === "main" ? (a.status === "running" && last ? `${last.name} ${last.summary ?? ""}` : "") : a.description}
              </span>
              <span className="shrink-0 tabular-nums text-faint" title={`${a.tokens_in.toLocaleString()} input, ${a.tokens_out.toLocaleString()} output tokens`}>
                {a.tokens_in + a.tokens_out ? `${tokens(a.tokens_in + a.tokens_out)} tokens` : "tokens pending"}
              </span>
              <span className={clsx("shrink-0", a.status === "running" ? "text-accent" : a.status === "failed" ? "text-bad" : "text-faint")}>
                {a.status === "running" ? `${a.calls_total} actions · ${a.started ? elapsed(a.started, end) : ""}` : a.status === "idle" ? "idle" : `${a.status} · ${a.started ? elapsed(a.started, end) : ""}`}
              </span>
            </div>
            <ProgressTrack a={a} task={task} />
          </div>
        );
      })}
    </div>
  );
}

function Agents({ agents, task, earlier }: { agents: AgentRow[]; task: Activity["task"]; earlier: number }) {
  const [mode, setModeState] = useState<Mode>(() => prefs().agents_view);
  const setMode = (m: Mode) => {
    setModeState(m);
    setPref("agents_view", m);
  };
  // Ticks every second while the panel is open: elapsed times, and a finished agent's exit.
  const now = useNow(true);
  const subs = agents.filter((a) => a.type !== "main");
  const main = agents.find((a) => a.type === "main");
  // The current fan-out: everything still running, and the most recent finished ones.
  // Only what is happening: running agents, and the main thread while it works. A finished
  // agent stays a few seconds with its emoji at the right end of the track, then leaves.
  const recent = subs.filter((a) => a.status === "running" || (a.ended !== null && now - a.ended < LINGER_S));
  const shown = [...(main && (main.status === "running" || (main.ended !== null && now - main.ended < LINGER_S)) ? [main] : []), ...recent];
  const counts = { running: subs.filter((a) => a.status === "running").length, done: subs.filter((a) => a.status === "done").length };
  const modes: { id: Mode; icon: React.ReactNode; title: string }[] = [
    { id: "lanes", icon: <Rows3 size="0.75rem" />, title: "Progress tracks" },
    { id: "cards", icon: <LayoutGrid size="0.75rem" />, title: "Cards" },
  ];
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[0.6875rem] text-faint">
          {main?.status === "running" ? "Working" : "Nothing running"}
          {counts.running > 0 ? ` · ${counts.running} agent${counts.running === 1 ? "" : "s"} running` : ""}
          {counts.done > 0 ? ` · ${counts.done} finished` : ""}
          {earlier > 0 ? <span title="Agents of earlier tasks in this conversation"> · {earlier} earlier</span> : null}
        </span>
        <div className="ml-auto flex rounded-md border border-border">
          {modes.map((m) => (
            <button key={m.id} title={m.title} onClick={() => setMode(m.id)} className={clsx("px-1.5 py-1", mode === m.id ? "bg-accent-bg text-accent" : "text-faint hover:text-fg")}>
              {m.icon}
            </button>
          ))}
        </div>
      </div>
      {mode === "cards" && <Cards agents={shown} now={now} task={task} />}
      {mode === "lanes" && <Tracks agents={shown} now={now} task={task} />}
      {!shown.length && <div className="text-[0.75rem] text-faint">No agents at work. They appear here while a task runs.</div>}
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 mt-4 text-[0.6875rem] font-medium uppercase tracking-wide text-faint first:mt-0">{children}</div>;
}

const WINDOW_LABEL: Record<string, string> = { "5h": "Session", "7d": "Week" };

function until(seconds: number): string {
  const minutes = Math.max(0, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
  return `${Math.floor(minutes / 1440)} d ${Math.floor((minutes % 1440) / 60)} h`;
}

function WindowLine({ window, now }: { window: UsageWindow; now: number }) {
  const rejected = window.status === "rejected";
  const exhausted = window.used_percent != null && window.used_percent >= 100;
  const used = window.used_percent;
  const left = used == null ? null : Math.max(0, 100 - used);
  const low = left != null && left <= 15;
  const label = rejected ? (left != null ? `limit reached · ${Math.round(left)}% reported left` : "limit reached") : exhausted ? "No tokens left" : left != null ? `${Math.round(left)}% left` : window.status === "allowed_warning" ? "nearing limit" : "within limit";
  return (
    <div className="flex items-center gap-2 text-[0.6875rem]">
      <span className="w-14 shrink-0 text-faint">{WINDOW_LABEL[window.name] ?? window.name}</span>
      <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-panel" title={used == null ? "The plan has not reported a usage share" : `${Math.round(used)}% used`}>
        <div className={clsx("h-full rounded-full", rejected || exhausted ? "bg-bad" : low ? "bg-warn" : used == null ? "bg-border" : "bg-good")} style={{ width: `${used ?? 100}%` }} />
      </div>
      <span className={clsx("w-44 shrink-0 text-right tabular-nums", rejected || exhausted ? "text-bad" : low ? "text-warn" : "text-faint")}>
        {label}
        {window.resets_at != null && window.resets_at > now && <span title={`Resets ${resetLabel(window.resets_at)}`}> · {until(window.resets_at - now)}</span>}
      </span>
    </div>
  );
}

const PLAN_CONNECTIONS = [
  { id: "claude-sub", label: "Claude" },
  { id: "codex-plan", label: "Codex" },
] as const;

function UsageSummary({ data }: { data: Activity }) {
  const now = useNow(true);
  const segments = data.cost.segments;
  const busy = data.agents.some((agent) => agent.status === "running");
  const plans = useQueries({
    queries: PLAN_CONNECTIONS.map((connection) => ({
      queryKey: ["usage", connection.id],
      queryFn: () => api.get<Usage>(`/api/usage/${connection.id}`),
      refetchInterval: busy ? 10_000 : 60_000,
      retry: false,
    })),
  });
  const input = segments.reduce((sum, segment) => sum + segment.tokens_in, 0);
  const output = segments.reduce((sum, segment) => sum + segment.tokens_out, 0);
  return (
    <div className="space-y-2">
      <div className="text-[0.7188rem]">
        <span className="font-medium">This conversation</span>
        <span className="text-faint"> · {tokens(input)} input / {tokens(output)} output tokens</span>
        {data.cost.context_percent != null && <span className="text-faint"> · context {Math.max(0, Math.round(100 - data.cost.context_percent))}% left</span>}
      </div>
      {PLAN_CONNECTIONS.map((connection, i) => {
        const plan = plans[i];
        return (
          <div key={connection.id} className="space-y-1">
            <div className="flex items-baseline gap-1.5 text-[0.7188rem]">
              <span className="font-medium">{connection.label}</span>
              {plan.data?.updated_at && <span className="text-[0.6875rem] text-faint">last reported {elapsed(plan.data.updated_at, now)} ago</span>}
            </div>
            {plan.isPending && <div className="text-[0.6875rem] text-faint">Reading plan usage…</div>}
            {plan.isError && <div className="text-[0.6875rem] text-bad">Usage unavailable: {(plan.error as Error).message}</div>}
            {plan.data?.windows.map((window) => <WindowLine key={window.name} window={window} now={now} />)}
            {plan.data && !plan.data.windows.length && <div className="text-[0.6875rem] text-faint">{plan.data.note || "Plan allowance unavailable."}</div>}
          </div>
        );
      })}
      {segments.map((segment, i) => (
        <div key={i} className="flex items-center gap-2 rounded-md bg-panel px-2 py-1.5 text-[0.6875rem]">
          <span className="font-medium">{segment.label}{segment.model ? ` · ${segment.model}` : ""}{segment.open ? " · current" : ""}</span>
          <span className="ml-auto tabular-nums text-faint">{tokens(segment.tokens_in)} in / {tokens(segment.tokens_out)} out</span>
        </div>
      ))}
    </div>
  );
}

export default function ActivityPanel({ sid, data, events, openPermissions }: { sid: string; data: Activity | undefined; events: AppEvent[]; openPermissions: string[] }) {
  const client = useQueryClient();
  const raise = useMutation({
    mutationFn: () => api.post(`/api/sessions/${sid}/raise-cap`),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["activity", sid] }),
  });
  const answered = new Set(events.filter((e) => e.type === "permission_answer").map((e) => String(e.data.id)));
  const open = new Set(openPermissions);
  const pending = events.filter((e) => e.type === "permission_request" && open.has(String(e.data.id)) && !answered.has(String(e.data.id)));
  if (!data) return <div className="p-4 text-[0.75rem] text-faint">Loading…</div>;
  const pendingTimes = new Set(pending.map((e) => e.ts));
  const history = data.permissions.filter((p) => !pendingTimes.has(p.ts)).slice(0, 12);
  const capped = data.cost.segments.some((s) => s.open && (s.searches >= s.search_cap || s.fetches >= s.fetch_cap)) || data.cost.notices.length > 0;

  return (
    <div className="scroll-thin h-full overflow-y-auto p-4 text-[0.7812rem]">
      <Heading>Progress</Heading>
      <Stepper data={data} walker={[...data.agents].reverse().map((a) => (a.status === "running" ? kind(a).emoji : "")).find(Boolean) ?? "🤖"} />

      <Heading>Agents</Heading>
      <Agents agents={data.agents} task={data.task} earlier={data.agents_earlier ?? 0} />

      <Heading>Usage</Heading>
      <UsageSummary data={data} />

      <Heading>Permissions</Heading>
      {pending.length > 0 && (
        <div className="mb-2 space-y-2">
          {pending.map((ev) => <PermissionRequestCard key={String(ev.data.id)} ev={ev} sid={sid} running />)}
        </div>
      )}
      {history.length === 0 && pending.length === 0 && <div className="text-faint">No requests yet.</div>}
      {history.length > 0 && pending.length === 0 && <div className="mb-1 text-faint">No approval is currently waiting. Earlier requests are listed below.</div>}
      <div className="space-y-0.5">
        {history.map((p, i) => (
          <div key={i} className="flex items-center gap-1.5" title={p.summary}>
            <span
              className={clsx(
                "w-16 shrink-0 text-[0.6875rem]",
                p.decision === "deny" || p.decision === "blocked" ? "text-bad" : p.decision === "waiting" || p.decision === "unanswered" || p.decision === "withdrawn" ? "text-faint" : "text-good",
              )}
            >
              {p.decision === "waiting" ? "unanswered" : p.decision}
            </span>
            <span className="shrink-0 font-medium">{p.kind === "question" ? "Question" : p.tool}</span>
            <span className="min-w-0 flex-1 truncate text-[0.7188rem] text-muted">{p.summary}</span>
            <span className="shrink-0 text-[0.6562rem] text-faint">{clock(p.ts)}</span>
          </div>
        ))}
      </div>

      <Heading>Search limits</Heading>
      <div className="space-y-1">
        {data.cost.segments.map((s, i) => (
          <div key={i} className="rounded-md bg-panel px-2 py-1.5">
            <div className="flex items-center gap-1 text-[0.6875rem] text-faint">
              <Globe size="0.6875rem" /> {s.label}: {s.searches}/{s.search_cap} searches · {s.fetches}/{s.fetch_cap} fetches
            </div>
          </div>
        ))}
        {data.cost.notices.map((n, i) => (
          <div key={i} className="text-[0.7188rem] text-warn">
            {n.text}
          </div>
        ))}
        {capped && (
          <button onClick={() => raise.mutate()} className="mt-1 rounded-md border border-border px-2 py-1 text-[0.75rem] hover:border-accent">
            Raise cap
          </button>
        )}
        {raise.isError && <div className="text-[0.6875rem] text-bad">{(raise.error as Error).message}</div>}
      </div>
    </div>
  );
}
