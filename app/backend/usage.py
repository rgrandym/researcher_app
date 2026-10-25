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

import datetime as dt
import hashlib
import json
import os
import re
import select
import subprocess
import threading
import time
import urllib.error
import urllib.request
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
_claude_file_lock = threading.Lock()

def _claude_file(account: str = "claude-sub") -> Any:
    """Each Claude account has its own plan windows; the default keeps its old file name."""
    name = "usage-claude.json" if account == "claude-sub" else f"usage-{account}.json"
    return config.data_dir() / name


# Live reads of a Claude plan: the same endpoint Claude Code's /usage view reads, with the
# account's own sign-in from the Keychain. The token is only read, never refreshed: a
# refresh outside Claude Code spends the refresh token, and the account is signed out.
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
OAUTH_BETA = "oauth-2025-04-20"
MIN_FETCH_S = 15  # several views poll the same account; one read serves them all
BACKOFF_S = 300  # after the endpoint refuses (429 or an error), before trying again
_fetch_state: dict[str, dict[str, Any]] = {}
_fetch_lock = threading.Lock()
_token_owner: dict[str, str] = {}  # sha256 of an access token -> the email it signs in


def keychain_service(config_dir: str) -> str:
    """Claude Code's Keychain entry for a config folder: the plain name for the default
    folder, a hash of `CLAUDE_CONFIG_DIR` (as given) for any other."""
    if not config_dir:
        return "Claude Code-credentials"
    return f"Claude Code-credentials-{hashlib.sha256(config_dir.encode()).hexdigest()[:8]}"


