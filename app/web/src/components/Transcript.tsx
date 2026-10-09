import { useState } from "react";
import clsx from "clsx";
import { AlertTriangle, Bot, ChevronDown, ChevronRight, CircleCheck, CircleX, Info, Repeat, ShieldQuestion, Wrench } from "lucide-react";
import { label, resetLabel } from "../lib/format";
import { send } from "../lib/socket";
import type { AppEvent, Connection } from "../lib/types";
import Markdown from "./Markdown";

interface Ctx {
  sid: string;
  results: Map<string, AppEvent>;
  answers: Map<string, string>;
  answerTexts: Map<string, Record<string, string>>;
  children: Map<string, AppEvent[]>;
  running: boolean;
  openSegment: boolean;
  lastUserTs: number;
  connections: Connection[];
}

function ToolRow({ ev, ctx, depth = 0 }: { ev: AppEvent; ctx: Ctx; depth?: number }) {
  const [open, setOpen] = useState(false);
  const id = String(ev.data.id ?? "");
  const result = ctx.results.get(id);
  const sub = ev.data.subagent as { type: string; description: string } | undefined;
  const kids = ctx.children.get(id) ?? [];
  const failed = result?.data.is_error;
  return (
    <div className={clsx("text-[13px]", depth && "ml-4")}>
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-muted hover:bg-panel">
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {sub ? <Bot size={13} className="text-accent" /> : <Wrench size={13} />}
        <span className="font-medium text-fg">{sub ? `${sub.type}` : ev.data.name}</span>
        <span className="min-w-0 flex-1 truncate">{sub ? sub.description : ev.data.summary}</span>
        {sub && <span className="text-[11px] text-faint">{kids.filter((k) => k.type === "tool_call").length} calls</span>}
        {result ? failed ? <CircleX size={13} className="text-bad" /> : <CircleCheck size={13} className="text-good" /> : ctx.running ? <span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> : null}
      </button>
      {open && (
        <div className="mb-2 ml-7 space-y-1.5 border-l border-border pl-3">
          {ev.data.input && Object.keys(ev.data.input).length > 0 && (
            <pre className="scroll-thin max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-panel p-2 font-mono text-[11.5px] text-muted">{JSON.stringify(ev.data.input, null, 2)}</pre>
          )}
          {result && <div className={clsx("whitespace-pre-wrap font-mono text-[11.5px]", failed ? "text-bad" : "text-muted")}>{String(result.data.summary ?? "")}</div>}
          {kids.map((k, i) =>
            k.type === "tool_call" ? (
              <ToolRow key={i} ev={k} ctx={ctx} depth={1} />
            ) : k.type === "assistant_text" ? (
              <div key={i} className="ml-4 text-[12.5px] text-muted">
                <Markdown text={String(k.data.text ?? "")} />
              </div>
            ) : null,
          )}
        </div>
      )}
    </div>
  );
}

interface Question {
  question: string;
  header: string;
  options: { label: string; description?: string }[];
  multiSelect?: boolean;
}

