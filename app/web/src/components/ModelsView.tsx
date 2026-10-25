import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowDown, ArrowUp, CircleCheck, CircleX, ExternalLink, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { api } from "../lib/api";
import { elapsed, resetLabel } from "../lib/format";
import type { Caps, Connection, Routing, Settings, Tier } from "../lib/types";
import { useUi } from "../stores/ui";
import { useSettings } from "./PromptBar";

const LINKS: Record<string, { label: string; href: string }[]> = {
  "claude-sub": [{ label: "Create a Claude account or choose a plan", href: "https://claude.ai/upgrade" }],
  "claude-api": [{ label: "Get an Anthropic API key", href: "https://console.anthropic.com/settings/keys" }],
  "codex-plan": [{ label: "Create a ChatGPT account or choose a plan", href: "https://chatgpt.com/" }],
  "codex-api": [{ label: "Get an OpenAI API key", href: "https://platform.openai.com/api-keys" }],
};

const OPTION_TITLE: Record<string, string> = {
  "claude-sub": "Use my Claude plan",
  "claude-api": "Use an Anthropic API key",
  "codex-plan": "Use my ChatGPT plan",
  "codex-api": "Use an OpenAI API key",
};

function ProviderPanel({ title, ids, all, settings, onSaved, put, children }: { title: string; ids: string[]; all: Connection[]; settings: Settings; onSaved: () => void; put: (p: Partial<Settings>) => Promise<void>; children?: React.ReactNode }) {
  const conns = ids.map((id) => all.find((c) => c.id === id)).filter((c): c is Connection => Boolean(c));
  const first = conns[0];
  return (
    <section className="rounded-2xl border border-border bg-panel/40 p-4">
      <div className="mb-1 flex items-baseline gap-2">
        <h2 className="text-[0.9375rem] font-medium">{title}</h2>
        {first && <span className="text-[0.75rem] text-faint">{first.installed ? `installed${first.version ? ` · ${first.version}` : ""}` : "not installed"}</span>}
      </div>
      {first?.path && (
        <div className="mb-3 truncate font-mono text-[0.6875rem] text-faint" title={first.path}>
          {first.path}
        </div>
      )}
      {first && !first.installed && <div className="mb-3 text-[0.7812rem] text-muted">{first.message}</div>}
      <div className="grid gap-3 md:grid-cols-2">
        {conns.map((c) => (
          <Card key={c.id} c={c} settings={settings} onSaved={onSaved} isDefault={settings.default_connection === c.id} onDefault={() => void put(firstInOrder(settings, c.id))} />
        ))}
      </div>
      {children}
    </section>
  );
}