def _oauth_token(config_dir: str) -> tuple[str, float] | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", keychain_service(config_dir), "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode:
            return None
        oauth = json.loads(out.stdout).get("claudeAiOauth") or {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    token, expires = oauth.get("accessToken"), oauth.get("expiresAt")
    if not isinstance(token, str) or not isinstance(expires, (int, float)):
        return None
    return token, float(expires) / 1000


def _get(url: str, token: str) -> Any:
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "anthropic-beta": OAUTH_BETA,
        "Content-Type": "application/json", "User-Agent": "research-app",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def fetch_claude_usage(account: str, config_dir: str, expected_email: str) -> str:
    """Read the plan's windows now and store them. Returns "" on success, else why not.

    At most one read per account every MIN_FETCH_S; a refusal backs off for BACKOFF_S.
    The token's owner is checked against the account's sign-in before anything is stored,
    so one account's windows can never be shown under another."""
    if not expected_email:
        return "not signed in"
    with _fetch_lock:
        state = _fetch_state.setdefault(account, {})
        if time.time() < float(state.get("next", 0)):
            return str(state.get("why", ""))
        state["next"] = time.time() + MIN_FETCH_S
        state["why"] = ""
    found = _oauth_token(config_dir)
    if found is None:
        why = "no Claude Code sign-in in the Keychain for this account"
    elif found[1] <= time.time() + 30:
        why = "the sign-in token has expired; Claude Code renews it on the next turn"
    else:
        why = _fetch_with(account, found[0], expected_email.strip().casefold())
    if why:
        with _fetch_lock:
            _fetch_state[account].update(next=time.time() + (BACKOFF_S if "refused" in why else MIN_FETCH_S), why=why)
    return why


def _fetch_with(account: str, token: str, email: str) -> str:
    key = hashlib.sha256(token.encode()).hexdigest()
    try:
        if key not in _token_owner:
            profile = _get(PROFILE_URL, token)
            _token_owner[key] = str((profile.get("account") or {}).get("email") or "").strip().casefold()
        if _token_owner[key] != email:
            return f"the Keychain sign-in belongs to {_token_owner[key] or 'another account'}"
        body = _get(USAGE_URL, token)
    except urllib.error.HTTPError as exc:
        return f"the usage endpoint refused the read ({exc.code})"
    except (OSError, ValueError) as exc:
        return f"the usage endpoint could not be reached ({exc.__class__.__name__})"
    incoming: dict[str, Any] = {}
    for name in _WINDOW_NAMES:
        raw = body.get(name) if isinstance(body, dict) else None
        if not isinstance(raw, dict) or not isinstance(raw.get("utilization"), (int, float)):
            continue
        reset = raw.get("resets_at")
        try:
            reset_at = dt.datetime.fromisoformat(reset).timestamp() if isinstance(reset, str) else None
        except ValueError:
            reset_at = None
        percent = float(raw["utilization"])
        incoming[name] = {
            "utilization": percent / 100,
            "resetsAt": reset_at,
            "status": "rejected" if percent >= 100 or raw.get("locked_reason") else "allowed",
        }
    if not incoming:
        return "the usage endpoint returned no plan windows"
    with _claude_file_lock:
        _claude_file(account).write_text(json.dumps({
            "account_email": email, "observed_at": time.time(), "source": "live", **incoming,
        }))
    return ""


def import_claude_local_usage(account: str, config_dir: str, expected_email: str) -> None:
    """Seed a connection from Claude Code's own account-bound usage snapshot, if present.

    Claude Code writes this after its usage view reads the plan. The snapshot carries the
    account UUID and fetch time, so an older login cannot be mistaken for this one.
    """
    if not expected_email:
        return
    path = Path(config_dir) / ".claude.json" if config_dir else Path.home() / ".claude.json"
    try:
        local = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    identity = local.get("oauthAccount") or {}
    snapshot = local.get("cachedUsageUtilization") or {}
    if not isinstance(identity, dict) or not isinstance(snapshot, dict):
        return
    email = str(identity.get("emailAddress") or "").strip().casefold()
    if email != expected_email.strip().casefold() or snapshot.get("accountUuid") != identity.get("accountUuid"):
        return
    fetched = snapshot.get("fetchedAtMs")
    windows = snapshot.get("utilization")
    if not isinstance(fetched, (int, float)) or not isinstance(windows, dict):
        return
    observed_at = float(fetched) / 1000
    incoming: dict[str, Any] = {}
    for key in _WINDOW_NAMES:
        raw = windows.get(key)
        if not isinstance(raw, dict) or not isinstance(raw.get("utilization"), (int, float)):
            continue
        reset = raw.get("resets_at")
        try:
            reset_at = dt.datetime.fromisoformat(reset).timestamp() if isinstance(reset, str) else None
        except ValueError:
            reset_at = None
        percent = float(raw["utilization"])
        incoming[key] = {
            "utilization": percent / 100,
            "resetsAt": reset_at,
            "status": "rejected" if percent >= 100 else "allowed",
        }
    if not incoming:
        return
    with _claude_file_lock:
        try:
            stored = json.loads(_claude_file(account).read_text())
        except (OSError, ValueError):
            stored = {}
        if stored.get("account_email") == email and float(stored.get("observed_at") or 0) >= observed_at:
            return
        _claude_file(account).write_text(json.dumps({
            "account_email": email, "observed_at": observed_at, **incoming,
        }))


def record_claude_limit(
    info: dict[str, Any], account: str = "claude-sub", account_email: str = ""
) -> UsageWindows:
    """Store one `rate_limit_info` from a stream-json `rate_limit_event`."""
    with _claude_file_lock:
        try:
            stored = json.loads(_claude_file(account).read_text())
        except (OSError, ValueError):
            stored = {}
        if account_email:
            normalized = account_email.strip().casefold()
            if stored.get("account_email") != normalized:
                stored = {}  # an earlier sign-in's windows belong to a different account
            stored["account_email"] = normalized
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
        _claude_file(account).write_text(json.dumps(stored))
    return claude_usage(account, expected_email=account_email or None)


def claude_usage(account: str = "claude-sub", expected_email: str | None = None) -> UsageWindows:
    try:
        stored = json.loads(_claude_file(account).read_text())
    except (OSError, ValueError):
        return UsageWindows(note="No verified usage snapshot yet. Open /usage in Claude Code to load one.")
    if expected_email and stored.get("account_email") != expected_email.strip().casefold():
        return UsageWindows(note="No verified usage for this sign-in. Open /usage in Claude Code to load it.")
    windows = []
    reset_since_report = False
    for key, name in _WINDOW_NAMES.items():
        win = stored.get(key)
        if not isinstance(win, dict):
            continue
        util = win.get("utilization")
        resets = win.get("resetsAt")
        status = win.get("status")
        if resets and float(resets) < time.time():
            util, status = 0.0, "allowed"
            reset_since_report = True
        windows.append(
            UsageWindow(
                name=name,
                used_percent=round(float(util) * (100 if float(util) <= 1 else 1), 1) if util is not None else None,
                resets_at=float(resets) if resets else None,
                status=status,
            )
        )
    return UsageWindows(
        windows=windows,
        updated_at=stored.get("observed_at"),
        note="A window reset since the last report; usage elsewhere has not been checked."
        if reset_since_report else "",
    )


# ------------------------------------------------------------------ Codex

_codex_cache: dict[str, Any] = {}
_codex_cache_lock = threading.Lock()
USAGE_TIMEOUT_S = 20


def codex_usage(binary: str | None, ttl: float = 10) -> UsageWindows:
    """ChatGPT plan windows through `codex app-server`. Cached
    briefly while Activity is open; the call starts a process but no model turn."""
    if binary is None:
        return UsageWindows(note="Codex not found.")
    hit = _codex_cache.get("value")
    if hit and time.time() - _codex_cache.get("at", 0) < ttl:
        return hit  # type: ignore[no-any-return]
    if not _codex_cache_lock.acquire(blocking=False):
        return hit or UsageWindows(note="Reading Codex usage…")
    try:
        hit = _codex_cache.get("value")
        if hit and time.time() - _codex_cache.get("at", 0) < ttl:
            return hit  # type: ignore[no-any-return]
        try:
            value = _read_codex_usage(binary)
        except (OSError, ValueError, RuntimeError) as exc:
            value = hit or UsageWindows(note=f"Could not read Codex usage: {exc}")
            _codex_cache.update(value=value, at=time.time())
            return value
        _codex_cache.update(value=value, at=time.time())
        return value
    finally:
        _codex_cache_lock.release()


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


def codex_child_threads(thread_id: str | None, since: float) -> list[dict[str, str]]:
    """Subagent threads a Codex thread spawned since `since` (epoch seconds), from their
    rollouts' first line. `codex exec --json` streams the waits on a subagent but not the
    `spawn_agent` call itself, so the rollouts are the record that one was launched."""
    if not thread_id:
        return []
    out = []
    for path in _codex_sessions_dir().glob("*/*/*/rollout-*.jsonl"):
        try:
            if path.stat().st_mtime < since:
                continue
            with path.open(errors="replace") as fh:
                meta = (json.loads(fh.readline()).get("payload") or {})
        except (OSError, ValueError, AttributeError):
            continue
        if meta.get("parent_thread_id") != thread_id or meta.get("id") == thread_id:
            continue
        spawn = ((meta.get("source") or {}).get("subagent") or {}).get("thread_spawn") or {}
        out.append({
            "id": str(meta.get("id") or path.stem),
            "role": str(spawn.get("agent_role") or meta.get("agent_role") or "subagent"),
            "path": str(spawn.get("agent_path") or ""),
        })
    return sorted(out, key=lambda c: c["id"])


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