function QuestionCard({ ev, ctx }: { ev: AppEvent; ctx: Ctx }) {
  const id = String(ev.data.id);
  const answer = ctx.answers.get(id);
  const live = !answer && ctx.running;
  const questions = (ev.data.questions ?? []) as Question[];
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  const [other, setOther] = useState<Record<string, string>>({});
  const answered = ctx.answerTexts.get(id);
  const toggle = (q: Question, label: string) =>
    setPicked((p) => {
      const now = p[q.question] ?? [];
      if (!q.multiSelect) return { ...p, [q.question]: now[0] === label ? [] : [label] };
      return { ...p, [q.question]: now.includes(label) ? now.filter((l) => l !== label) : [...now, label] };
    });
  const value = (q: Question) => (other[q.question]?.trim() ? other[q.question].trim() : (picked[q.question] ?? []).join(", "));
  const ready = questions.every((q) => value(q));
  const submit = () => {
    const answers = Object.fromEntries(questions.map((q) => [q.question, value(q)]));
    send({ type: "permission", session: ctx.sid, id, decision: "answer", answers });
  };
  const launch = questions.some((q) => q.header === "LAUNCH CODE");
  return (
    <div className={clsx("rounded-xl border p-3 text-[13px]", live ? (launch ? "border-bad bg-bad/5" : "border-accent bg-accent-bg") : "border-border")}>
      {questions.map((q) => (
        <div key={q.question} className="mb-3 last:mb-1">
          <div className="mb-1 flex items-center gap-2">
            <span className={clsx("rounded px-1.5 text-[11px] font-medium", launch ? "bg-bad text-white" : "bg-panel text-muted")}>{q.header}</span>
            {ev.agent && <span className="text-[11px] text-faint">subagent</span>}
          </div>
          <div className="mb-2 font-medium">{q.question}</div>
          {launch && live && (
            <div className="mb-2 text-[12px] text-muted">
              The launch-codes mod shows its 4-character code only in a terminal Claude Code session. Here you can abort; run the command yourself if you want it.
            </div>
          )}
          {live ? (
            <>
              <div className="flex flex-wrap gap-1.5">
                {q.options.map((o) => (
                  <button
                    key={o.label}
                    onClick={() => toggle(q, o.label)}
                    title={o.description}
                    className={clsx("rounded-md border px-2.5 py-1 text-[12.5px]", (picked[q.question] ?? []).includes(o.label) ? "border-accent bg-accent text-white" : "border-border bg-surface hover:border-accent")}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
              <input
                value={other[q.question] ?? ""}
                onChange={(e) => setOther((o) => ({ ...o, [q.question]: e.target.value }))}
                onKeyDown={(e) => e.key === "Enter" && ready && submit()}
                placeholder="Other: type your own answer"
                className="mt-2 w-full rounded-md border border-border bg-surface px-2 py-1 text-[12.5px] outline-none focus:border-accent"
              />
            </>
          ) : (
            <div className="text-[12px] text-muted">{answered?.[q.question] ? `Answered: ${answered[q.question]}` : answer === "deny" ? "Not answered" : answer === "withdrawn" ? "Withdrawn" : "No longer waiting"}</div>
          )}
        </div>
      ))}
      {live && (
        <div className="flex gap-2">
          <button onClick={submit} disabled={!ready} className="rounded-md bg-accent px-3 py-1 text-[12px] text-white disabled:opacity-40">
            Answer
          </button>
          <button onClick={() => send({ type: "permission", session: ctx.sid, id, decision: "skip" })} className="rounded-md border border-border bg-surface px-3 py-1 text-[12px]">
            Skip
          </button>
        </div>
      )}
    </div>
  );
}

function PermissionCard({ ev, ctx }: { ev: AppEvent; ctx: Ctx }) {
  const id = String(ev.data.id);
  const answer = ctx.answers.get(id);
  const live = !answer && ctx.running;
  const [show, setShow] = useState(false);
  const decide = (decision: string) => send({ type: "permission", session: ctx.sid, id, decision });
  return (
    <div className={clsx("rounded-xl border p-3 text-[13px]", live ? "border-accent bg-accent-bg" : "border-border")}>
      <div className="flex items-center gap-2">
        <ShieldQuestion size={15} className="text-accent" />
        <span className="font-medium">{ev.data.tool}</span>
        <span className="min-w-0 flex-1 truncate text-muted">{ev.data.summary}</span>
        {ev.agent && <span className="text-[11px] text-faint">subagent</span>}
      </div>
      <button onClick={() => setShow(!show)} className="mt-1 text-[12px] text-faint hover:text-muted">
        {show ? "Hide details" : "Show details"}
      </button>
      {show && <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-panel p-2 font-mono text-[11.5px]">{JSON.stringify(ev.data.input, null, 2)}</pre>}
      {live ? (
        <div className="mt-2 flex gap-2">
          <button onClick={() => decide("once")} className="rounded-md bg-accent px-3 py-1 text-[12px] text-white">
            Allow once
          </button>
          <button onClick={() => decide("always")} className="rounded-md border border-border bg-surface px-3 py-1 text-[12px]" title={(ev.data.rules ?? []).map((r: { tool: string; rule: string }) => `${r.tool}(${r.rule})`).join(", ")}>
            Always allow
          </button>
          <button onClick={() => decide("deny")} className="rounded-md border border-border bg-surface px-3 py-1 text-[12px] text-bad">
            Deny
          </button>
        </div>
      ) : (
        <div className="mt-1 text-[12px] text-faint">{answer === "deny" ? "Denied" : answer === "always" ? "Always allowed" : answer === "once" ? "Allowed once" : answer === "withdrawn" ? "Withdrawn" : "No longer waiting"}</div>
      )}
    </div>
  );
}

function LimitCard({ ev, ctx, actionable }: { ev: AppEvent; ctx: Ctx; actionable: boolean }) {
  const [chosen, setChosen] = useState<string>(String(ev.data.next ?? ""));
  const [waiting, setWaiting] = useState(false);
  const provider = label(ev.data.provider ?? ev.provider);
  const resets = ev.data.resets_at ? ` (resets ${resetLabel(ev.data.resets_at)})` : "";
  const target = ctx.connections.find((c) => c.id === chosen);
  const go = (conn: string) => send({ type: "switch", session: ctx.sid, connection: conn, reason: "limit" });
  return (
    <div className="rounded-xl border border-warn/60 bg-surface p-3 text-[13px]">
      <div className="flex items-start gap-2">
        <AlertTriangle size={15} className="mt-0.5 text-warn" />
        <div className="flex-1">
          <div className="font-medium">
            {provider}'s plan limit is reached{resets}.
            {actionable && !waiting && chosen && ` Continue with ${label(chosen)}?`}
          </div>
          {ev.data.text && <div className="mt-0.5 text-[12px] text-faint">{ev.data.text}</div>}
          {actionable && !waiting && (
            <>
              {target?.billing === "key" && <div className="mt-1 text-[12px] text-warn">{target.label} bills per token.</div>}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {chosen && (
                  <button onClick={() => go(chosen)} className="rounded-md bg-accent px-3 py-1 text-[12px] text-white">
                    Continue
                  </button>
                )}
                <select value={chosen} onChange={(e) => setChosen(e.target.value)} className="rounded-md border border-border bg-surface px-2 py-1 text-[12px]">
                  <option value="">Choose another…</option>
                  {ctx.connections
                    .filter((c) => c.id !== ev.data.provider)
                    .map((c) => (
                      <option key={c.id} value={c.id} disabled={!c.signed_in}>
                        {c.label}
                        {c.signed_in ? "" : " (not ready)"}
                      </option>
                    ))}
                </select>
                <button onClick={() => setWaiting(true)} className="rounded-md border border-border px-3 py-1 text-[12px]">
                  Wait
                </button>
              </div>
            </>
          )}
          {waiting && <div className="mt-1 text-[12px] text-faint">Waiting. Send a message when the window resets and the session resumes on {provider}.</div>}
        </div>
      </div>
    </div>
  );
}

function HandoverCard({ ev, ctx, actionable }: { ev: AppEvent; ctx: Ctx; actionable: boolean }) {
  const [dismissed, setDismissed] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-[12.5px] text-muted">
      <Repeat size={14} className="text-warn" />
      <span className="flex-1">
        {ev.data.text}
        {ev.data.resets_at ? ` Resets ${resetLabel(ev.data.resets_at)}.` : ""}
      </span>
      {actionable && !dismissed && ev.data.next && (
        <>
          <button onClick={() => send({ type: "switch", session: ctx.sid, connection: ev.data.next, reason: "handover" })} className="rounded-md bg-accent px-2.5 py-1 text-[12px] text-white">
            Hand over to {label(ev.data.next)}
          </button>
          <button onClick={() => setDismissed(true)} className="text-[12px] text-faint hover:text-muted">
            Not now
          </button>
        </>
      )}
    </div>
  );
}

function HandoffRow({ ev }: { ev: AppEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-dashed border-border px-3 py-2 text-[12.5px] text-muted">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 text-left">
        <Repeat size={14} />
        <span className="flex-1">
          {ev.data.resumed ? "Resumed" : "Continued"} on {label(ev.data.to)}
          {ev.data.from ? ` after ${label(ev.data.from)}` : ""}. Handoff packet {ev.data.name}
          {ev.data.flagged?.length ? `, ${ev.data.flagged.length} flagged file(s)` : ""}.
        </span>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>
      {open && (
        <div className="mt-2 max-h-96 overflow-auto rounded bg-panel p-3">
          <Markdown text={String(ev.data.packet ?? "")} className="text-[12.5px]" />
        </div>
      )}
    </div>
  );
}

const NOTICE_TONE: Record<string, string> = { cap: "text-warn", isolation: "text-warn", gate: "text-warn", lock: "text-warn", external: "text-warn" };

export default function Transcript({
  sid,
  events,
  running,
  openSegment,
  connections,
}: {
  sid: string;
  events: AppEvent[];
  running: boolean;
  openSegment: boolean;
  connections: Connection[];
}) {
  const results = new Map<string, AppEvent>();
  const answers = new Map<string, string>();
  const answerTexts = new Map<string, Record<string, string>>();
  const children = new Map<string, AppEvent[]>();
  for (const e of events) {
    if (e.type === "tool_result") results.set(String(e.data.id), e);
    if (e.type === "permission_answer") {
      answers.set(String(e.data.id), String(e.data.decision));
      if (e.data.answers) answerTexts.set(String(e.data.id), e.data.answers as Record<string, string>);
    }
    if (e.agent && (e.type === "tool_call" || e.type === "assistant_text")) {
      children.set(e.agent, [...(children.get(e.agent) ?? []), e]);
    }
  }
  const lastUserTs = Math.max(0, ...events.filter((e) => e.type === "user").map((e) => e.ts));
  const lastLimit = [...events].reverse().find((e) => e.type === "error" && e.data.kind === "limit");
  const lastHandover = [...events].reverse().find((e) => e.type === "notice" && e.data.kind === "handover");
  const lastSwitch = Math.max(0, ...events.filter((e) => e.type === "handoff").map((e) => e.ts));
  const ctx: Ctx = { sid, results, answers, answerTexts, children, running, openSegment, lastUserTs, connections };

  return (
    <div className="space-y-3">
      {events.map((ev, i) => {
        if (ev.agent && ev.type !== "permission_request" && ev.type !== "notice") return null;
        switch (ev.type) {
          case "user":
            return (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-panel px-4 py-2.5 text-[14px]">{ev.data.text}</div>
              </div>
            );
          case "assistant_text":
            return <Markdown key={i} text={String(ev.data.text ?? "")} className="text-[14px]" />;
          case "tool_call":
            return <ToolRow key={i} ev={ev} ctx={ctx} />;
          case "permission_request":
            return ev.data.kind === "question" ? <QuestionCard key={i} ev={ev} ctx={ctx} /> : <PermissionCard key={i} ev={ev} ctx={ctx} />;
          case "session":
            return (
              <div key={i} className="text-center text-[11.5px] text-faint">
                {label(ev.provider)} session {ev.data.model ? `· ${ev.data.model}` : ""}
                {ev.provider?.startsWith("claude") && ev.data.monitor_loaded === false ? " · research monitor not loaded" : ""}
              </div>
            );
          case "handoff":
            return <HandoffRow key={i} ev={ev} />;
          case "notice":
            if (ev.data.kind === "handover") {
              return <HandoverCard key={i} ev={ev} ctx={ctx} actionable={ev === lastHandover && !running && openSegment && ev.ts > lastSwitch} />;
            }
            if (ev.data.kind === "route") {
              return (
                <div key={i} className="px-1 text-[11.5px] text-faint">
                  {ev.data.text}
                </div>
              );
            }
            return (
              <div key={i} className={clsx("flex items-start gap-2 rounded-lg border border-border px-3 py-2 text-[12.5px]", NOTICE_TONE[ev.data.kind] ?? "text-muted")}>
                <Info size={14} className="mt-0.5 shrink-0" />
                <span className="whitespace-pre-wrap">{ev.data.text}</span>
              </div>
            );
          case "error":
            if (ev.data.kind === "limit") {
              return <LimitCard key={i} ev={ev} ctx={ctx} actionable={ev === lastLimit && !running && !openSegment} />;
            }
            return (
              <div key={i} className="flex items-start gap-2 rounded-lg border border-bad/50 px-3 py-2 text-[13px] text-bad">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <span className="whitespace-pre-wrap">
                  {ev.data.kind === "auth" ? "Sign-in needed. " : ev.data.kind === "context" ? "The context is full. " : ev.data.kind === "network" ? "Network failure. " : ""}
                  {ev.data.text}
                </span>
              </div>
            );
          case "done":
            return ev.data.end_reason === "stopped" ? (
              <div key={i} className="text-[12px] text-faint">
                Stopped.
              </div>
            ) : null;
          default:
            return null;
        }
      })}
    </div>
  );
}
