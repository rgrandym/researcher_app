import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bot, Check, Circle, Globe, LayoutGrid, List, Rows3 } from "lucide-react";
import { api } from "../lib/api";
import { prefs, setPref } from "../lib/prefs";
import { clock, elapsed, resetLabel, tokens } from "../lib/format";
import type { Activity, AgentRow, Stage } from "../lib/types";

// ------------------------------------------------------------------ pipeline stepper

const STEPS: { id: string; label: string; done: (ok: (k: string) => boolean) => boolean }[] = [
  { id: "gather", label: "Gather", done: (ok) => ok("brief") && ok("voice") && ok("coverage") && ok("evidence") },
  { id: "draft", label: "Draft", done: (ok) => ok("report") || ok("verify") || ok("critique") },
  { id: "review", label: "Review", done: (ok) => ok("verify") && ok("critique") },
  { id: "finish", label: "Finish", done: (ok) => ok("repair") && ok("report") },
];

function Stepper({ data }: { data: Activity }) {
  const [details, setDetails] = useState(false);
  const runName = data.pipeline?.run || data.project || data.progress[0]?.run;
  const run = data.progress.find((p) => p.run === runName) ?? data.progress[0];
  if (!run) return <div className="text-faint">No run folder yet.</div>;
  const ok = (k: string) => Boolean(run.stages.find((s: Stage) => s.stage === k)?.ok);
  const done = STEPS.map((st) => st.done(ok));
  const live = data.pipeline && data.pipeline.run === run.run ? STEPS.findIndex((st) => st.id === data.pipeline?.stage) : -1;
  const current = live >= 0 ? live : done.indexOf(false);
  return (
    <div>
      <div className="truncate text-[11.5px] text-muted" title={run.run}>
        {run.run}
      </div>
      <div className="mt-2 flex items-start">
        {STEPS.map((st, i) => {
          const isDone = done[i] && i !== live;
          const isNow = i === current;
          return (
            <div key={st.id} className="flex flex-1 flex-col items-center">
              <div className="flex w-full items-center">
                <div className={clsx("h-0.5 flex-1", i === 0 ? "opacity-0" : done[i - 1] ? "bg-good" : "bg-border")} />
                <div
                  className={clsx(
                    "relative flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 text-[10px] font-semibold",
                    isDone ? "border-good bg-good text-bg" : isNow ? "border-accent text-accent" : "border-border text-faint",
                  )}
                >
                  {isDone ? <Check size={12} strokeWidth={3} /> : i + 1}
                  {isNow && live >= 0 && <span className="absolute -inset-1 animate-ping rounded-full border border-accent opacity-40" />}
                </div>
                <div className={clsx("h-0.5 flex-1", i === STEPS.length - 1 ? "opacity-0" : done[i] ? "bg-good" : "bg-border")} />
              </div>
              <span className={clsx("mt-1 text-[11px]", isNow ? "font-medium text-accent" : isDone ? "text-fg" : "text-faint")}>{st.label}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex items-center text-[11px] text-faint">
        <span>
          {run.evidence_rows} evidence rows · {run.notes} notes
          {live >= 0 ? " · staged run" : current < 0 ? " · complete" : ""}
        </span>
        <button onClick={() => setDetails(!details)} className="ml-auto underline hover:text-fg">
          {details ? "hide stages" : "all stages"}
        </button>
      </div>
      {details && (
        <div className="mt-1 space-y-0.5">
          {run.stages.map((s) => (
            <div key={s.stage} className="flex items-center gap-1.5" title={s.detail}>
              {s.ok ? <Check size={12} className="text-good" /> : <Circle size={10} className="ml-0.5 mr-0.5 text-faint" />}
              <span className={s.ok ? "" : "text-faint"}>{s.stage}</span>
              <span className="ml-auto truncate pl-2 text-[11px] text-faint">{s.detail}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ agents: cards, swimlanes, list

const KINDS: { match: RegExp; label: string; color: string }[] = [
  { match: /scout/i, label: "Scout", color: "#4f8fd6" },
  { match: /verif/i, label: "Verifier", color: "#3d9a6a" },
  { match: /critic/i, label: "Critic", color: "#c9822b" },
  { match: /writer/i, label: "Writer", color: "#9b6bd1" },
  { match: /explore|plan/i, label: "Explorer", color: "#3aa5a5" },
];

function kind(a: AgentRow) {
  if (a.type === "main") return { label: "Main thread", color: "var(--text-secondary)" };
  return KINDS.find((k) => k.match.test(a.type)) ?? { label: a.type, color: "#7a8394" };
}

type Mode = "cards" | "lanes" | "list";

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

function Cards({ agents, now }: { agents: AgentRow[]; now: number }) {
  return (
    <div className="space-y-2">
      {agents.map((a) => {
        const k = kind(a);
        const last = a.calls[a.calls.length - 1];
        return (
          <div key={a.id} className={clsx("rounded-lg border bg-surface p-2.5", a.status === "running" ? "border-accent/50 shadow-sm" : "border-border")} style={{ borderLeft: `3px solid ${k.color}` }}>
            <div className="flex items-center gap-1.5">
              <StatusDot status={a.status} color={k.color} />
              <span className="font-medium" style={{ color: k.color }}>
                {k.label}
              </span>
              <span className={clsx("ml-auto text-[11px]", a.status === "running" ? "text-accent" : a.status === "failed" ? "text-bad" : "text-faint")}>{a.status}</span>
            </div>
            {a.type !== "main" && <div className="mt-0.5 line-clamp-2 text-[11.5px] text-fg">{a.description}</div>}
            <div className="mt-1 flex flex-wrap gap-x-2 text-[11px] text-faint">
              {a.started && <span>{elapsed(a.started, a.ended ?? now)}</span>}
              <span>
                {tokens(a.tokens_in)} in / {tokens(a.tokens_out)} out
              </span>
              <span className="flex items-center gap-0.5">
                <Globe size={10} /> {a.web}
              </span>
              <span>{a.calls.length} calls</span>
            </div>
            {last && a.status === "running" && (
              <div className="mt-1 truncate text-[11px] text-muted" title={last.summary}>
                <span className="text-fg">{last.name}</span> {last.summary}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Lanes({ agents, now }: { agents: AgentRow[]; now: number }) {
  const timed = agents.filter((a) => a.started);
  if (!timed.length) return <div className="text-faint">No timings yet.</div>;
  const t0 = Math.min(...timed.map((a) => a.started as number));
  const t1 = timed.some((a) => a.status === "running") ? now : Math.max(...timed.map((a) => a.ended ?? now));
  const span = Math.max(1, t1 - t0);
  const pct = (t: number) => `${((t - t0) / span) * 100}%`;
  const mark = (secs: number) => (secs >= 60 ? `${Math.floor(secs / 60)}m${String(Math.round(secs % 60)).padStart(2, "0")}` : `${Math.round(secs)}s`);
  return (
    <div>
      <div className="relative mb-1 h-3 text-[10px] text-faint">
        <span className="absolute left-0">0</span>
        <span className="absolute left-1/2 -translate-x-1/2">{mark(span / 2)}</span>
        <span className="absolute right-0">{mark(span)}</span>
      </div>
      <div className="space-y-1.5">
        {timed.map((a) => {
          const k = kind(a);
          const end = a.ended ?? now;
          return (
            <div key={a.id} title={`${k.label}: ${a.description}\n${elapsed(a.started, end)} · ${tokens(a.tokens_in)} in · ${a.web} web`}>
              <div className="flex items-center gap-1 text-[11px]">
                <span style={{ color: k.color }} className="shrink-0 font-medium">
                  {k.label}
                </span>
                <span className="min-w-0 flex-1 truncate text-faint">{a.type === "main" ? "" : a.description}</span>
                <span className="shrink-0 text-faint">{elapsed(a.started, end)}</span>
              </div>
              <div className="relative h-2.5 rounded bg-panel">
                <div
                  className={clsx("absolute top-0 h-2.5 rounded", a.status === "running" && "lane-running")}
                  style={{ left: pct(a.started as number), width: `max(3px, calc(${pct(end)} - ${pct(a.started as number)}))`, background: a.status === "failed" ? "var(--bad)" : k.color }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Agents({ agents, openAgent, setOpenAgent }: { agents: AgentRow[]; openAgent: string | null; setOpenAgent: (id: string | null) => void }) {
  const [mode, setModeState] = useState<Mode>(() => prefs().agents_view);
  const setMode = (m: Mode) => {
    setModeState(m);
    setPref("agents_view", m);
  };
  const running = agents.some((a) => a.status === "running");
  const now = useNow(running);
  const subs = agents.filter((a) => a.type !== "main");
  const main = agents.find((a) => a.type === "main");
  // The current fan-out: everything still running, and the most recent finished ones.
  const recent = [...subs].sort((a, b) => (b.started ?? 0) - (a.started ?? 0)).slice(0, 14).reverse();
  const shown = [...(main ? [main] : []), ...recent];
  const counts = { running: subs.filter((a) => a.status === "running").length, done: subs.filter((a) => a.status === "done").length };
  const modes: { id: Mode; icon: React.ReactNode; title: string }[] = [
    { id: "cards", icon: <LayoutGrid size={12} />, title: "Cards" },
    { id: "lanes", icon: <Rows3 size={12} />, title: "Swimlanes" },
    { id: "list", icon: <List size={12} />, title: "List" },
  ];
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[11px] text-faint">
          {subs.length ? `${counts.running} running · ${counts.done} done${subs.length > recent.length ? ` · latest ${recent.length} of ${subs.length}` : ""}` : "No subagents yet"}
        </span>
        <div className="ml-auto flex rounded-md border border-border">
          {modes.map((m) => (
            <button key={m.id} title={m.title} onClick={() => setMode(m.id)} className={clsx("px-1.5 py-1", mode === m.id ? "bg-accent-bg text-accent" : "text-faint hover:text-fg")}>
              {m.icon}
            </button>
          ))}
        </div>
      </div>
      {mode === "cards" && <Cards agents={shown} now={now} />}
      {mode === "lanes" && <Lanes agents={shown} now={now} />}
      {mode === "list" && (
        <div className="space-y-1">
          {agents.map((a) => (
            <div key={a.id}>
              <button onClick={() => setOpenAgent(openAgent === a.id ? null : a.id)} className="w-full rounded-md px-2 py-1.5 text-left hover:bg-panel">
                <div className="flex items-center gap-1.5">
                  <Bot size={12} className={a.type === "main" ? "text-muted" : "text-accent"} />
                  <span className="font-medium">{a.type === "main" ? "Main thread" : a.type}</span>
                  <span className={clsx("ml-auto text-[11px]", a.status === "running" ? "text-accent" : a.status === "failed" ? "text-bad" : "text-faint")}>{a.status}</span>
                </div>
                {a.type !== "main" && <div className="truncate text-[11.5px] text-muted">{a.description}</div>}
                <div className="text-[11px] text-faint">
                  {a.type !== "main" && `${elapsed(a.started, a.ended)} · `}
                  {tokens(a.tokens_in)} in / {tokens(a.tokens_out)} out · {a.web} web
                </div>
              </button>
              {openAgent === a.id && (
                <div className="mb-1 ml-5 space-y-0.5 border-l border-border pl-2">
                  {a.calls.length === 0 && <div className="text-[11px] text-faint">No tool calls.</div>}
                  {a.calls.map((c, i) => (
                    <div key={i} className="truncate text-[11px] text-muted">
                      <span className="text-fg">{c.name}</span> {c.summary}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 mt-4 text-[11px] font-medium uppercase tracking-wide text-faint first:mt-0">{children}</div>;
}

export default function ActivityPanel({ sid, data }: { sid: string; data: Activity | undefined }) {
  const [openAgent, setOpenAgent] = useState<string | null>(null);
  const client = useQueryClient();
  const raise = useMutation({
    mutationFn: () => api.post(`/api/sessions/${sid}/raise-cap`),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["activity", sid] }),
  });
  if (!data) return <div className="p-4 text-[12px] text-faint">Loading…</div>;
  const capped = data.cost.segments.some((s) => s.open && (s.searches >= s.search_cap || s.fetches >= s.fetch_cap)) || data.cost.notices.length > 0;

  return (
    <div className="scroll-thin h-full overflow-y-auto p-4 text-[12.5px]">
      <Heading>Progress</Heading>
      <Stepper data={data} />

      <Heading>Agents</Heading>
      <Agents agents={data.agents} openAgent={openAgent} setOpenAgent={setOpenAgent} />

      <Heading>Permissions</Heading>
      {data.permissions.length === 0 && <div className="text-faint">No requests yet.</div>}
      <div className="space-y-0.5">
        {data.permissions.slice(0, 12).map((p, i) => (
          <div key={i} className="flex items-center gap-1.5" title={p.summary}>
            <span
              className={clsx(
                "w-16 shrink-0 text-[11px]",
                p.decision === "deny" || p.decision === "blocked" ? "text-bad" : p.decision === "waiting" ? "text-accent" : p.decision === "unanswered" || p.decision === "withdrawn" ? "text-faint" : "text-good",
              )}
            >
              {p.decision}
            </span>
            <span className="shrink-0 font-medium">{p.kind === "question" ? "Question" : p.tool}</span>
            <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted">{p.summary}</span>
            <span className="shrink-0 text-[10.5px] text-faint">{clock(p.ts)}</span>
          </div>
        ))}
      </div>

      <Heading>Cost</Heading>
      <div className="space-y-1">
        <div>
          Session ${data.cost.total_usd.toFixed(2)}
          {data.cost.context_percent != null && <span className="text-faint"> · context {Math.round(data.cost.context_percent)}%</span>}
        </div>
        {(data.windows?.windows ?? []).map((w) => (
          <div key={w.name} className="flex items-center gap-2">
            <span className="w-12 text-faint">{w.name}</span>
            <div className="h-1.5 flex-1 rounded bg-panel">
              <div className={clsx("h-1.5 rounded", (w.used_percent ?? 0) >= 85 ? "bg-warn" : "bg-good")} style={{ width: `${Math.min(100, w.used_percent ?? 0)}%` }} />
            </div>
            <span className="w-24 text-right text-[11px] text-faint">
              {w.used_percent != null ? `${Math.round(w.used_percent)}%` : ""} {w.resets_at ? resetLabel(w.resets_at) : ""}
            </span>
          </div>
        ))}
        {data.windows?.note && <div className="text-[11px] text-faint">{data.windows.note}</div>}
        {data.cost.segments.map((s, i) => (
          <div key={i} className="rounded-md bg-panel px-2 py-1.5">
            <div className="flex items-center gap-1">
              <span className="font-medium">{s.label}</span>
              {s.open && <span className="text-[11px] text-accent">current</span>}
              <span className="ml-auto">{s.cost_usd ? `$${s.cost_usd.toFixed(2)}` : ""}</span>
            </div>
            <div className="text-[11px] text-faint">
              {tokens(s.tokens_in)} in / {tokens(s.tokens_out)} out
            </div>
            <div className="flex items-center gap-1 text-[11px] text-faint">
              <Globe size={11} /> {s.searches}/{s.search_cap} searches · {s.fetches}/{s.fetch_cap} fetches
            </div>
          </div>
        ))}
        {data.cost.notices.map((n, i) => (
          <div key={i} className="text-[11.5px] text-warn">
            {n.text}
          </div>
        ))}
        {capped && (
          <button onClick={() => raise.mutate()} className="mt-1 rounded-md border border-border px-2 py-1 text-[12px] hover:border-accent">
            Raise cap
          </button>
        )}
        {raise.isError && <div className="text-[11px] text-bad">{(raise.error as Error).message}</div>}
      </div>
    </div>
  );
}