function Card({ c, settings, onSaved, isDefault, onDefault }: { c: Connection; settings: Settings; onSaved: () => void; isDefault: boolean; onDefault: () => void }) {
  const client = useQueryClient();
  const { setView } = useUi();
  const [key, setKey] = useState("");
  const [message, setMessage] = useState("");
  const expectedEmail = c.id === "claude-sub"
    ? settings.claude_default_email ?? ""
    : settings.claude_accounts.find((account) => account.id === c.id)?.email ?? "";
  const [loginEmail, setLoginEmail] = useState(expectedEmail);
  const conf = settings.connections[c.id] ?? { model: "", effort: "" };
  const model = c.models.find((m) => m.value === conf.model);
  const efforts = model?.efforts?.length ? model.efforts : ["low", "medium", "high", "xhigh", "max"];
  const refresh = () => void client.invalidateQueries({ queryKey: ["connections"] });
  const act = useMutation({
    mutationFn: async (what: string) => {
      if (what === "login") return api.post<{ message: string }>(`/api/connections/${c.id}/login`, c.runtime === "claude" ? { email: loginEmail.trim() } : {});
      if (what === "logout") return api.post<{ message: string }>(`/api/connections/${c.id}/logout`);
      if (what === "remove") return api.del(`/api/accounts/${c.id}`);
      if (what === "key") return api.post(`/api/connections/${c.id}/key`, { key });
      if (what === "unkey") return api.del(`/api/connections/${c.id}/key`);
      if (what === "test") return api.post(`/api/connections/${c.id}/test`);
      return api.post<{ session: string }>(`/api/connections/${c.id}/test-turn`);
    },
    onSuccess: (res, what) => {
      setKey("");
      if (what === "login" || what === "logout") setMessage((res as { message: string }).message);
      if (what === "login") onSaved();
      if (what === "remove") onSaved();
      if (what === "test") setMessage("Checked the binary and the sign-in. No model call was made.");
      if (what === "turn") setView({ kind: "session", id: (res as { session: string }).session });
      void client.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e) => setMessage((e as Error).message),
  });
  const save = async (patch: { model?: string; effort?: string }) => {
    await api.put("/api/settings", { connections: { [c.id]: { ...conf, ...patch } } });
    onSaved();
  };

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center gap-2">
        {c.installed && c.signed_in ? <CircleCheck size="1rem" className="text-good" /> : <CircleX size="1rem" className="text-faint" />}
        <div className="text-[0.8438rem] font-medium">{OPTION_TITLE[c.id] ?? `Use my Claude plan: ${c.label}`}</div>
        <button onClick={refresh} title="Check again" className="ml-auto text-faint hover:text-fg">
          <RefreshCw size="0.8125rem" />
        </button>
      </div>
      <div className="mt-1 text-[0.75rem] text-muted">{c.billing === "plan" ? "Uses your subscription's usage windows." : "Bills per token to your API account. The key is kept in the macOS Keychain."}</div>
      <div className="mt-1.5 text-[0.75rem]">{c.message}</div>
      <label className="mt-2 flex items-center gap-1.5 text-[0.75rem] text-muted">
        <input type="radio" checked={isDefault} onChange={onDefault} disabled={!c.signed_in} />
        New sessions start here
      </label>
      <div className="mt-1 flex flex-wrap gap-x-3">
        {(LINKS[c.id] ?? (c.runtime === "claude" && c.billing === "plan" ? LINKS["claude-sub"] : [])).map((l) => (
          <a key={l.href} href={l.href} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[0.75rem] text-accent underline underline-offset-2">
            {l.label} <ExternalLink size="0.6875rem" />
          </a>
        ))}
      </div>
      {(c.usage?.windows ?? []).length > 0 && (
        <div className="mt-2 space-y-1">
          {c.usage?.updated_at && <div className="text-[0.6875rem] text-faint">Last reported {elapsed(c.usage.updated_at, Date.now() / 1000)} ago</div>}
          {c.usage!.windows.map((w) => (
            <div key={w.name} className="flex items-center gap-2 text-[0.75rem]">
              <span className="w-10 text-faint">{w.name}</span>
              <div className="h-1.5 flex-1 rounded bg-panel">
                <div className={clsx("h-1.5 rounded", (w.used_percent ?? 0) >= 85 ? "bg-warn" : "bg-good")} style={{ width: `${Math.min(100, w.used_percent ?? 0)}%` }} />
              </div>
              <span className="w-28 text-right text-[0.6875rem] text-faint">
                {w.used_percent != null ? `${Math.round(w.used_percent)}%` : w.status} {w.resets_at ? `· ${resetLabel(w.resets_at)}` : ""}
              </span>
            </div>
          ))}
        </div>
      )}
      {c.usage?.note && <div className="mt-1 text-[0.6875rem] text-faint">{c.usage.note}</div>}

      {c.installed && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[0.75rem]">
          <label className="text-faint">Model</label>
          <select value={conf.model} onChange={(e) => void save({ model: e.target.value })} className="max-w-[12rem] rounded-md border border-border bg-surface px-2 py-1">
            <option value="">{c.runtime === "codex" ? "Codex default" : "default"}</option>
            {c.models
              .filter((m) => m.value !== "default")
              .map((m) => (
                <option key={m.value} value={m.value} title={m.description}>
                  {m.label}
                </option>
              ))}
          </select>
          <label className="ml-2 text-faint">Effort</label>
          <select value={conf.effort} onChange={(e) => void save({ effort: e.target.value })} className="rounded-md border border-border bg-surface px-2 py-1">
            <option value="">default</option>
            {efforts.map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {c.billing === "plan" ? (
          <>
            {c.runtime === "claude" && !c.signed_in && (
              <label className="flex items-center gap-2 text-[0.75rem] text-faint">
                Sign in as
                <input type="email" value={loginEmail} onChange={(e) => setLoginEmail(e.target.value)} placeholder="name@example.com" className="w-48 rounded-md border border-border bg-surface px-2 py-1 text-fg" />
              </label>
            )}
            <button disabled={!c.installed || c.signed_in || (c.runtime === "claude" && !loginEmail.trim())} onClick={() => act.mutate("login")} className="rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent disabled:opacity-40">
              {c.signed_in ? "Signed in" : c.runtime === "claude" ? "Sign in with Claude" : "Sign in with ChatGPT"}
            </button>
            {c.runtime === "claude" && c.account && (
              <button
                onClick={() => {
                  if (window.confirm(`Sign ${c.account ?? c.label} out of this connection? Other accounts stay signed in.`)) act.mutate("logout");
                }}
                className="rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent"
              >
                Sign out
              </button>
            )}
          </>
        ) : (
          <>
            <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={c.signed_in ? "Replace the stored key" : "Paste an API key"} className="w-56 rounded-md border border-border bg-surface px-2 py-1 text-[0.75rem]" />
            <button disabled={!key.trim()} onClick={() => act.mutate("key")} className="rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent disabled:opacity-40">
              Add key
            </button>
            {c.signed_in && (
              <button onClick={() => act.mutate("unkey")} className="rounded-md border border-border px-2.5 py-1 text-[0.75rem] text-bad">
                Remove key
              </button>
            )}
          </>
        )}
        <button disabled={!c.installed} onClick={() => act.mutate("test")} className="rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent disabled:opacity-40">
          Test
        </button>
        <button
          disabled={!c.signed_in}
          onClick={() => {
            if (window.confirm(`Send one short message to ${c.label}? It is a real model turn.`)) act.mutate("turn");
          }}
          className="rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent disabled:opacity-40"
        >
          Send a test message
        </button>
        {c.removable && (
          <button
            onClick={() => {
              if (window.confirm(`Remove ${c.label} from the app? It is signed out first. Its folder stays on disk, so it can be added back.`)) act.mutate("remove");
            }}
            className="ml-auto flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[0.75rem] text-bad hover:border-bad"
          >
            <Trash2 size="0.75rem" /> Remove account
          </button>
        )}
      </div>
      {message && <div className="mt-2 text-[0.75rem] text-muted">{message}</div>}
    </div>
  );
}

/** Put one connection first in the order of use; new sessions start on the first. */
function firstInOrder(s: Settings, id: string): Partial<Settings> {
  return { default_connection: id, fallback_order: [id, ...s.fallback_order.filter((x) => x !== id)] };
}

function AddAccount({ onSaved }: { onSaved: () => void }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [email, setEmail] = useState("");
  const [folder, setFolder] = useState("");
  const [message, setMessage] = useState("");
  const add = useMutation({
    mutationFn: () => api.post("/api/accounts", { label, email, config_dir: folder }),
    onSuccess: () => {
      setLabel("");
      setEmail("");
      setFolder("");
      setOpen(false);
      setMessage("Account added. Sign it in on its card.");
      onSaved();
      void client.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e) => setMessage((e as Error).message),
  });
  const field = "rounded-md border border-border bg-surface px-2 py-1 text-[0.75rem]";
  return (
    <div className="mt-3">
      {open ? (
        <div className="rounded-xl border border-dashed border-border p-3">
          <div className="mb-2 text-[0.7812rem] text-muted">Another Claude subscription, with its own sign-in and usage windows. It shares this machine's Claude Code settings, skills and conversations.</div>
          <div className="flex flex-wrap items-center gap-2">
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Name, e.g. Second plan" className={clsx(field, "w-44")} />
            <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email (optional)" className={clsx(field, "w-52")} />
            <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="Folder (optional, e.g. ~/.claude-work)" title="Leave empty for ~/.claude-<name>. An existing folder keeps its sign-in." className={clsx(field, "w-64")} />
            <button disabled={!label.trim() || add.isPending} onClick={() => add.mutate()} className="rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent disabled:opacity-40">
              Add
            </button>
            <button onClick={() => setOpen(false)} className="text-[0.75rem] text-faint hover:text-fg">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button onClick={() => { setOpen(true); setMessage(""); }} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[0.75rem] hover:border-accent">
          <Plus size="0.75rem" /> Add a Claude account
        </button>
      )}
      {message && <div className="mt-2 text-[0.75rem] text-muted">{message}</div>}
    </div>
  );
}

function NumberField({ label, value, onChange, suffix }: { label: string; value: number; onChange: (v: number) => void; suffix?: string }) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  return (
    <label className="flex items-center gap-2 text-[0.7812rem]">
      <span className="w-44 text-muted">{label}</span>
      <input value={v} onChange={(e) => setV(e.target.value)} onBlur={() => Number.isFinite(Number(v)) && onChange(Number(v))} className="w-20 rounded-md border border-border bg-surface px-2 py-1" />
      {suffix && <span className="text-faint">{suffix}</span>}
    </label>
  );
}

