// Mirrors of the backend's payloads (app/backend). Kept by hand; small enough.

export type EventType =
  | "user"
  | "session"
  | "assistant_text"
  | "tool_call"
  | "tool_result"
  | "permission_request"
  | "permission_answer"
  | "usage"
  | "notice"
  | "error"
  | "done"
  | "handoff";

export interface AppEvent {
  type: EventType;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
  ts: number;
  agent: string | null;
  provider: string | null;
}

export interface Segment {
  provider: string;
  model: string;
  effort: string;
  native_session_id: string | null;
  started: number;
  ended: number | null;
  end_reason: string | null;
  cost_usd: number;
}

export interface SessionSummary {
  id: string;
  title: string;
  created: number;
  updated: number;
  providers: string[];
  runs: string[];
  stale: boolean;
  running: boolean;
}

export interface SessionDetail {
  id: string;
  title: string;
  runs: string[];
  project: string;
  segments: Segment[];
  stale: boolean;
  imported_from: string | null;
  // "Continue with the same model later": when, and on which connection.
  resume_at?: number | null;
  resume_connection?: string | null;
  events: AppEvent[];
  running: boolean;
  open_permissions: string[];
}

export interface Command {
  name: string;
  description: string;
  kind: "skill" | "command";
  path: string;
}

export interface Stage {
  stage: string;
  ok: string;
  detail: string;
}

export interface RunSummary {
  name: string;
  kind: string;
  doc_kind: string;
  primary: string | null;
  mtime: number;
  prompt: string;
}

export interface RunDetail {
  name: string;
  path: string;
  meta: { kind: string; doc_kind?: string; masters: string[]; primary: string | null };
  stages: Stage[];
  files: { path: string; size: number; mtime: number }[];
  master: string;
  evidence_rows: number;
  notes: number;
}

export interface ExportFile {
  run: string;
  style: string;
  name: string;
  path: string;
  size: number;
  mtime: number;
}

export interface UsageWindow {
  name: string;
  used_percent: number | null;
  resets_at: number | null;
  status: string | null;
}

export interface Usage {
  windows: UsageWindow[];
  updated_at: number | null;
  note: string;
}

export interface ModelOption {
  value: string;
  label: string;
  description?: string;
  efforts: string[];
}

export interface Connection {
  id: string;
  label: string;
  runtime: "claude" | "codex";
  billing: "plan" | "key";
  installed: boolean;
  path: string | null;
  version: string | null;
  signed_in: boolean;
  message: string;
  models: ModelOption[];
  usage: Usage | null;
}

export interface Caps {
  searchCap: number;
  fetchCap: number;
  warnEvery: number;
  raise: { searches: number; fetches: number };
}

export interface Settings {
  connections: Record<string, { model: string; effort: string }>;
  fallback_order: string[];
  default_connection: string;
  handover_threshold: number;
  allow_rules: { tool: string; rule: string }[];
  caps: Caps;
  routing: Routing;
  staged_pipeline: boolean;
  permission_mode: string;
}

export type Tier = "frontier" | "workhorse" | "fast";

/** Model routing: a command picks a tier and an effort; each runtime maps tiers to models. */
export interface Routing {
  enabled: boolean;
  fresh: boolean;
  tiers: Record<"claude" | "codex", Record<Tier, string>>;
  commands: Record<string, [Tier, string]>;
  chat: [Tier, string];
}

export interface AgentRow {
  id: string;
  type: string;
  description: string;
  status: string;
  started: number | null;
  ended: number | null;
  tokens_in: number;
  tokens_out: number;
  web: number;
  calls_total: number;
  calls: { name: string; summary: string; ts: number }[];
}

export interface Activity {
  agents: AgentRow[];
  permissions: { ts: number; tool: string; kind: string; summary: string; decision: string; provider: string | null }[];
  progress: {
    run: string;
    kind: string;
    stages: Stage[];
    evidence_rows: number;
    notes: number;
    // The latest expansion round while it is open; the stepper follows it instead of the run.
    round: { name: string; notes: number; stages: Stage[] } | null;
  }[];
  pipeline: { run: string; stage: string } | null;
  // Subagents of earlier tasks in this conversation; the panel lists only the current task's.
  agents_earlier?: number;
  // The task the latest message started: its own steps, judged from evidence since it began.
  task: {
    command: string;
    label: string;
    text: string;
    started: number;
    running: boolean;
    steps: { label: string; state: "done" | "current" | "todo" | "skipped" }[];
    run: string | null;
  } | null;
  project: string;
  cost: {
    total_usd: number;
    context_percent: number | null;
    context_tokens: number | null;
    segments: {
      provider: string;
      label: string;
      model: string;
      cost_usd: number;
      tokens_in: number;
      tokens_out: number;
      searches: number;
      fetches: number;
      search_cap: number;
      fetch_cap: number;
      open: boolean;
    }[];
    notices: { text: string }[];
  };
  windows: Usage | null;
}

export interface WorkspaceGroup {
  group: string;
  files: { path: string; name: string; mtime: number }[];
}

export interface Commit {
  rev: string;
  short: string;
  date: string;
  message: string;
}
