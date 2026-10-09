export function clock(epoch: number | null | undefined): string {
  if (!epoch) return "";
  return new Date(epoch * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export function day(epoch: number | null | undefined): string {
  if (!epoch) return "";
  const d = new Date(epoch * 1000);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return clock(epoch);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function resetLabel(epoch: number | null | undefined): string {
  if (!epoch) return "";
  const d = new Date(epoch * 1000);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? clock(epoch) : d.toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

export function tokens(n: number | null | undefined): string {
  const v = n ?? 0;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${Math.round(v / 1e3)}k`;
  return String(v);
}

export function bytes(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} kB`;
  return `${n} B`;
}

export function elapsed(from: number | null, to?: number | null): string {
  if (!from) return "";
  const secs = Math.max(0, Math.round((to ?? Date.now() / 1000) - from));
  const m = Math.floor(secs / 60);
  return m ? `${m}m ${secs % 60}s` : `${secs}s`;
}

export const SHORT_LABEL: Record<string, string> = {
  "claude-sub": "Claude Code",
  "claude-api": "Claude Code (key)",
  "codex-plan": "Codex",
  "codex-api": "Codex (key)",
};

export function label(conn: string | null | undefined): string {
  return conn ? (SHORT_LABEL[conn] ?? conn) : "";
}