const TIERS: { id: Tier; label: string; hint: string }[] = [
  { id: "frontier", label: "Frontier", hint: "research, drafting, critique, repair, writing" },
  { id: "workhorse", label: "Workhorse", hint: "verify, export, plain chat" },
  { id: "fast", label: "Fast", hint: "/app questions" },
];

function RoutingPanel({ routing, all, put }: { routing: Routing; all: Connection[]; put: (p: Partial<Settings>) => Promise<void> }) {
  const modelsFor = (runtime: "claude" | "codex") => all.find((c) => c.runtime === runtime)?.models ?? [];
  const setTier = (runtime: "claude" | "codex", tier: Tier, model: string) =>
    void put({ routing: { ...routing, tiers: { ...routing.tiers, [runtime]: { ...routing.tiers[runtime], [tier]: model } } } });
  const byTier = (tier: Tier) =>
    Object.entries(routing.commands)
      .filter(([, [t]]) => t === tier)
      .map(([name]) => `/${name}`)
      .join(" ");
  return (
    <section>
      <h2 className="mb-1 text-[0.875rem] font-medium">Route by command</h2>
      <p className="mb-2 text-[0.7812rem] text-muted">
        The command a message starts with picks the model and effort, on Claude and on Codex alike. A message without a command is chat. Off: every turn uses the connection's own model and the effort meter.
      </p>
      <label className="mb-3 flex items-center gap-2 text-[0.8125rem]">
        <input type="checkbox" checked={routing.enabled} onChange={(e) => void put({ routing: { ...routing, enabled: e.target.checked } })} />
        Route each turn by its command
      </label>
      <label className="mb-3 flex items-center gap-2 text-[0.8125rem]" title="A command works from the run folder, so it does not need the conversation before it. A reply without a command continues the command's conversation, on its tier.">
        <input type="checkbox" checked={routing.fresh} onChange={(e) => void put({ routing: { ...routing, fresh: e.target.checked } })} />
        Start each command in a fresh conversation
      </label>
      {routing.enabled && (
        <div className="space-y-2">
          {TIERS.map((t) => (
            <div key={t.id} className="rounded-md border border-border bg-surface px-3 py-2 text-[0.8125rem]">
              <div className="flex flex-wrap items-center gap-3">
                <span className="w-24 font-medium">{t.label}</span>
                {(["claude", "codex"] as const).map((rt) => {
                  const models = modelsFor(rt);
                  const value = routing.tiers[rt]?.[t.id] ?? "";
                  return (
                    <label key={rt} className="flex items-center gap-1 text-[0.7812rem] text-muted">
                      {rt === "claude" ? "Claude" : "Codex"}
                      <select value={value} onChange={(e) => setTier(rt, t.id, e.target.value)} className="rounded-md border border-border bg-surface px-1.5 py-0.5 text-fg">
                        {!models.some((m) => m.value === value) && <option value={value}>{value || "none"}</option>}
                        {models.map((m) => (
                          <option key={m.value} value={m.value}>
                            {m.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  );
                })}
              </div>
              <div className="mt-1 text-[0.75rem] text-faint">
                {byTier(t.id) || t.hint}
                {routing.chat[0] === t.id && " · chat"}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function ModelsView() {
  const client = useQueryClient();
  const settings = useSettings();
  const connections = useQuery({ queryKey: ["connections"], queryFn: () => api.get<Connection[]>("/api/connections?fresh=true"), staleTime: 0, refetchOnMount: "always" });
  const saved = () => void client.invalidateQueries({ queryKey: ["settings"] });
  const put = async (patch: Partial<Settings> | { caps: Caps }) => {
    await api.put("/api/settings", patch);
    saved();
  };
  const s = settings.data;
  const all = connections.data ?? [];

  const move = (i: number, d: number) => {
    if (!s) return;
    const order = [...s.fallback_order];
    const j = i + d;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    void put({ fallback_order: order, default_connection: order[0] });
  };

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-8 py-6">
        <h1 className="text-[1.125rem] font-medium">Models</h1>
        <p className="mb-4 text-[0.8125rem] text-muted">
          Connect each provider with your own plan or with an API key; you can set up both and choose which new sessions use. Each runs the workspace's skills itself. Codex is the copy that ships with the VS Code ChatGPT extension, shared with any other app that uses it, so its plan windows cover them all and this app never signs it out.
        </p>
        {connections.isLoading && <div className="text-faint">Checking the connections…</div>}
        {s && (
          <div className="space-y-4">
            <ProviderPanel title="Claude Code" ids={["claude-sub", ...(s.claude_accounts ?? []).map((a) => a.id), "claude-api"]} all={all} settings={s} onSaved={saved} put={put}>
              <AddAccount onSaved={saved} />
            </ProviderPanel>
            <ProviderPanel title="Codex" ids={["codex-plan", "codex-api"]} all={all} settings={s} onSaved={saved} put={put} />
          </div>
        )}

        {s && (
          <div className="mt-8 space-y-6">
            <RoutingPanel routing={s.routing} all={all} put={put} />

            <section>
              <h2 className="mb-1 text-[0.875rem] font-medium">Order of use</h2>
              <p className="mb-2 text-[0.7812rem] text-muted">New sessions start on the first. When one runs out, the app offers to continue on the next one here; it never switches by itself.</p>
              <div className="space-y-1">
                {s.fallback_order.map((id, i) => (
                  <div key={id} className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-[0.8125rem]">
                    <span className="w-4 text-faint">{i + 1}</span>
                    <span className="flex-1">
                      {all.find((c) => c.id === id)?.label ?? id}
                      {all.find((c) => c.id === id)?.account && <span className="ml-2 text-[0.75rem] text-faint">{all.find((c) => c.id === id)?.account}</span>}
                      {i === 0 && <span className="ml-2 text-[0.6875rem] text-accent">new sessions start here</span>}
                    </span>
                    <button onClick={() => move(i, -1)} className="text-faint hover:text-fg">
                      <ArrowUp size="0.8125rem" />
                    </button>
                    <button onClick={() => move(i, 1)} className="text-faint hover:text-fg">
                      <ArrowDown size="0.8125rem" />
                    </button>
                    <button
                      onClick={() => {
                        const order = s.fallback_order.filter((x) => x !== id);
                        void put({ fallback_order: order, ...(i === 0 && order[0] ? { default_connection: order[0] } : {}) });
                      }}
                      className="text-faint hover:text-bad"
                    >
                      <X size="0.8125rem" />
                    </button>
                  </div>
                ))}
              </div>
              {all.some((c) => !s.fallback_order.includes(c.id)) && (
                <select value="" onChange={(e) => e.target.value && void put({ fallback_order: [...s.fallback_order, e.target.value], ...(s.fallback_order.length ? {} : { default_connection: e.target.value }) })} className="mt-2 rounded-md border border-border bg-surface px-2 py-1 text-[0.7812rem]">
                  <option value="">Add a connection…</option>
                  {all
                    .filter((c) => !s.fallback_order.includes(c.id))
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                </select>
              )}
            </section>

            <section>
              <h2 className="mb-1 text-[0.875rem] font-medium">Permissions</h2>
              <p className="mb-2 text-[0.7812rem] text-muted">
                How Claude Code asks before acting. Auto, as in VS Code, approves routine work itself; deleting a file always asks you, whatever the mode. Codex runs inside its sandbox without prompts.
              </p>
              <select value={s.permission_mode || "default"} onChange={(e) => void put({ permission_mode: e.target.value })} className="rounded-md border border-border bg-surface px-2 py-1 text-[0.8125rem]">
                <option value="auto">Auto, as in VS Code (asks before deleting)</option>
                <option value="acceptEdits">Accept file edits, ask for commands</option>
                <option value="default">Ask every time</option>
              </select>
            </section>

            <section>
              <h2 className="mb-1 text-[0.875rem] font-medium">Research pipeline</h2>
              <p className="mb-2 text-[0.7812rem] text-muted">
                Run /research-pipeline one stage per fresh conversation: gather, draft, review, finish. The app starts each stage when the one before has left its files, and waits whenever a stage asks you something. Stop ends the chain; /research-pipeline stage=draft run=… re-runs one stage.
              </p>
              <label className="flex items-center gap-2 text-[0.8125rem]">
                <input type="checkbox" checked={s.staged_pipeline} onChange={(e) => void put({ staged_pipeline: e.target.checked })} />
                One conversation per stage
              </label>
            </section>

            <section>
              <h2 className="mb-1 text-[0.875rem] font-medium">Hand over early</h2>
              <p className="mb-2 text-[0.7812rem] text-muted">When a plan window passes this share after a turn, the app offers to hand over before the provider fails mid-step.</p>
              <NumberField label="Offer at" value={s.handover_threshold} onChange={(v) => void put({ handover_threshold: v })} suffix="% used" />
            </section>

            <section>
              <h2 className="mb-1 text-[0.875rem] font-medium">Web caps per session</h2>
              <p className="mb-2 text-[0.7812rem] text-muted">Kept in .claude/monitor.json, shared by the research monitor in VS Code, the Codex hooks and this app.</p>
              <div className="space-y-1.5">
                <NumberField label="Searches" value={s.caps.searchCap} onChange={(v) => void put({ caps: { ...s.caps, searchCap: v } })} />
                <NumberField label="Fetches" value={s.caps.fetchCap} onChange={(v) => void put({ caps: { ...s.caps, fetchCap: v } })} />
                <NumberField label="Warn every" value={s.caps.warnEvery} onChange={(v) => void put({ caps: { ...s.caps, warnEvery: v } })} suffix="calls" />
                <NumberField label="Raise cap adds searches" value={s.caps.raise.searches} onChange={(v) => void put({ caps: { ...s.caps, raise: { ...s.caps.raise, searches: v } } })} />
                <NumberField label="Raise cap adds fetches" value={s.caps.raise.fetches} onChange={(v) => void put({ caps: { ...s.caps, raise: { ...s.caps.raise, fetches: v } } })} />
              </div>
            </section>

            {s.allow_rules.length > 0 && (
              <section>
                <h2 className="mb-1 text-[0.875rem] font-medium">Always allowed in the app</h2>
                <div className="space-y-1">
                  {s.allow_rules.map((r, i) => (
                    <div key={i} className="flex items-center gap-2 font-mono text-[0.75rem]">
                      <span className="flex-1">
                        {r.tool}({r.rule})
                      </span>
                      <button onClick={() => void put({ allow_rules: s.allow_rules.filter((_, j) => j !== i) })} className="text-faint hover:text-bad">
                        <X size="0.8125rem" />
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
