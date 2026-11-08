#!/usr/bin/env python3
"""codedoc.py: the deterministic half of /code-doc.

A code document describes an implementation as written. Its evidence is the code
itself, cited as `path:line` or `path:start-end`, so the checks here play the part
that audit_citations.py plays for a report: every reference resolves to lines that
exist, every statement carries one or is a labelled gap, and the document says
when the code it describes has changed.

    python3 .claude/scripts/codedoc.py start <slug> --target "<what was typed>" \
            --scope <path> [<path> ...] --prompt "<the request, verbatim>" \
            [--code-root <path>] [--project outputs/<run>]
    python3 .claude/scripts/codedoc.py find "<target>"     # the run already documenting it
    python3 .claude/scripts/codedoc.py inventory <run>     # files in scope, with line counts
    python3 .claude/scripts/codedoc.py check <doc>         # ERROR / WARN lines, exit 1 on ERROR
    python3 .claude/scripts/codedoc.py stamp <run>         # record the code the document describes
    python3 .claude/scripts/codedoc.py status <run>        # what changed since; exit 1 if anything
    python3 .claude/scripts/codedoc.py stages <run>        # stage table, used by run_check.py

A code-doc run is a folder under outputs/ or a project's `code-docs/` directory whose `.run.json` has kind "code-doc",
one master `<slug>.md`, the target as typed and the scope as paths relative to the
code root. Running /code-doc again on the same target finds that run and the
master is updated in place.

The code root is the project itself unless the run's `.run.json` names another
repository in `code_root`, which is how a document in this workspace describes
code that lives in a sibling checkout. Scope paths, `path:line` references, the
inventory and the stamp all resolve against it; the run folder itself always
stays under this project's `outputs/`.
"""
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runmeta  # noqa: E402

KIND = "code-doc"
# The repository the document describes: this project, unless a run names another.
CODE_ROOT = ROOT
GAP = "[Not defined in codebase]"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".pytest_cache", ".mypy_cache", ".history", "outputs"}

# `app/backend/workspace.py:91` or `app/backend/workspace.py:91-114`, in backticks.
REF = re.compile(r"`((?:[\w@+.-]+/)*[\w@+-][\w@+.-]*):(\d+)(?:-(\d+))?`")
INFERENCE = re.compile(r"^\W*(?:\*\*|\*|_)?Inference(?:\*\*|\*|_)?\s*:", re.I)
FENCE = re.compile(r"^\s*(```|~~~)")
SEVERITY = re.compile(r"\b(?:High|Medium|Low)\b")

# Sections in order: (heading pattern, required sub-headings).
SECTIONS = [
    ("overview", r"overview", []),
    ("architecture", r"architecture|interactions", []),
    ("specification", r"specification", [
        ("detailed architecture", r"detailed architecture|data model"),
        ("tech stack and dependencies", r"tech stack|dependenc"),
        ("reproduction guide", r"reproduc"),
    ]),
    ("code health", r"code health|gaps|improvement", []),
    ("supplemental details", r"supplemental|implementation details|quirks", []),
]

# The documentation process never reaches the reader. Internal file names are not
# listed: a document about this workspace's own scripts names them legitimately.
ARTIFACTS = [
    (r"^#{1,6}\s*Round\s+\d", "round-shaped heading"),
    (r"\[(?:BLOCKING|MATERIAL|MINOR)\]", "review severity tag"),
    (r"\bas an AI\b|\bI (?:searched|looked|read|found|grepped|will now|should note|could not)\b"
     r"|\bmy (?:analysis|reading|review) (?:showed|found)\b", "agent self-reference"),
    (r"\b(?:the|an?) (?:independent )?reviewer (?:found|flagged|noted|said)\b", "review process"),
    (r"\b(?:Great question|Let'?s dive|Here'?s what I found|I hope this helps)\b", "chat voice"),
    (r"<[a-z ]+here>|\bANALYST-TODO\b|\bDOC-TODO\b", "unfinished scaffold"),
]


# ------------------------------------------------------------------ helpers

def use_code_root(where) -> Path:
    """Point the code lookups at the repository a run documents. Idempotent."""
    global CODE_ROOT
    CODE_ROOT = ROOT
    path = Path(where)
    run = path if path.is_dir() else path.parent
    declared = runmeta.meta(run).get("code_root")
    if declared:
        q = Path(declared)
        q = q if q.is_absolute() else ROOT / q
        if q.is_dir():
            CODE_ROOT = q.resolve()
    return CODE_ROOT


