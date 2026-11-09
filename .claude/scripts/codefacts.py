#!/usr/bin/env python3
"""codefacts.py: what a project already knows about a codebase, so no range of code
is read twice and no search is repeated.

Every code document in a project shares one record, kept beside the project's code
documents (`<project>/code-docs/.facts.jsonl` and `.reads.jsonl`; `<run>/notes/` for a
run outside a project). It holds two kinds of row:

  fact   a statement about the code, the file and line range that show it, the exact
         quote from those lines, and a hash of the file when it was recorded
  read   a line range an agent has read, with the file's hash at the time

A fact is accepted only if its quote is in the cited lines, so the record cannot hold
an invented claim. When a file changes, a fact whose quote is still there is moved to
its new lines; one whose quote is gone is stale and its range counts as unread.

    python3 .claude/scripts/codefacts.py known  <run> <file> [<file> ...] [--brief]
    python3 .claude/scripts/codefacts.py unread <run> <file> [<file> ...]
    python3 .claude/scripts/codefacts.py add    <run> <facts.jsonl> --by <name>
    python3 .claude/scripts/codefacts.py read   <run> <file> <start-end> [...] --by <name>
    python3 .claude/scripts/codefacts.py search <run> <regex> [<path> ...]   # grep, cached per code version
    python3 .claude/scripts/codefacts.py import <run>     # the project's evidence rows about the code
    python3 .claude/scripts/codefacts.py stats  <run>

`add` takes a JSON-lines file, one fact per line:
    {"file": "src/x.py", "lines": "10-14", "claim": "...", "quote": "exact text from those lines"}
and records the lines as read. Rejected facts are printed with the reason.
"""
import fcntl
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codedoc  # noqa: E402

FILE_URL = re.compile(r"^file://(?P<path>[^#]+)(?:#L(?P<a>\d+)(?:-L?(?P<b>\d+))?)?$")
MIN_QUOTE = 6


# ------------------------------------------------------------------ storage

def store(run) -> Path:
    run = Path(run)
    return run.parent if run.parent.name == "code-docs" else run / "notes"


def _path(run, kind) -> Path:
    return store(run) / (f".{kind}.jsonl" if Path(run).parent.name == "code-docs" else f"{kind}.jsonl")


def rows(run, kind) -> list:
    path = _path(run, kind)
    out = []
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def append(run, kind, new: list):
    if not new:
        return
    path = _path(run, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in new))
        fcntl.flock(fh, fcntl.LOCK_UN)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ code access

class Files:
    """Current text and hash of code files, read once per command."""

    def __init__(self):
        self.cache = {}

    def get(self, rel: str):
        if rel not in self.cache:
            p = codedoc.inside(rel)
            if p is None or not p.is_file():
                self.cache[rel] = None
            else:
                text = p.read_text(errors="replace")
                lines = text.split("\n")
                if lines and lines[-1] == "":
                    lines.pop()           # a final newline ends the last line; it is not a line
                self.cache[rel] = (lines, codedoc.sha(p))
        return self.cache[rel]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def locate(quote: str, lines: list, start: int = 0, end: int = 0):
    """(start, end) of the quote, preferring the cited range; None if absent. Matching
    ignores whitespace differences, so indentation and wrapping do not break it."""
    q = norm(quote)
    if len(q) < MIN_QUOTE:
        return None
    nl = [norm(x) for x in lines]
    if start and end and q in " ".join(nl[start - 1:end]):
        return start, end
    head = q[:20]
    hits = []
    for i, line in enumerate(nl):
        if head not in line and not (line and q.startswith(line[:20]) and len(line) >= 8):
            continue
        acc = ""
        for j in range(i, min(i + 60, len(nl))):
            acc = f"{acc} {nl[j]}".strip()
            if q in acc:
                hits.append((i + 1, j + 1))
                break
            if len(acc) > len(q) + 400:
                break
    if not hits:
        return None
    if start:
        hits.sort(key=lambda h: abs(h[0] - start))
    return hits[0]


def status(fact: dict, files: Files):
    """('valid' | 'moved' | 'stale', start, end) for a fact against the current code."""
    cur = files.get(fact["file"])
    if cur is None:
        return "stale", fact["start"], fact["end"]
    lines, digest = cur
    if digest == fact.get("sha"):
        return "valid", fact["start"], fact["end"]
    hit = locate(fact["quote"], lines, fact["start"], fact["end"])
    if hit is None:
        return "stale", fact["start"], fact["end"]
    return ("valid" if hit == (fact["start"], fact["end"]) else "moved"), hit[0], hit[1]


