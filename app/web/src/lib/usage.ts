// When to read a connection's plan windows. One policy for every place that shows them:
//   - the connection a running task is using: every 20 s, so the bars track it live;
//   - once its task stops, no more reads until the next reset;
//   - a connection nothing is using: read once, then again only when a window resets;
//   - when a task stops: one last read, so the bars show where it ended.

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { Usage } from "./types";

export const LIVE_POLL_MS = 20_000;
// setTimeout misfires beyond ~24.8 days; no plan window is that long.
const MAX_WAIT_MS = 2 ** 31 - 1;

const now = () => Date.now() / 1000;

function nextReset(u: Usage | undefined): number | null {
  const t = now();
  const times = (u?.windows ?? []).map((w) => w.resets_at).filter((r): r is number => r != null && r > t);
  return times.length ? Math.min(...times) : null;
}

export function usageInterval(u: Usage | undefined, live: boolean): number | false {
  // A spent plan has had its final read: nothing changes until a window resets.
  const spent = (u?.windows ?? []).some((w) => w.status === "rejected" || (w.used_percent ?? 0) >= 100);
  if (live && !spent) return LIVE_POLL_MS;
  const reset = nextReset(u);
  return reset == null ? false : Math.min(MAX_WAIT_MS, (reset - now()) * 1000 + 2_000);
}

export function usageQuery(conn: string, live: boolean) {
  return {
    queryKey: ["usage", conn],
    queryFn: () => api.get<Usage>(`/api/usage/${conn}`),
    refetchInterval: (query: { state: { data: Usage | undefined } }) => usageInterval(query.state.data, live),
    retry: false,
    enabled: Boolean(conn),
  };
}

/** The final read when a task on `conn` stops, and a fresh one when a task starts on it. */
export function useUsageEdges(conn: string, live: boolean): void {
  const client = useQueryClient();
  const was = useRef(live);
  useEffect(() => {
    if (was.current !== live && conn) void client.invalidateQueries({ queryKey: ["usage", conn] });
    was.current = live;
  }, [client, conn, live]);
}