def skip_dirs() -> set:
    """`outputs` is this project's run folders; in another repository it is code."""
    return SKIP_DIRS if CODE_ROOT == ROOT else SKIP_DIRS - {"outputs"}


def rel(path) -> str:
    """A code path, relative to the code root."""
    p = Path(path)
    p = p if p.is_absolute() else CODE_ROOT / p
    try:
        return str(p.resolve().relative_to(CODE_ROOT))
    except ValueError:
        return str(p)


def run_rel(path) -> str:
    """A run path, relative to this project. Run folders never move."""
    p = Path(path)
    p = p if p.is_absolute() else ROOT / p
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def inside(path: str):
    """The file a reference names, if it lies inside the code root. None otherwise."""
    p = (CODE_ROOT / path).resolve()
    try:
        p.relative_to(CODE_ROOT)
    except ValueError:
        return None
    return p


def line_count(path: Path) -> int:
    try:
        with path.open("rb") as fh:
            data = fh.read()
    except OSError:
        return 0
    if b"\0" in data[:4096]:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args) -> str:
    try:
        p = subprocess.run(["git", *args], cwd=CODE_ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def expand(scope) -> list:
    """Every text file the scope covers, relative to the project root, sorted."""
    out = set()
    for entry in scope:
        p = inside(entry)
        if p is None or not p.exists():
            continue
        if p.is_file():
            out.add(rel(p))
            continue
        tracked = git("ls-files", "--cached", "--others", "--exclude-standard", "--", rel(p))
        files = [CODE_ROOT / f for f in tracked.splitlines()] if tracked else list(p.rglob("*"))
        for f in files:
            if f.is_file() and not (set(Path(rel(f)).parts) & skip_dirs()) and line_count(f):
                out.add(rel(f))
    return sorted(out)


def load(run) -> dict:
    return runmeta.meta(run)


def master(run) -> Path:
    return Path(run) / runmeta.meta(run)["masters"][0]


def runs():
    base = ROOT / "outputs"
    paths = (list(base.glob("*/.run.json")) + list(base.glob("*/code-docs/*/.run.json"))) if base.is_dir() else []
    for path in sorted(paths):
        meta = runmeta.meta(path.parent)
        if meta.get("kind") == KIND:
            yield path.parent, meta


def norm(target: str) -> str:
    return re.sub(r"\s+", " ", target.strip().strip("/").lower())


# ------------------------------------------------------------------ commands

def find(target: str, project: str = ""):
    """The newest matching code document, limited to a project when supplied."""
    want = norm(target)
    parent = (ROOT / project).resolve() if project else None
    hits = [run for run, meta in runs()
            if (parent is None or run.parent.parent == parent)
            and (norm(meta.get("target", "")) == want
                 or want in [norm(s) for s in meta.get("scope", [])])]
    return hits[-1] if hits else None


def start(slug: str, target: str, scope: list, prompt: str, code_root: str = "",
          project: str = "") -> Path:
    global CODE_ROOT
    if code_root:
        q = Path(code_root)
        q = (q if q.is_absolute() else ROOT / q).resolve()
        if not q.is_dir():
            sys.exit(f"ERROR code root is not a directory: {code_root}")
        CODE_ROOT = q
    bad = [s for s in scope if inside(s) is None or not inside(s).exists()]
    if bad:
        sys.exit(f"ERROR scope paths that do not exist inside the project: {', '.join(bad)}")
    scope = [rel(s) for s in scope]
    existing = find(target, project)
    if existing:
        data = json.loads((existing / ".run.json").read_text())
        data["scope"] = sorted(set(data.get("scope", [])) | set(scope))
        if CODE_ROOT != ROOT:
            data["code_root"] = str(CODE_ROOT)
        (existing / ".run.json").write_text(json.dumps(data, indent=2) + "\n")
        _append_prompt(existing, prompt)
        return existing
    clean = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")[:50] or "code"
    if project:
        project_path = (ROOT / project).resolve()
        try:
            relative = project_path.relative_to(ROOT / "outputs")
        except ValueError:
            sys.exit(f"ERROR project must be a run under outputs/: {project}")
        if len(relative.parts) != 1 or not project_path.is_dir():
            sys.exit(f"ERROR project must be an existing top-level run: {project}")
        run = project_path / "code-docs" / clean
    else:
        run = ROOT / "outputs" / f"{date.today().isoformat()}-code-doc-{clean}"
    if run.exists():
        sys.exit(f"ERROR a different folder already uses {run_rel(run)}")
    (run / "notes").mkdir(parents=True, exist_ok=True)
    data = {"kind": KIND, "doc_kind": KIND, "masters": [f"{clean}.md"], "target": target,
            "scope": sorted(set(scope)),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if CODE_ROOT != ROOT:
        data["code_root"] = str(CODE_ROOT)
    (run / ".run.json").write_text(json.dumps(data, indent=2) + "\n")
    if not (run / "prompt.md").is_file():
        (run / "prompt.md").write_text(
            f"# Request\n\n**Date:** {date.today().isoformat()}\n**Run:** {run_rel(run)}\n"
            f"**Target:** {target}\n\n## Verbatim prompt\n\n{prompt}\n")
    return run


def _append_prompt(run: Path, prompt: str):
    path = run / "prompt.md"
    text = path.read_text() if path.is_file() else "# Request\n"
    path.write_text(text.rstrip("\n") + f"\n\n## Re-run {date.today().isoformat()}\n\n{prompt}\n")


def inventory(run) -> list:
    use_code_root(run)
    return [(f, line_count(CODE_ROOT / f)) for f in expand(load(run).get("scope", []))]


def blocks(text: str):
    """(line number, kind, text, section) for each block a reader sees as a statement.
    kind is 'para', 'item', 'row', 'fence' or 'heading'."""
    out, section, buf, start_at, in_fence, fence_start = [], "", [], 0, False, 0

    def flush():
        nonlocal buf
        if buf:
            out.append((start_at, "para", " ".join(s.strip() for s in buf), section))
        buf = []

    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if FENCE.match(line):
            if not in_fence:
                flush()
                fence_start = n
            else:
                out.append((fence_start, "fence", "", section))
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if s.startswith("<!--"):
            flush()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            flush()
            if len(m.group(1)) == 2:
                section = m.group(2)
            out.append((n, "heading", s, section))
            continue
        if not s:
            flush()
            continue
        if s.startswith("|"):
            flush()
            if re.fullmatch(r"\|[\s:|-]+\|?", s):
                # the separator: the row above was a header, not a statement
                if out and out[-1][1] == "row":
                    out[-1] = (*out[-1][:1], "header", *out[-1][2:])
                continue
            out.append((n, "row", s, section))
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", s):
            flush()
            out.append((n, "item", s, section))
            continue
        if out and out[-1][1] == "item" and not buf and line.startswith((" ", "\t")):
            # continuation of a list item
            ln, k, t, sec = out[-1]
            out[-1] = (ln, k, f"{t} {s}", sec)
            continue
        if not buf:
            start_at = n
        buf.append(s)
    flush()
    return out


def check(doc: Path):
    """(errors, warnings) for a code document."""
    errors, warns = [], []
    text = doc.read_text()
    name = doc.name
    run = doc.parent
    use_code_root(run)
    lines = text.splitlines()

    # Structure: the five sections, in order, with the three specification parts.
    h2 = [(n, s[3:].strip()) for n, s in enumerate(lines, 1) if s.startswith("## ")]
    h3 = [(n, s[4:].strip()) for n, s in enumerate(lines, 1) if s.startswith("### ")]
    found = []
    for label, pat, subs in SECTIONS:
        hit = next(((n, h) for n, h in h2 if re.search(pat, h, re.I)), None)
        if not hit:
            errors.append(f"ERROR {name}: no section for {label}")
            continue
        found.append((hit[0], label))
        end = min([n for n, _ in h2 if n > hit[0]] or [len(lines) + 1])
        for sub, spat in subs:
            if not any(hit[0] < n < end and re.search(spat, h, re.I) for n, h in h3):
                errors.append(f"ERROR {name}:{hit[0]}: {label} has no '{sub}' subsection")
    if [n for n, _ in found] != sorted(n for n, _ in found):
        errors.append(f"ERROR {name}: sections out of order: {', '.join(l for _, l in sorted(found))}")

    # References resolve to lines that exist inside the project.
    cited = set()
    for n, line in enumerate(lines, 1):
        for m in REF.finditer(line):
            path, a, b = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
            p = inside(path)
            if p is None:
                errors.append(f"ERROR {name}:{n}: `{m.group(0)[1:-1]}` points outside the project")
            elif not p.is_file():
                errors.append(f"ERROR {name}:{n}: `{path}` does not exist")
            elif a < 1 or b < a or b > line_count(p):
                errors.append(f"ERROR {name}:{n}: `{m.group(0)[1:-1]}` is outside the file "
                              f"({line_count(p)} lines)")
            else:
                cited.add(rel(p))

    # Every statement carries a reference, a labelled gap, or a labelled inference.
    seen_h2 = False
    diagram_sections = set()
    for n, kind, body, section in blocks(text):
        if kind == "heading":
            seen_h2 = seen_h2 or body.startswith("## ")
            continue
        if kind == "fence":
            diagram_sections.add(section)
            continue
        if not seen_h2 or kind == "header":
            continue                       # title and metadata lines
        plain = body.rstrip()
        if plain.endswith(":") and kind in ("para", "item"):
            continue                       # a lead-in to a list, table or code block
        if REF.search(body) or GAP in body or INFERENCE.match(body):
            continue
        if kind == "row" and _row_has_gap(body):
            continue
        errors.append(f"ERROR {name}:{n}: statement with no code reference, "
                      f"no {GAP} and no 'Inference:' label: {plain[:70]}")

    arch = next((h for n, h in h2 if re.search(SECTIONS[1][1], h, re.I)), None)
    if arch and arch not in diagram_sections:
        errors.append(f"ERROR {name}: the architecture section has no diagram")

    health = next((n for n, h in h2 if re.search(SECTIONS[3][1], h, re.I)), None)
    if health:
        end = min([n for n, _ in h2 if n > health] or [len(lines) + 1])
        if not SEVERITY.search("\n".join(lines[health:end - 1])):
            warns.append(f"WARN {name}:{health}: no finding is graded High, Medium or Low")

    for pat, why in ARTIFACTS:
        for n, line in enumerate(lines, 1):
            if re.search(pat, line, re.I | re.M):
                errors.append(f"ERROR {name}:{n}: {why}: {line.strip()[:70]}")

    # Coverage and freshness are advice: the reviewer decides what they mean.
    scope = set(expand(load(run).get("scope", [])))
    for f in sorted(scope - cited):
        warns.append(f"WARN {name}: in scope but never cited: {f}")
    for line in changed(run):
        warns.append(f"WARN {name}: {line}")
    return errors, warns


def _row_has_gap(row: str) -> bool:
    return any(c.strip() in (GAP, "Not defined in codebase") for c in row.strip("|").split("|"))


def cited_files(doc: Path) -> set:
    out = set()
    for m in REF.finditer(doc.read_text() if doc.is_file() else ""):
        p = inside(m.group(1))
        if p is not None and p.is_file():
            out.add(rel(p))
    return out


def stamp(run) -> dict:
    run = Path(run)
    use_code_root(run)
    files = sorted(set(expand(load(run).get("scope", []))) | cited_files(master(run)))
    data = {
        "commit": git("rev-parse", "HEAD") or None,
        "dirty": [f for f in git("status", "--porcelain", "--", *files).splitlines()] if files else [],
        "stamped": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_root": str(CODE_ROOT) if CODE_ROOT != ROOT else None,
        "files": {f: sha(CODE_ROOT / f) for f in files if (CODE_ROOT / f).is_file()},
    }
    (run / "sources.json").write_text(json.dumps(data, indent=2) + "\n")
    return data


def changed(run) -> list:
    """What changed in the code since the document was stamped, one line each."""
    run = Path(run)
    use_code_root(run)
    path = run / "sources.json"
    if not path.is_file():
        return ["never stamped: the document records no state of the code"]
    old = json.loads(path.read_text()).get("files", {})
    out = []
    doc = master(run)
    text = doc.read_text() if doc.is_file() else ""
    for f, digest in sorted(old.items()):
        p = CODE_ROOT / f
        if not p.is_file():
            out.append(f"DELETED {f}{_where(text, f)}")
        elif sha(p) != digest:
            out.append(f"CHANGED {f}{_where(text, f)}")
    for f in sorted(set(expand(load(run).get("scope", []))) - set(old)):
        out.append(f"NEW {f}")
    return out


def _where(text: str, f: str) -> str:
    """The sections that cite a file, so a refresh knows what to reread."""
    section, hits = "", []
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        if f"`{f}:" in line and section and section not in hits:
            hits.append(section)
    return f" (cited in: {'; '.join(hits)})" if hits else ""


def stages(run) -> list:
    """(label, ok, detail) for each stage of a code-doc run."""
    run = Path(run)
    use_code_root(run)
    doc = master(run)
    out = []
    prompt = run / "prompt.md"
    out.append(("prompt", prompt.is_file(), "the request, verbatim" if prompt.is_file() else "not written"))
    n = len(expand(load(run).get("scope", [])))
    out.append(("scope", n > 0, f"{n} file(s)" if n else "no files in scope"))
    if doc.is_file():
        errs, _ = check(doc)
        out.append(("document", True, f"{doc.name}, {len(doc.read_text().split())} words"))
        out.append(("references", not errs, "every statement resolves" if not errs
                    else f"{len(errs)} problem(s)"))
    else:
        out.append(("document", False, "not written"))
        out.append(("references", False, "nothing to check"))
    review, log = run / "review.md", run / "repair-log.md"
    fresh = review.is_file() and doc.is_file() and (
        review.stat().st_mtime >= doc.stat().st_mtime
        # a repair after the review is expected: the review stands if the log is newer
        or (log.is_file() and log.stat().st_mtime >= max(review.stat().st_mtime, doc.stat().st_mtime) - 1))
    out.append(("review", fresh, "independent review on file" if fresh
                else "document changed since its review and repair" if review.is_file() else "never reviewed"))
    out.append(("repair", log.is_file(), "findings dispositioned" if log.is_file() else "no repair log"))
    moved = changed(run)
    out.append(("current", not moved, "matches the code" if not moved else f"{len(moved)} file(s) moved"))
    return out


def main():
    args = sys.argv[1:]
    if not args:
        sys.stderr.write(__doc__)
        return 2
    cmd, rest = args[0], args[1:]

    def opt(flag, many=False):
        if flag not in rest:
            return [] if many else None
        i = rest.index(flag) + 1
        vals = []
        while i < len(rest) and not rest[i].startswith("--"):
            vals.append(rest[i])
            i += 1
        return vals if many else (vals[0] if vals else None)

    if cmd == "start":
        if not rest or rest[0].startswith("--") or not opt("--target") or not opt("--scope", True):
            sys.exit("usage: codedoc.py start <slug> --target T --scope P [P ...] --prompt TEXT "
                     "[--code-root PATH] [--project outputs/RUN]")
        run = start(rest[0], opt("--target"), opt("--scope", True), opt("--prompt") or "",
                    opt("--code-root") or "", opt("--project") or "")
        print(run_rel(run))
        print(run_rel(master(run)))
        return 0
    if cmd == "find":
        run = find(" ".join(rest))
        if run:
            print(run_rel(run))
            return 0
        return 1
    if cmd == "inventory":
        rows = inventory(rest[0])
        for f, n in rows:
            print(f"{n:6d}  {f}")
        print(f"{len(rows)} file(s), {sum(n for _, n in rows)} line(s)")
        return 0
    if cmd == "check":
        errors, warns = check(Path(rest[0]))
        for line in errors + warns:
            print(line)
        if not errors:
            print(f"OK {Path(rest[0]).name}: structure, references and statements")
        return 1 if errors else 0
    if cmd == "stamp":
        data = stamp(rest[0])
        print(f"stamped {len(data['files'])} file(s) at {data['commit'] or 'no commit'}"
              + (f", {len(data['dirty'])} with uncommitted changes" if data["dirty"] else ""))
        return 0
    if cmd == "status":
        moved = changed(rest[0])
        for line in moved:
            print(line)
        if not moved:
            print("current: the code matches the document's stamp")
        return 1 if moved else 0
    if cmd == "stages":
        for label, ok, detail in stages(rest[0]):
            print(f"  {'ok ' if ok else 'MISSING'} {label}  {detail}")
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
