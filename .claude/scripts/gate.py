#!/usr/bin/env python3
"""gate.py — run the mechanical gates on a report and report hard failures.

Every rule in this workspace that a script can check is checked here, in one
place, so that no skill has to remember a list of commands and no agent can
ship past a gate by forgetting it.

    python3 .claude/scripts/gate.py <run>/report.md      # check one document
    python3 .claude/scripts/gate.py --hook               # called by the hook
    python3 .claude/scripts/gate.py --hook --codex       # called by Codex's hook

Hard failures (exit 1, or exit 2 under --hook so the agent is told):

    VOICE      a construction the author has banned, from voice.py lint
    ERROR      a dangling, fabricated or unlisted citation, from audit_citations
    ERROR      a malformed or uncited figure spec, from figures.py check
    ARTIFACT   pipeline vocabulary left in the deliverable

Advisory output (ECHO, DICTION, DRIFT, SHAPE, WARN) is printed but never fails
a build: only a reader can tell a term of art from a lazy verb.

After the checks, `voice.py mark` records what the agent just wrote. That mirror
is what lets saved_check.py tell an unsaved buffer from a real edit, and lets
voice.py learn tell the author's prose from the agent's. Running it here rather
than asking each skill to remember it is the difference between a mechanism and
a good intention.

Under --hook, stdin carries the Claude Code tool payload; a path that is not a
master document of its run exits 0 in silence. Which documents those are is
declared in `<run>/.run.json` and read through runmeta.py: report.md and
draft.md by default. Only the hook updates the
mirror, because only the hook knows an agent has just written: a manual run of
this script after the author has edited by hand must leave their edit visible
to voice.py learn.

Codex sends the same payload shape with two differences. Its apply_patch tool
names no file_path: the files it touched are the `*** Add File:` and
`*** Update File:` headers of the patch in tool_input.command, relative to the
payload's cwd. And Codex may read a hook's stdout as JSON, so under --codex a
pass prints nothing; a failure is reported exactly as for Claude Code, exit 2
with the findings on stderr, which Codex hands to the agent.

A write through the shell carries no file_path, so the payload names no
document and the gate would never see it. Those calls are caught by mtime
instead: any run document newer than its `.gate-stamp` is gated, once per
change. That path never marks the mirror, because a shell command is not
evidence that an agent wrote the file and the author's own save reaches the
gate the same way.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".claude" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import runmeta                                            # noqa: E402

# Documents worth gating: anything a run declares as a master. A research run
# declares report.md and draft.md by default.
TARGET = re.compile(r"outputs/[^/]+/[^/]+\.md$")
# The file headers of a Codex apply_patch.
PATCH_FILE = re.compile(r"^\*\*\* (?:Add File|Update File|Move to): (.+?)\s*$", re.M)


def payload_paths(payload):
    """Every file a tool call names: Claude Code's (and Codex's Edit/Write)
    file_path, or the files a Codex apply_patch adds or updates."""
    tool_input = payload.get("tool_input") or {}
    if isinstance(tool_input, str):
        tool_input = {"command": tool_input}
    if tool_input.get("file_path"):
        return [tool_input["file_path"]]
    patch = tool_input.get("command") or tool_input.get("input") or ""
    if not isinstance(patch, str):
        return []
    cwd = Path(payload.get("cwd") or ROOT)
    return [str(Path(f) if Path(f).is_absolute() else cwd / f)
            for f in PATCH_FILE.findall(patch)]


def gated(doc: Path) -> bool:
    """True if this path is a master document of the run that contains it."""
    return runmeta.is_master(doc)


def run(args):
    """Run a checker, return (exit code, stdout+stderr)."""
    p = subprocess.run([sys.executable, *args], capture_output=True, text=True,
                       cwd=ROOT)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def gate(doc: Path, mark: bool):
    """Check one document. Returns (hard failure lines, advisory lines).

    `mark` updates the mirror and is true only when an agent has just written.
    A manual inspection never marks: the mirror records what the agent last
    wrote, and overwriting it after a hand edit would hide that edit from
    voice.py learn and from saved_check.py.
    """
    run_dir = doc.parent
    hard, soft = [], []

    code, out = run([str(SCRIPTS / "voice.py"), "lint", str(doc)])
    for line in out.splitlines():
        if line.startswith("VOICE"):
            hard.append(line)
        elif line.split(" ")[0] in ("DRIFT", "SHAPE", "ECHO", "ECHO-NEAR",
                                    "OPENER", "DICTION"):
            soft.append(line)

    code, out = run([str(SCRIPTS / "audit_citations.py"), str(run_dir), doc.name])
    for line in out.splitlines():
        if line.startswith("ERROR"):
            hard.append(line)
        elif line.startswith("WARN"):
            soft.append(line)

    code, out = run([str(SCRIPTS / "figures.py"), "check", str(doc)])
    hard += [l for l in out.splitlines() if l.startswith("ERROR")]

    # Record what the agent wrote, whatever the verdict. The mirror is a record
    # of authorship, not of quality.
    if mark:
        run([str(SCRIPTS / "voice.py"), "mark", str(doc)])

    return hard, soft


def stamp_of(doc):
    return doc.parent / f".gate-stamp-{doc.name}"


# A shell write is recognised by its recency: the hook fires immediately after
# the command that made it. Anything older is a file that was already there,
# and gating those would turn every shell command into an audit of the whole
# outputs tree, including drafts the author supplied and runs long finished.
RECENT = 120        # seconds


def stale_docs(now):
    """Run documents a shell command has just written.

    The fallback for a write the payload cannot name: a heredoc, a sed, a short
    script. A document the gate has not seen before is stamped and skipped, so
    installing this does not fire on every run in the tree; after that, only a
    change made in the last RECENT seconds is gated. Ordered newest first.
    """
    out = []
    for doc in ROOT.glob("outputs/*/*.md"):
        if not gated(doc):
            continue
        stamp = stamp_of(doc)
        mtime = doc.stat().st_mtime
        if not stamp.exists() or mtime <= stamp.stat().st_mtime:
            stamp_of(doc).write_text("")     # baseline, silently
            continue
        if now - mtime > RECENT:
            stamp_of(doc).write_text("")     # changed, but not by this command
            continue
        out.append(doc)
    return sorted(out, key=lambda d: d.stat().st_mtime, reverse=True)


def main():
    hook = "--hook" in sys.argv
    quiet = "--codex" in sys.argv          # Codex may parse stdout as JSON
    if hook:
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0
        paths = payload_paths(payload)
        docs = [Path(p) for p in paths
                if TARGET.search(p.replace("\\", "/")) and gated(Path(p))]
        if not docs:
            # No document in the payload: a shell write, or a tool call that
            # touched nothing. Fall back to what changed on disk.
            if paths:
                return 0
            stale = stale_docs(time.time())
            if not stale:
                return 0
            docs = stale[:1]
            hook = "shell"
    else:
        args = [a for a in sys.argv[1:] if not a.startswith("-")]
        if not args:
            return int(bool(sys.stderr.write(__doc__)))
        docs = [Path(args[0])]

    return max((verdict(doc, hook, quiet) for doc in docs if doc.exists()),
               default=0)


def verdict(doc, hook, quiet):
    """Gate one document and report it; returns the exit code."""
    hard, soft = gate(doc, mark=(hook is True))
    if hook:
        stamp_of(doc).write_text("")

    if not hard:
        if quiet:
            return 0
        # Advisory notes go to the transcript; they fail nothing. The shell
        # fallback prints the summary line only: it can fire on any command,
        # and 20 advisory lines per shell call trains the reader to skip them.
        if hook != "shell":
            for line in soft[:20]:
                print(line)
        print(f"gate: {doc.name} passes the mechanical gates "
              f"({len(soft)} advisory note(s))")
        return 0

    counts = {}
    for line in hard:
        counts[line.split()[0]] = counts.get(line.split()[0], 0) + 1

    report = [f"gate: {doc} FAILS {len(hard)} hard check(s): "
              + ", ".join(f"{n}× {k}" for k, n in counts.items()), ""]
    report += hard[:40]
    if len(hard) > 40:
        report.append(f"… and {len(hard) - 40} more. "
                      f"Run: python3 .claude/scripts/gate.py {doc}")
    report += [
        "",
        "Fix these before the document goes any further. A VOICE line is a "
        "construction the author has banned: rebuild the sentence around its "
        "real subject rather than swapping the flagged token. Doctrine: "
        ".claude/voice/profile.md and .claude/references/diction.md.",
    ]
    sys.stderr.write("\n".join(report) + "\n")
    return 2 if hook else 1


if __name__ == "__main__":
    sys.exit(main())
