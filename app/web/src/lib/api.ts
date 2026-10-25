// REST calls to the backend. Every call carries the per-launch token, which arrives in
// the window's URL (`?token=`, from the launcher) or, under dev.sh, in VITE_APP_TOKEN.

function readToken(): string {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    try {
      sessionStorage.setItem("research-token", fromUrl);
    } catch {
      /* storage may be unavailable; the token still works for this page */
    }
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.toString());
    return fromUrl;
  }
  try {
    const stored = sessionStorage.getItem("research-token");
    if (stored) return stored;
  } catch {
    /* fall through */
  }
  return (import.meta.env.VITE_APP_TOKEN as string | undefined) ?? "";
}

export const TOKEN = readToken();

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: {
      "X-App-Token": TOKEN,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, res.status);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

/** A text file and its modification time, for edits that must not overwrite a newer save. */
export async function getText(path: string): Promise<{ text: string; mtime: number | null }> {
  const res = await fetch(path, { headers: { "X-App-Token": TOKEN } });
  if (!res.ok) throw new ApiError(res.statusText, res.status);
  const mtime = res.headers.get("X-Mtime");
  return { text: await res.text(), mtime: mtime ? Number(mtime) : null };
}

export function renderedUrl(run: string, style: string, cite: boolean, path: string, download = false, built?: number): string {
  const params: Record<string, string> = { style, cite: String(cite), path, token: TOKEN };
  if (built !== undefined) params.v = String(built);
  if (download) params.download = "true";
  return `/api/runs/${encodeURIComponent(run)}/rendered?${new URLSearchParams(params).toString()}`;
}

export const q = (params: Record<string, string>) => new URLSearchParams(params).toString();

export function fileUrl(run: string, path: string): string {
  return `/api/runs/${encodeURIComponent(run)}/file?${q({ path, token: TOKEN })}`;
}
