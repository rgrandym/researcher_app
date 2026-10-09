#!/usr/bin/env python3
"""Live usage statusline for the research workspace.

Reads Claude Code's session JSON on stdin and prints four lines:

  Opus · high · claude_research
  ctx  ████████░░░░░░░░  42%  ·  $1.83 · 14m
  5h   ███░░░░░░░░░░░░░  23%  resets 14:32 (2h11m)  ·  7d 41% resets Sat 16
  run  2026-08-12-battery · 2 agents · 31 fetches · 1.2M in / 48k out · 14 sources

The 5h/7d rows mirror the Usage tab in the Claude portal. Token counters are
parsed from the transcript incrementally (byte-offset cache) so this stays fast
on long sessions, and they include subagent (sidechain) usage — which is the
point during a research run, when scouts burn most of the tokens.

Never raises: a statusline that throws prints its traceback into the status bar.
"""

import json
import os
import sys
import time

C = {
    "dim": "\033[2m", "r": "\033[0m", "b": "\033[1m",
    "green": "\033[32m", "yellow": "\033[33m", "red": "\033[31m",
    "cyan": "\033[36m", "mag": "\033[35m", "blue": "\033[34m",
}
CACHE = "/tmp/claude-statusline-cache"


def bar(pct, width=16):
    """Progress bar coloured green→yellow→red as it fills."""
    pct = max(0.0, min(100.0, float(pct or 0)))
    filled = int(round(pct / 100 * width))
    color = C["green"] if pct < 60 else C["yellow"] if pct < 85 else C["red"]
    return f"{color}{'█' * filled}{C['dim']}{'░' * (width - filled)}{C['r']}"