def _span(text: str):
    m = re.fullmatch(r"L?(\d+)(?:\s*-\s*L?(\d+))?", str(text).strip())
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    return (a, b) if a >= 1 and b >= a else None


# ------------------------------------------------------------------ commands

def add(run, source: Path, by: str) -> tuple:
    """Validate and record facts from a JSON-lines file. Returns (accepted, rejected)."""
    codedoc.use_code_root(run)
    files = Files()
    known = {(f["file"], norm(f["quote"])) for f in rows(run, "facts")}
    next_id = len(rows(run, "facts")) + 1
    accepted, rejected, reads = [], [], []
    for n, line in enumerate(Path(source).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            rel_file = codedoc.rel(item["file"])
            span = _span(item["lines"])
            claim, quote = item["claim"].strip(), item["quote"]
        except (ValueError, KeyError, AttributeError):
            rejected.append(f"line {n}: not a fact (needs file, lines, claim, quote)")
            continue
        cur = files.get(rel_file)
        if cur is None:
            rejected.append(f"line {n}: {rel_file} does not exist under the code root")
            continue
        if span is None or span[1] > len(cur[0]):
            rejected.append(f"line {n}: {rel_file}:{item['lines']} is not a range in the file")
            continue
        hit = locate(quote, cur[0], *span)
        if hit is None:
            rejected.append(f"line {n}: quote not found in {rel_file}: {quote[:60]!r}")
            continue
        if hit != span:
            rejected.append(f"line {n}: quote is at {rel_file}:{hit[0]}-{hit[1]}, not {item['lines']}")
            continue
        if (rel_file, norm(quote)) in known:
            continue
        known.add((rel_file, norm(quote)))
        accepted.append({"id": f"F{next_id}", "file": rel_file, "start": span[0], "end": span[1],
                         "claim": claim, "quote": quote, "sha": cur[1], "by": by, "at": now()})
        reads.append({"file": rel_file, "start": span[0], "end": span[1], "sha": cur[1],
                      "by": by, "at": now()})
        next_id += 1
    append(run, "facts", accepted)
    append(run, "reads", reads)
    return accepted, rejected


def record_reads(run, file: str, spans: list, by: str) -> int:
    codedoc.use_code_root(run)
    cur = Files().get(codedoc.rel(file))
    if cur is None:
        sys.exit(f"ERROR {file} does not exist under the code root")
    new = []
    for s in spans:
        span = _span(s)
        if span is None:
            sys.exit(f"ERROR not a line range: {s}")
        new.append({"file": codedoc.rel(file), "start": span[0], "end": min(span[1], len(cur[0])),
                    "sha": cur[1], "by": by, "at": now()})
    append(run, "reads", new)
    return len(new)


def _merge(spans: list) -> list:
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def coverage(run, rel_file: str, files: Files, facts=None, docs=None):
    """(line count, read ranges valid at the current version, facts with status)."""
    cur = files.get(rel_file)
    if cur is None:
        return 0, [], []
    lines, digest = cur
    facts = rows(run, "facts") if facts is None else facts
    mine = []
    for f in facts:
        if f["file"] == rel_file:
            st, a, b = status(f, files)
            mine.append((st, a, b, f))
    spans = [(r["start"], r["end"]) for r in rows(run, "reads")
             if r["file"] == rel_file and r.get("sha") == digest]
    if docs is not None:
        spans += [(a, min(b, len(lines))) for a, b, *_rest, current in docs.get(rel_file, []) if current]
    spans += [(a, b) for st, a, b, _ in mine if st != "stale"]
    return len(lines), _merge(spans), mine


MIN_GAP = 6   # an unread gap shorter than this is a blank line or a brace, not code to read


def unread_spans(total: int, read: list) -> list:
    out, pos = [], 1
    for a, b in read:
        if a > pos:
            out.append((pos, a - 1))
        pos = max(pos, b + 1)
    if pos <= total:
        out.append((pos, total))
    return [(a, b) for a, b in out if b - a + 1 >= MIN_GAP or (a, b) == (1, total)]


def fmt(spans: list) -> str:
    return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in spans) or "none"


def siblings(run) -> list:
    """Every code document in the same project (this one included), with its stamp."""
    run = Path(run)
    if run.parent.name != "code-docs":
        return [run]
    return sorted(p.parent for p in run.parent.glob("*/.run.json"))


