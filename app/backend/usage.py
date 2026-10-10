"""Plan windows per provider, and the classifier that tells a spent plan from any other
error.

A wrong classification either strands the author (a limit read as an ordinary error, so
no switch is offered) or switches provider on an ordinary error. The patterns are tested
against fixtures in tests/fixtures/.

No function here makes a model call. Claude Code reports its windows in the
`rate_limit_event`s of every turn, which the app records; Codex reports them through
`codex app-server`.
"""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import time
from pathlib import Path
from typing import Any

from backend import config
from backend.providers.base import ErrorKind, UsageWindow, UsageWindows

LIMIT = re.compile(
    r"usage limit|hit your (usage )?limit|limit reached|limit (has been )?exceeded|rate[ _-]?limit"
    r"|quota|out of (extra )?usage|credit balance is too low|insufficient_quota|\b429\b"
    r"|usage_limit_reached|plan limit",
    re.I,
)
AUTH = re.compile(
    r"not (logged|signed) in|log ?in again|please (log|sign) ?in|unauthori[sz]ed|\b401\b|\b403\b"
    r"|invalid (x-)?api[ -]?key|authentication|oauth token|token (has )?expired|/login",
    re.I,
)
CONTEXT = re.compile(
    r"prompt is too long|context (length|window)|too many tokens|maximum context", re.I
)
NETWORK = re.compile(
    r"ECONN\w*|ENOTFOUND|EAI_AGAIN|network|fetch failed|socket hang up|connection (reset|refused|error)"
    r"|timed? ?out|getaddrinfo|offline",
    re.I,
)


def classify(text: str) -> ErrorKind:
    """The kind of a provider error from its message. Limit first: a quota message often
    also mentions the account or the request, and a spent plan must never read as auth."""
    if LIMIT.search(text):
        return "limit"
    if AUTH.search(text):
        return "auth"
    if CONTEXT.search(text):
        return "context"
    if NETWORK.search(text):
        return "network"
    return "other"