def human(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def countdown(epoch):
    """'2h11m' until the given epoch, or 'now' once it has passed."""
    if not epoch:
        return ""
    secs = int(epoch - time.time())
    if secs <= 0:
        return "now"
    h, m = divmod(secs // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def scan_transcript(path, session_id):
    """Sum tokens/fetches/agents from the transcript, reading only new bytes."""
    blank = {"offset": 0, "inp": 0, "out": 0, "cache_read": 0, "fetches": 0,
             "started": [], "done": []}
    if not path or not os.path.exists(path):
        return blank

    cache_file = f"{CACHE}-{session_id}.json"
    st = blank.copy()
    try:
        with open(cache_file) as fh:
            cached = json.load(fh)
        if cached.get("offset", 0) <= os.path.getsize(path):
            st = cached
    except Exception:
        pass

    started, done = set(st["started"]), set(st["done"])
    with open(path, "rb") as fh:
        fh.seek(st["offset"])
        chunk = fh.read()
        st["offset"] = fh.tell()

    for line in chunk.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        msg = row.get("message")
        if not isinstance(msg, dict):
            continue

        u = msg.get("usage") or {}
        if u:
            st["inp"] += (u.get("input_tokens", 0)
                          + u.get("cache_creation_input_tokens", 0))
            st["out"] += u.get("output_tokens", 0)
            st["cache_read"] += u.get("cache_read_input_tokens", 0)
            stu = u.get("server_tool_use") or {}
            st["fetches"] += (stu.get("web_search_requests", 0)
                              + stu.get("web_fetch_requests", 0))

        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                    started.add(block.get("id"))
                elif block.get("type") == "tool_result":
                    done.add(block.get("tool_use_id"))

    st["started"], st["done"] = sorted(started), sorted(done)
    try:
        with open(cache_file, "w") as fh:
            json.dump(st, fh)
    except Exception:
        pass

    st["active"] = len(started - done)
    return st


def latest_run(project_dir):
    """Newest outputs/<run>/ folder and its evidence count."""
    out = os.path.join(project_dir or ".", "outputs")
    try:
        runs = [d for d in os.listdir(out) if os.path.isdir(os.path.join(out, d))]
    except OSError:
        return None, 0
    if not runs:
        return None, 0
    run = max(runs, key=lambda d: os.path.getmtime(os.path.join(out, d)))
    ev = os.path.join(out, run, "evidence.jsonl")
    n = 0
    try:
        with open(ev, "rb") as fh:
            n = sum(1 for ln in fh if ln.strip())
    except OSError:
        pass
    return run, n


def render(d):
    lines = []
    model = (d.get("model") or {}).get("display_name", "?")
    effort = (d.get("effort") or {}).get("level")
    ws = d.get("workspace") or {}
    project = ws.get("project_dir") or d.get("cwd") or "."

    head = f"{C['b']}{C['mag']}◆ {model}{C['r']}"
    if effort:
        head += f" {C['dim']}·{C['r']} {effort}"
    if d.get("fast_mode"):
        head += f" {C['cyan']}⚡fast{C['r']}"
    head += f" {C['dim']}·{C['r']} {C['blue']}{os.path.basename(project)}{C['r']}"
    if (d.get("agent") or {}).get("name"):
        head += f" {C['dim']}·{C['r']} {C['cyan']}{d['agent']['name']}{C['r']}"
    lines.append(head)

    # context + spend
    cw = d.get("context_window") or {}
    used = cw.get("used_percentage", 0)
    cost = (d.get("cost") or {}).get("total_cost_usd", 0) or 0
    mins = int((d.get("cost") or {}).get("total_duration_ms", 0) or 0) // 60000
    ctx_tok = human(cw.get("total_input_tokens", 0) + cw.get("total_output_tokens", 0))
    lines.append(
        f"{C['dim']}ctx {C['r']}{bar(used)} {used:>3.0f}% {C['dim']}({ctx_tok}){C['r']}"
        f"  {C['dim']}·{C['r']}  {C['b']}${cost:.2f}{C['r']} {C['dim']}· {mins}m{C['r']}"
    )

    # plan limits — the Usage-tab view
    rl = d.get("rate_limits") or {}
    five, seven = rl.get("five_hour") or {}, rl.get("seven_day") or {}
    if five or seven:
        seg = ""
        if five:
            p = five.get("used_percentage", 0)
            at = five.get("resets_at")
            clock = time.strftime("%H:%M", time.localtime(at)) if at else "?"
            seg = (f"{C['dim']}5h  {C['r']}{bar(p)} {p:>3.0f}% "
                   f"{C['dim']}resets {clock} ({countdown(at)}){C['r']}")
        if seven:
            p = seven.get("used_percentage", 0)
            at = seven.get("resets_at")
            day = time.strftime("%a %d", time.localtime(at)) if at else "?"
            color = C["green"] if p < 60 else C["yellow"] if p < 85 else C["red"]
            seg += (f"  {C['dim']}·{C['r']}  {C['dim']}7d{C['r']} {color}{p:.0f}%{C['r']} "
                    f"{C['dim']}resets {day}{C['r']}")
        lines.append(seg)

    # research run progress
    st = scan_transcript(d.get("transcript_path"), d.get("session_id", "x"))
    run, sources = latest_run(project)
    bits = []
    if run:
        bits.append(f"{C['cyan']}{run}{C['r']}")
    if st.get("active"):
        bits.append(f"{C['yellow']}⟳ {st['active']} agent"
                    f"{'s' if st['active'] > 1 else ''}{C['r']}")
    if st["fetches"]:
        bits.append(f"{st['fetches']} fetches")
    if st["inp"] or st["out"]:
        bits.append(f"{human(st['inp'])} in / {human(st['out'])} out")
    if run:
        bits.append(f"{sources} sources")
    if bits:
        lines.append(f"{C['dim']}run {C['r']}" + f" {C['dim']}·{C['r']} ".join(bits))

    return lines


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("statusline: no input")
        return
    try:
        print("\n".join(render(data)))
    except Exception as exc:  # never let the bar show a traceback
        model = (data.get("model") or {}).get("display_name", "?")
        cost = (data.get("cost") or {}).get("total_cost_usd", 0) or 0
        print(f"{model} · ${cost:.2f} · statusline error: {type(exc).__name__}")


if __name__ == "__main__":
    main()