def documented(run, files: Files) -> dict:
    """{file: [(start, end, doc name, doc line, statement, current)]} from the project's
    code documents. `current` is False when the file changed since that document's stamp."""
    out = {}
    for doc_run in siblings(run):
        try:
            master = codedoc.master(doc_run)
        except (KeyError, IndexError):
            continue
        if not master.is_file():
            continue
        stamp = doc_run / "sources.json"
        shas = json.loads(stamp.read_text()).get("files", {}) if stamp.is_file() else {}
        for n, kind, body, _ in codedoc.blocks(master.read_text()):
            if kind not in ("para", "item", "row"):
                continue
            for m in codedoc.REF.finditer(body):
                f = m.group(1)
                cur = files.get(f)
                a, b = int(m.group(2)), int(m.group(3) or m.group(2))
                out.setdefault(f, []).append(
                    (a, b, doc_run.name, n, norm(codedoc.REF.sub("", body))[:160],
                     bool(cur) and shas.get(f) == cur[1]))
    return out


def known(run, targets: list, brief: bool = False) -> list:
    codedoc.use_code_root(run)
    files, facts, out = Files(), rows(run, "facts"), []
    docs = documented(run, files)
    for t in targets:
        rel_file = codedoc.rel(t)
        total, read, mine = coverage(run, rel_file, files, facts, docs)
        if not total:
            out.append(f"## {rel_file}: not found under the code root")
            continue
        counts = {s: sum(1 for m in mine if m[0] == s) for s in ("valid", "moved", "stale")}
        done = sum(b - a + 1 for a, b in read)
        where = fmt(read) if len(read) <= 8 else f"{len(read)} ranges; `unread` lists what is left"
        out.append(f"## {rel_file} · {total} lines · read {done * 100 // total}% at this version "
                   f"({where}) · facts {counts['valid']} valid, {counts['moved']} moved, "
                   f"{counts['stale']} stale")
        if brief:
            continue
        for st, a, b, f in sorted(mine, key=lambda m: (m[1], m[2])):
            mark = "" if st == "valid" else f" [{st.upper()}]"
            out.append(f"- `{rel_file}:{a}-{b}`{mark} {f['claim'][:200]}")
        here = [d for d in docs.get(rel_file, []) if d[2] != Path(run).name]
        if here:
            out.append(f"Already described in {len({d[2] for d in here})} other code document(s):")
            for a, b, name, n, text, current in sorted(here)[:25]:
                mark = "" if current else " [FILE CHANGED SINCE]"
                out.append(f"- `{rel_file}:{a}-{b}` {name}.md L{n}{mark}: {text}")
            if len(here) > 25:
                out.append(f"- (+{len(here) - 25} more)")
    return out


def import_evidence(run) -> tuple:
    """Turn the project's evidence rows that cite the code into facts. Rows whose quote
    is no longer in the file are skipped and counted."""
    run = Path(run)
    root = codedoc.use_code_root(run)
    project = run.parent.parent if run.parent.name == "code-docs" else run
    ev = project / "evidence.jsonl"
    if not ev.is_file():
        return 0, 0, 0
    files = Files()
    have = {(f["file"], norm(f["quote"])) for f in rows(run, "facts")}
    next_id = len(rows(run, "facts")) + 1
    new, reads, stale, outside = [], [], 0, 0
    for line in ev.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        m = FILE_URL.match(str(r.get("url", "")))
        if not m or not r.get("quote"):
            continue
        path = Path(m.group("path"))
        try:
            rel_file = str(path.resolve().relative_to(root))
        except ValueError:
            outside += 1
            continue
        cur = files.get(rel_file)
        a = int(m.group("a") or 0)
        b = int(m.group("b") or a)
        hit = locate(r["quote"], cur[0], a, b) if cur else None
        if hit is None:
            stale += 1
            continue
        if (rel_file, norm(r["quote"])) in have:
            continue
        have.add((rel_file, norm(r["quote"])))
        new.append({"id": f"F{next_id}", "file": rel_file, "start": hit[0], "end": hit[1],
                    "claim": str(r.get("claim", "")).strip(), "quote": r["quote"], "sha": cur[1],
                    "by": f"evidence {r.get('id', '')}".strip(), "at": now()})
        reads.append({"file": rel_file, "start": hit[0], "end": hit[1], "sha": cur[1],
                      "by": f"evidence {r.get('id', '')}".strip(), "at": now()})
        next_id += 1
    append(run, "facts", new)
    append(run, "reads", reads)
    return len(new), stale, outside


MAX_HITS = 200