def reset_from_text(text: str, now: float | None = None) -> float | None:
    """A reset time named in a limit message: an epoch after `|` (older Claude Code), or a
    clock time ("try again at 10:21 PM", "resets 22:21"), the next time it comes round."""
    m = re.search(r"\|(\d{10})\b", text)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(?:at|resets?(?: at)?)\s+(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?", text, re.I)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    half = (m.group(3) or "").lower().replace(".", "")
    if half == "pm" and hour < 12:
        hour += 12
    elif half == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59 or (not half and not m.group(2)):
        return None  # a bare number is not a clock time
    base = time.localtime(now if now is not None else time.time())
    target = time.mktime((base.tm_year, base.tm_mon, base.tm_mday, hour, minute, 0, 0, 0, -1))
    return target + 86400 if target <= (now if now is not None else time.time()) else target


# ------------------------------------------------------------------ Claude Code

_WINDOW_NAMES = {
    "five_hour": "5h",
    "seven_day": "7d",
    "seven_day_opus": "7d opus",
    "seven_day_sonnet": "7d sonnet",
}


def _claude_file() -> Any:
    return config.data_dir() / "usage-claude.json"


def record_claude_limit(info: dict[str, Any]) -> UsageWindows:
    """Store one `rate_limit_info` from a stream-json `rate_limit_event`."""
    try:
        stored = json.loads(_claude_file().read_text())
    except (OSError, ValueError):
        stored = {}
    unified = info.get("unifiedWindows")
    if isinstance(unified, dict):
        for key, win in unified.items():
            if isinstance(win, dict):
                stored[key] = {**stored.get(key, {}), **win}
    kind = info.get("rateLimitType")
    if kind:
        stored[str(kind)] = {
            **stored.get(str(kind), {}),
            "status": info.get("status"),
            "resetsAt": info.get("resetsAt"),
            **({"utilization": info["utilization"]} if info.get("utilization") is not None else {}),
        }
    stored["observed_at"] = time.time()
    _claude_file().write_text(json.dumps(stored))
    return claude_usage()


def claude_usage() -> UsageWindows:
    try:
        stored = json.loads(_claude_file().read_text())
    except (OSError, ValueError):
        return UsageWindows(note="Shown after the first Claude Code turn.")
    windows = []
    for key, name in _WINDOW_NAMES.items():
        win = stored.get(key)
        if not isinstance(win, dict):
            continue
        util = win.get("utilization")
        resets = win.get("resetsAt")
        if resets and float(resets) < time.time():
            util = 0.0  # the window has reset since it was observed
        windows.append(
            UsageWindow(
                name=name,
                used_percent=round(float(util) * 100, 1) if util is not None else None,
                resets_at=float(resets) if resets else None,
                status=win.get("status"),
            )
        )
    return UsageWindows(windows=windows, updated_at=stored.get("observed_at"))


# ------------------------------------------------------------------ Codex

_codex_cache: dict[str, Any] = {}
USAGE_TIMEOUT_S = 20


def codex_usage(binary: str | None, ttl: float = 60) -> UsageWindows:
    """ChatGPT plan windows through `codex app-server`. Cached
    for a minute: the call starts a process but no model turn."""
    if binary is None:
        return UsageWindows(note="Codex not found.")
    hit = _codex_cache.get("value")
    if hit and time.time() - _codex_cache.get("at", 0) < ttl:
        return hit  # type: ignore[no-any-return]
    try:
        value = _read_codex_usage(binary)
    except (OSError, ValueError, RuntimeError) as exc:
        return UsageWindows(note=f"Could not read Codex usage: {exc}")
    _codex_cache.update(value=value, at=time.time())
    return value


def _read_codex_usage(binary: str) -> UsageWindows:
    proc = subprocess.Popen(
        [binary, "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=config.child_env(),
    )
    try:
        assert proc.stdin and proc.stdout
        requests = [
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "research-app", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            },
            {"method": "initialized"},
            {
                "id": 2,
                "method": "account/rateLimits/read",
                "params": {"excludeResetCreditDetails": True},
            },
        ]
        for request in requests:
            proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + USAGE_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("timed out")
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                raise RuntimeError("timed out")
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("app-server stopped")
            message = json.loads(line)
            if message.get("id") == 2:
                if "error" in message:
                    raise RuntimeError(str(message["error"]))
                return codex_windows(message.get("result") or {})
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def codex_windows(rate_response: dict[str, Any]) -> UsageWindows:
    limits = rate_response.get("rateLimits") or {}
    windows = []
    for key in ("primary", "secondary"):
        win = limits.get(key)
        if not isinstance(win, dict):
            continue
        minutes = int(win.get("windowDurationMins") or 0)
        name = f"{minutes // 60}h" if minutes and minutes < 1440 else f"{minutes // 1440}d"
        windows.append(
            UsageWindow(
                name=name,
                used_percent=float(win.get("usedPercent") or 0),
                resets_at=float(win["resetsAt"]) if win.get("resetsAt") else None,
            )
        )
    note = f"ChatGPT {limits.get('planType')} plan" if limits.get("planType") else ""
    return UsageWindows(windows=windows, updated_at=time.time(), note=note)


def over_threshold(usage: UsageWindows | None, threshold: float) -> UsageWindow | None:
    """The first window past the early-handover threshold, if any."""
    if usage is None:
        return None
    for win in usage.windows:
        if win.used_percent is not None and win.used_percent >= threshold:
            return win
    return None


# ------------------------------------------------------------------ Codex threads' own record

_rollout_cache: dict[str, tuple[float, dict[str, int]]] = {}


def _codex_sessions_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"


def codex_thread_usage(thread_id: str | None) -> dict[str, int] | None:
    """Tokens and web searches of one Codex thread and every subagent thread it spawned, from
    the rollout files Codex writes as it works (~/.codex/sessions/.../rollout-*-<id>.jsonl).

    The stream's `turn.completed` carries usage only for a turn that completes, and only the
    main thread's: a turn stopped by a usage limit, and the subagents' work, never reach it.
    The rollouts hold both, so the activity panel reads them. None when no rollout is found."""
    if not thread_id:
        return None
    base = _codex_sessions_dir()
    main = next(iter(base.glob(f"*/*/*/rollout-*-{thread_id}.jsonl")), None)
    if main is None:
        return None
    # Subagent threads start after their parent: rollout names begin with the start time
    # ("rollout-2026-10-09T17-20-57-"), so only later rollouts can be its children.
    started = main.name[: len("rollout-2026-10-09T17-20-57")]
    files = [main] + [
        p for p in sorted(base.glob("*/*/*/rollout-*.jsonl")) if p != main and p.name >= started
    ]
    child = re.compile(r'"parent_thread_id"\s*:\s*"' + re.escape(thread_id) + '"')
    newest = max(p.stat().st_mtime for p in files)
    hit = _rollout_cache.get(thread_id)
    if hit and hit[0] >= newest:
        return hit[1]
    totals = {"tokens_in": 0, "tokens_out": 0, "searches": 0, "threads": 0}
    for path in files:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if path != main and not child.search(text[:20000]):
            continue  # another thread's rollout
        last: dict[str, Any] | None = None
        for line in text.splitlines():
            if '"token_count"' not in line and '"web_search' not in line:
                continue
            try:
                payload = json.loads(line).get("payload") or {}
            except ValueError:
                continue
            kind = payload.get("type")
            if kind == "token_count" and payload.get("info"):
                last = payload["info"].get("total_token_usage") or last
            elif kind in ("web_search_call", "web_search"):
                totals["searches"] += 1
        totals["threads"] += 1
        if last:
            totals["tokens_in"] += int(last.get("input_tokens") or 0)
            totals["tokens_out"] += int(last.get("output_tokens") or 0)
    _rollout_cache[thread_id] = (newest, totals)
    return totals