def version(paths: list) -> str:
    """The state of the code a search covers: the commit, plus the size and modification
    time of every file under the searched paths, so an edit invalidates a cached search
    whether or not it was committed, and whether or not the code is a repository."""
    import hashlib
    import os
    root = codedoc.CODE_ROOT
    h = hashlib.sha256((codedoc.git("rev-parse", "HEAD") or "no-commit").encode())
    skip = codedoc.skip_dirs()
    for top in sorted(paths or ["."]):
        base = (root / top).resolve()
        if base.is_file():
            st = base.stat()
            h.update(f"{top}:{st.st_size}:{st.st_mtime_ns}".encode())
            continue
        for d, dirs, names in os.walk(base):
            dirs[:] = sorted(x for x in dirs if x not in skip)
            for n in sorted(names):
                try:
                    st = os.stat(os.path.join(d, n))
                except OSError:
                    continue
                h.update(f"{d}/{n}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:16]


def search(run, pattern: str, paths: list) -> tuple:
    """(lines, cached) for a grep over the code root. Identical searches at the same
    code version are answered from the record."""
    import subprocess
    root = codedoc.use_code_root(run)
    ver = version(paths)
    key = {"pattern": pattern, "paths": sorted(paths)}
    for r in reversed(rows(run, "searches")):
        if r.get("version") == ver and {"pattern": r["pattern"], "paths": r["paths"]} == key:
            return r["hits"], r.get("total", len(r["hits"])), True
    cmd = ["git", "grep", "-n", "-I", "-E", pattern, "--", *(paths or ["."])]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=60)
    if proc.returncode > 1:   # not a repository, or a bad pattern: plain grep
        cmd = ["grep", "-rnIE", "--exclude-dir=node_modules", "--exclude-dir=.git", pattern, *(paths or ["."])]
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=60)
    found = [line[:300] for line in proc.stdout.splitlines()]
    append(run, "searches", [{"pattern": pattern, "paths": sorted(paths), "version": ver,
                              "total": len(found), "hits": found[:MAX_HITS], "at": now()}])
    return found[:MAX_HITS], len(found), False


def stats(run) -> str:
    codedoc.use_code_root(run)
    files, facts = Files(), rows(run, "facts")
    by_status = {"valid": 0, "moved": 0, "stale": 0}
    for f in facts:
        by_status[status(f, files)[0]] += 1
    n_files = len({f["file"] for f in facts})
    return (f"{len(facts)} fact(s) on {n_files} file(s): {by_status['valid']} valid, "
            f"{by_status['moved']} moved, {by_status['stale']} stale; "
            f"{len(rows(run, 'reads'))} read record(s). Store: {codedoc.run_rel(_path(run, 'facts'))}")


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.stderr.write(__doc__)
        return 2
    cmd, run, rest = args[0], args[1], args[2:]
    by = rest[rest.index("--by") + 1] if "--by" in rest and rest.index("--by") + 1 < len(rest) else ""
    rest = [a for i, a in enumerate(rest) if a not in ("--by", "--brief")
            and not (i and rest[i - 1] == "--by")]
    if cmd == "known":
        print("\n".join(known(run, rest, "--brief" in args)))
        return 0
    if cmd == "unread":
        codedoc.use_code_root(run)
        files = Files()
        docs = documented(run, files)
        for t in rest:
            rel_file = codedoc.rel(t)
            total, read, _ = coverage(run, rel_file, files, docs=docs)
            print(f"{rel_file}: {fmt(unread_spans(total, read)) if total else 'not found'}")
        return 0
    if cmd == "add":
        if not rest or not by:
            sys.exit("usage: codefacts.py add <run> <facts.jsonl> --by <name>")
        ok, bad = add(run, Path(rest[0]), by)
        for line in bad:
            print(f"REJECTED {line}")
        print(f"recorded {len(ok)} fact(s), rejected {len(bad)}")
        return 1 if bad else 0
    if cmd == "read":
        if len(rest) < 2 or not by:
            sys.exit("usage: codefacts.py read <run> <file> <start-end> [...] --by <name>")
        print(f"recorded {record_reads(run, rest[0], rest[1:], by)} read range(s)")
        return 0
    if cmd == "import":
        n, stale, outside = import_evidence(run)
        print(f"imported {n} fact(s) from the project's evidence; {stale} no longer match the code, "
              f"{outside} cite files outside the code root")
        print(stats(run))
        return 0
    if cmd == "search":
        if not rest:
            sys.exit("usage: codefacts.py search <run> <regex> [<path> ...]")
        hits, total, cached = search(run, rest[0], rest[1:])
        print("\n".join(hits))
        more = f", first {len(hits)} shown" if total > len(hits) else ""
        print(f"({total} match(es){more}{'; from the record, the code has not changed since' if cached else ''})")
        return 0
    if cmd == "stats":
        print(stats(run))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
