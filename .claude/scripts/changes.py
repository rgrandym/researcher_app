#!/usr/bin/env python3
"""changes.py: a subject's change plan, the author's decisions on it, and the checks.

    python3 .claude/scripts/changes.py validate <run> <slug>     # the plan, before the author sees it
    python3 .claude/scripts/changes.py render   <run> <slug>     # changes.md, the readable plan
    python3 .claude/scripts/changes.py status   <run> [<slug>]   # proposed / accepted / rejected / stale
    python3 .claude/scripts/changes.py decide   <run> <slug> <C01,C02|all> accept|reject|clear
                                                [--after TEXT] [--note TEXT] [--by "author in chat"]
    python3 .claude/scripts/changes.py check    <run> <slug> [vN]   # the applied deliverable
    python3 .claude/scripts/changes.py fidelity <run> <slug> <file> # a rebuilt file against the design

The plan is `subjects/<slug>/changes.json`, written by the agent. Decisions are
`subjects/<slug>/decisions.json`, written only by the author (the app, or `decide`).
A decision binds to a hash of the change it answered: a change edited after the
author accepted it is `stale` and is not applied until they decide again.

`check` compares the deliverable with the original part by part. Every difference
must belong to an accepted change; every accepted change must be visible; no
formatting value may appear that the original does not use; no new link may point
to a URL that is not in evidence.jsonl; no pipeline trace may reach the document.
Exit 1 on any problem. Schema and doctrine: `.claude/references/revision.md`.
"""
import difflib
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import officedoc  # noqa: E402
import subject as subjects  # noqa: E402

OPS = {
    "docx": {"replace", "insert_after", "insert_before", "delete", "insert_table"},
    "pptx": {"replace", "insert_after", "insert_before", "delete", "add_slide"},
    "xlsx": {"set_cell"},
    "md": {"replace", "insert_after", "insert_before", "delete"},
    # A PDF is never edited: its plan is carried out by /rebuild, which builds the new file.
    "pdf": {"replace", "insert_after", "insert_before", "delete", "add_slide"},
}
KINDS = {"correct", "update", "add", "remove", "adjust", "style"}
BASES = {"evidence", "author", "consistency", "editorial"}
CONTENT = ("op", "target", "before", "after", "like", "rows", "fill", "drop")
TRACE = re.compile(r"\[E\d+\]|\[UNVERIFIED\]|evidence\.jsonl|verification\.md|critique\.md|"
                   r"changes\.json|\bsubagents?\b|\bscouts?\b|\bAdmiralty\b|\bgate\.py\b")
GAP = re.compile(r"\[NEEDS DATA")
DONOR = re.compile(r"^\{([A-Za-z0-9.#!]+)\}\s*")


def sdir(run, slug):
    return Path(run) / "subjects" / slug


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return default


def plan(run, slug):
    return load_json(sdir(run, slug) / "changes.json", {"changes": []})


def change_hash(ch):
    body = {k: ch.get(k) for k in CONTENT if ch.get(k) is not None}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def decisions(run, slug):
    return load_json(sdir(run, slug) / "decisions.json", {"decisions": {}}).get("decisions", {})


def states(run, slug):
    """[(change, status, decision)] with status proposed | accepted | rejected | stale."""
    dec = decisions(run, slug)
    out = []
    for ch in plan(run, slug).get("changes", []):
        d = dec.get(ch.get("id"))
        if d is None:
            status = "proposed"
        elif d.get("hash") != change_hash(ch):
            status = "stale"
        else:
            status = d.get("status", "proposed")
        out.append((ch, status, d))
    return out


def accepted(run, slug):
    """Accepted changes as they will be applied: an author-edited `after` replaces the proposal."""
    out = []
    for ch, status, d in states(run, slug):
        if status != "accepted":
            continue
        ch = dict(ch)
        if d.get("after") is not None and d["after"] != ch.get("after"):
            ch["after"] = d["after"]
            ch["author_edited"] = True
        out.append(ch)
    return out


def decide(run, slug, ids, verdict, after=None, note=None, by="author"):
    if verdict not in ("accept", "reject", "clear"):
        sys.exit("ERROR verdict is accept, reject or clear")
    path = sdir(run, slug) / "decisions.json"
    data = load_json(path, {"decisions": {}})
    data.setdefault("decisions", {})
    changes = {c["id"]: c for c in plan(run, slug).get("changes", [])}
    targets = list(changes) if ids == ["all"] else ids
    for cid in targets:
        if cid not in changes:
            sys.exit(f"ERROR no change {cid} in the plan")
        if verdict == "clear":
            data["decisions"].pop(cid, None)
            continue
        entry = {"status": "accepted" if verdict == "accept" else "rejected",
                 "hash": change_hash(changes[cid]), "by": by,
                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if after is not None:
            entry["after"] = after
        if note:
            entry["note"] = note
        data["decisions"][cid] = entry
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"{verdict}: {', '.join(targets)}")
    return 0


def evidence_rows(run):
    rows = {}
    path = Path(run) / "evidence.jsonl"
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    rows[row.get("id")] = row
                except json.JSONDecodeError:
                    pass
    return rows


def norm(text):
    return " ".join(officedoc.strip_tokens(text).split())


def model_of(run, slug):
    return load_json(sdir(run, slug) / "model.json", None)


# ------------------------------------------------------------------ validate

def validate(run, slug, quiet=False):
    model = model_of(run, slug)
    if model is None:
        sys.exit(f"ERROR {slug} is not extracted: subject.py extract {run} {slug}")
    fmt = model["format"]
    parts = {p["id"]: p for p in model["parts"]}
    refs = load_json(sdir(run, slug) / "references.json", {})
    ev = evidence_rows(run)
    data = plan(run, slug)
    problems, warnings = [], []
    seen = set()
    for ch in data.get("changes", []):
        cid = ch.get("id", "?")
        say = lambda msg: problems.append(f"{cid}: {msg}")  # noqa: E731
        warn = lambda msg: warnings.append(f"{cid}: {msg}")  # noqa: E731
        if not re.fullmatch(r"C\d{2,}", str(cid)):
            say("id must look like C01")
        if cid in seen:
            say("duplicate id")
        seen.add(cid)
        op, target = ch.get("op"), ch.get("target")
        if op not in OPS.get(fmt, set()):
            say(f"op '{op}' is not available for {fmt} ({', '.join(sorted(OPS.get(fmt, [])))})")
            continue
        if ch.get("kind") not in KINDS:
            say(f"kind must be one of {', '.join(sorted(KINDS))}")
        basis = ch.get("basis", "evidence")
        if basis not in BASES:
            say(f"basis must be one of {', '.join(sorted(BASES))}")
        if not (ch.get("rationale") or "").strip():
            say("rationale is empty: say why the change improves the document")
        ids = ch.get("evidence") or []
        if basis == "evidence" and not ids:
            say("basis is evidence but no evidence IDs are given")
        for eid in ids:
            if eid not in ev:
                say(f"evidence {eid} is not in evidence.jsonl")
        if op == "set_cell":
            if not re.fullmatch(r".+![A-Z]{1,3}[1-9]\d*", str(target or "")):
                say("set_cell target must be Sheet!A1")
            elif ch.get("before") is not None and ch["before"] != (parts.get(target) or {}).get("text", ""):
                say(f"before does not match {target}: it holds {(parts.get(target) or {}).get('text', '')!r}")
            if ch.get("after") is None:
                say("set_cell needs after (a value, or a formula starting with =)")
            continue
        if op == "add_slide":
            for key in ("target", "like"):
                ref = ch.get(key) or (target if key == "like" else None)
                if (parts.get(ref) or {}).get("kind") not in ("slide", "page"):
                    say(f"{key} must be a slide ID such as S04 (PG04 in a PDF)")
            if fmt == "pdf" and not (ch.get("after") or ch.get("fill")):
                say("a new slide in a PDF plan needs after: its full text, one line per paragraph")
            continue
        part = parts.get(target)
        if part is None:
            say(f"target {target} is not a part of the original")
            continue
        after = ch.get("after") or ""
        if op == "replace":
            before = ch.get("before") or ""
            if not before:
                say("replace needs before: the exact original text it changes")
            elif officedoc.TOKEN.search(before):
                say("before contains a footnote marker or object token; replace the text around it")
            elif part["kind"] == "shape":
                inside = [q for q in model["parts"] if q["id"].startswith(target + ".p") and before in q["text"]]
                if norm(before) != norm(part["text"]) and len(inside) != 1:
                    say(f"before must be the whole text of {target}, or occur in exactly one of its paragraphs")
            else:
                n = part["text"].count(before)
                if n != 1:
                    say(f"before occurs {n} times in {target}" + (
                        "; copy it exactly from text.md" if n == 0 else "; quote more of the sentence"))
        if op == "delete" and ch.get("before") and norm(ch["before"]) != norm(part["text"]):
            say(f"before does not match the whole text of {target}")
        if op in ("insert_after", "insert_before") and not after.strip():
            say("insert needs after: the new text")
        if ch.get("like") and ch["like"] not in parts:
            say(f"like {ch['like']} is not a part of the original")
        for block in after.split("\n\n"):
            m = DONOR.match(block.strip())
            if m and m.group(1) not in parts and not re.fullmatch(r"p\d+", m.group(1)):
                say(f"formatting donor {{{m.group(1)}}} is not a part of the original")
        if op == "insert_table":
            like = parts.get(ch.get("like"))
            rows = ch.get("rows")
            if not like or like["kind"] != "table":
                say("insert_table needs like: an existing table (T1) to copy")
            elif not isinstance(rows, list) or not rows or any(len(r) != like["cols"] for r in rows):
                say(f"rows must be a list of rows, each with {like['cols']} cells (as {like['id']})")
        if fmt == "pptx" and "^[" in after:
            say("slides have no footnotes; cite in the deck's own style")
        texts = [after] + [str(c) for r in (ch.get("rows") or []) for c in r]
        for t in texts:
            if TRACE.search(t):
                say(f"after carries a pipeline trace: {TRACE.search(t).group(0)!r}")
            if GAP.search(t):
                warn("after contains a [NEEDS DATA] placeholder; it will appear in the document as a visible hole")
        system = refs.get("system")
        if ch.get("kind") in ("add", "update", "correct") and basis == "evidence" and after:
            has_link = bool(re.search(r"\]\((?:https?|mailto):", after))
            if system == "linked_parenthetical" and not has_link:
                warn("new claim carries no citation in the document's style: a linked source name in parentheses")
            if system == "footnotes" and "^[" not in after:
                warn("new claim carries no footnote, the document's citation style")
            if system == "numbered" and not officedoc.NUMERIC.search(after):
                warn("new claim carries no numbered citation, the document's style")
        if system == "footnotes" and officedoc.NUMERIC.search(after):
            warn("bracketed numbers in a footnoted document")
        if system == "numbered":
            nxt = (refs.get("numbered") or {}).get("next")
            for m in officedoc.NUMERIC.finditer(after):
                for n in map(int, re.findall(r"\d+", m.group(1))):
                    if nxt and n > nxt + 20:
                        warn(f"citation [{n}] is far beyond the document's next number ({nxt})")
    spans = {}
    for ch in data.get("changes", []):
        t, before = ch.get("target"), ch.get("before") or ""
        text = (parts.get(t) or {}).get("text", "")
        if ch.get("op") == "replace" and before and text.count(before) == 1:
            s = text.index(before)
            for other, (o1, o2) in spans.get(t, {}).items():
                if s < o2 and o1 < s + len(before):
                    problems.append(f"{ch['id']}: overlaps {other} in {t}; merge them into one change")
            spans.setdefault(t, {})[ch["id"]] = (s, s + len(before))
    if not quiet:
        for p in problems:
            print(f"PROBLEM {p}")
        for wmsg in warnings:
            print(f"warn    {wmsg}")
        n = len(data.get("changes", []))
        print(f"{n} change(s) · {len(problems)} problem(s) · {len(warnings)} warning(s)")
    return problems, warnings


# ------------------------------------------------------------------ render

def render(run, slug):
    model = model_of(run, slug) or {"parts": []}
    parts = {p["id"]: p for p in model["parts"]}
    src = load_json(sdir(run, slug) / "source.json", {})
    ev = evidence_rows(run)
    rows = states(run, slug)
    counts = {}
    for _, st, _ in rows:
        counts[st] = counts.get(st, 0) + 1
    lines = [f"# Proposed changes: {Path(src.get('path', slug)).name}", "",
             " · ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "No changes proposed.", "",
             "| ID | Where | Kind | Change | Status |", "| --- | --- | --- | --- | --- |"]
    for ch, st, _ in rows:
        where = parts.get(ch.get("target"), {}).get("section") or ch.get("target")
        summary = " ".join((ch.get("summary") or ch.get("rationale") or "").split())[:90]
        lines.append(f"| {ch.get('id')} | {ch.get('target')} · {where} | {ch.get('kind')} | {summary} | {st} |")
    for ch, st, d in rows:
        where = parts.get(ch.get("target"), {}).get("section", "")
        lines += ["", f"## {ch.get('id')} · {ch.get('kind')} · {ch.get('op')} {ch.get('target')}"
                  + (f" ({where})" if where else ""), "", f"**Status:** {st}"]
        if ch.get("before"):
            lines += ["", "**Before:**", "", *[f"> {x}" for x in ch["before"].splitlines()]]
        elif ch.get("op") in ("insert_after", "insert_before") and ch.get("target") in parts:
            lines += ["", f"**{'After' if ch['op'] == 'insert_after' else 'Before'} this part:**", "",
                      f"> {parts[ch['target']]['text'][:300]}"]
        if ch.get("after") is not None:
            lines += ["", "**Proposed:**", "", *[f"> {x}" for x in str(ch["after"]).splitlines()]]
        if ch.get("rows"):
            lines += ["", "**Table rows:**", ""] + [" | ".join(map(str, r)) for r in ch["rows"]]
        if ch.get("fill"):
            lines += ["", "**Slide text:**", ""] + [f"- {k}: {v}" for k, v in ch["fill"].items()]
        if d and d.get("after") is not None and d["after"] != ch.get("after"):
            lines += ["", "**Author's text:**", "", *[f"> {x}" for x in d["after"].splitlines()]]
        lines += ["", f"**Why:** {ch.get('rationale', '')}"]
        if ch.get("evidence"):
            refs = []
            for eid in ch["evidence"]:
                row = ev.get(eid, {})
                refs.append(f"{eid} {row.get('title', '?')} ({row.get('publisher', '')}, {row.get('published', 'n.d.')})")
            lines += ["", "**Evidence:** " + "; ".join(refs)]
        elif ch.get("basis") and ch["basis"] != "evidence":
            lines += ["", f"**Basis:** {ch['basis']}"]
    out = sdir(run, slug) / "changes.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")
    return 0


def status(run, slug=None):
    items = [subjects.find(run, slug)] if slug else subjects.declared(run)
    for item in items:
        rows = states(run, item["slug"])
        counts = {}
        for _, st, _ in rows:
            counts[st] = counts.get(st, 0) + 1
        versions = sorted((Path(run) / "deliverable" / item["slug"]).glob("v*"))
        last = versions[-1].name if versions else "none"
        print(f"{item['slug']}: {len(rows)} change(s) "
              f"({', '.join(f'{n} {k}' for k, n in sorted(counts.items())) or 'none'}) · deliverable {last}")
    return 0


# ------------------------------------------------------------------ check

def latest_version(run, slug):
    base = Path(run) / "deliverable" / slug
    versions = sorted(base.glob("v*"), key=lambda p: int(p.name[1:]) if p.name[1:].isdigit() else 0)
    return versions[-1] if versions else None


def evidence_urls(run):
    urls = set()
    for row in evidence_rows(run).values():
        for key in ("url", "canonical_url"):
            if row.get(key):
                urls.add(row[key].rstrip("/"))
        for u in re.findall(r"https?://\S+", row.get("note") or ""):
            urls.add(u.rstrip("/.,;)"))
    return urls


def links_of(model, fmt):
    if fmt == "docx":
        return [x["url"] for x in model.get("links", [])]
    if fmt == "md":
        return [m for p in model["parts"] for m in re.findall(r"\]\(((?:https?|mailto):[^)\s]+)\)", p["text"])]
    return []


def check(run, slug, version=None):
    run = Path(run)
    item = subjects.find(run, slug)
    vdir = run / "deliverable" / slug / version if version else latest_version(run, slug)
    if vdir is None or not vdir.is_dir():
        sys.exit(f"ERROR no deliverable for {slug}: run apply_changes.py first")
    applied = load_json(vdir / "applied.json", None)
    if applied is None:
        sys.exit(f"ERROR {vdir} has no applied.json")
    src = run / "external_data" / item["path"]
    dest = vdir / applied["file"]
    orig, new = officedoc.read(src), officedoc.read(dest)
    fmt = orig["format"]
    changes = [c for c in applied["changes"] if c["id"] in
               {r["id"] for r in applied["results"] if r["status"] == "applied"}]
    problems, warnings = [], []

    if fmt == "xlsx":
        a = {p["id"]: p["text"] for p in orig["parts"] if p["kind"] in ("value", "formula")}
        b = {p["id"]: p["text"] for p in new["parts"] if p["kind"] in ("value", "formula")}
        targets = {c["target"]: c for c in changes}
        new_text = [str(b[c]) for c in targets if c in b]
        for cid in sorted(set(a) | set(b)):
            if a.get(cid) == b.get(cid):
                continue
            if cid not in targets:
                problems.append(f"{cid} changed without an accepted change: {a.get(cid)!r} → {b.get(cid)!r}")
                continue
            want = str(targets[cid]["after"])
            got = b.get(cid, "")
            same = got == want or _num(got) is not None and _num(got) == _num(want)
            if not same:
                problems.append(f"{targets[cid]['id']}: {cid} holds {got!r}, expected {want!r}")
    else:
        L = [(p["id"], p["text"]) for p in officedoc.leaves(orig)]
        N = [p["text"] for p in officedoc.leaves(new)]
        ids = [i for i, _ in L]
        touched, after_anchor, before_anchor = set(), set(), set()
        for c in changes:
            t, op = c["target"], c["op"]
            family = [i for i in ids if i == t or i.startswith(t + ".")]
            if op in ("replace", "delete"):
                touched.update(family or [t])
            if op in ("insert_after", "add_slide", "insert_table"):
                after_anchor.add(family[-1] if family else t)
            if op == "insert_before":
                before_anchor.add(family[0] if family else t)
        notes = {norm(seg["footnote"]) for c in changes for seg in officedoc.segments(c.get("after") or "")
                 if seg.get("footnote")}
        sm = difflib.SequenceMatcher(None, [t for _, t in L], N, autojunk=False)
        new_text = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            new_text += N[j1:j2]
            for i in range(i1, i2):
                if L[i][0] not in touched:
                    problems.append(f"{L[i][0]} changed without an accepted change: {L[i][1][:90]!r}")
            if all(norm(t) in notes for t in N[j1:j2]) and i1 == i2:
                continue                      # footnotes the accepted changes created
            if j2 - j1 > i2 - i1:
                prev_id = L[i1 - 1][0] if i1 > 0 else None
                next_id = L[i2][0] if i2 < len(L) else None
                near = {prev_id, next_id} | {L[i][0] for i in range(i1, i2)}
                if not (prev_id in after_anchor or next_id in before_anchor or near & touched
                        or _anchored(prev_id, after_anchor)):
                    problems.append(f"text added after {prev_id} without an accepted insert: {N[j1][:90]!r}")
        whole = norm("\n".join(N))
        for c in changes:
            if c["op"] in ("replace", "insert_after", "insert_before") and c.get("after"):
                for block in c["after"].split("\n\n"):
                    want = norm(officedoc.plain(DONOR.sub("", block.strip())))
                    if want and want not in whole:
                        problems.append(f"{c['id']}: its text is not in the deliverable: {want[:80]!r}")
        if fmt in ("docx", "pptx"):
            extra = set(officedoc.vocabulary(dest)) - set(officedoc.vocabulary(src))
            for kind, value in sorted(extra):
                problems.append(f"formatting the original does not use: {kind} {value}")
    for t in new_text:
        m = TRACE.search(t)
        if m:
            problems.append(f"pipeline trace in the deliverable: {m.group(0)!r} in {t[:80]!r}")
    known = evidence_urls(run)
    old_links = links_of(orig, fmt)
    for url in links_of(new, fmt):
        if url in old_links:
            old_links.remove(url)
            continue
        if url.rstrip("/") not in known:
            problems.append(f"new link to a URL that is not in evidence.jsonl: {url}")
    gaps = sum(len(GAP.findall(t)) for t in new_text)
    if gaps:
        warnings.append(f"{gaps} [NEEDS DATA] placeholder(s) are visible in the deliverable")
    refused = [r for r in applied["results"] if r["status"] != "applied"]
    for r in refused:
        warnings.append(f"{r['id']} was not applied: {r.get('reason')}")
    (vdir / "text.md").write_text(subjects.render_text(new, {**item, "path": applied["file"]}))
    result = {"deliverable": str(dest.relative_to(run)), "ok": not problems,
              "problems": problems, "warnings": warnings,
              "checked": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (vdir / "check.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for p in problems:
        print(f"PROBLEM {p}")
    for wmsg in warnings:
        print(f"warn    {wmsg}")
    print(f"{'PASS' if not problems else 'FAIL'} {dest.relative_to(run)} · "
          f"{len(changes)} change(s) applied · {len(problems)} problem(s)")
    return 0 if not problems else 1


def _anchored(prev_id, anchors):
    return prev_id is not None and any(prev_id.startswith(a + ".") for a in anchors)


def _num(text):
    try:
        return float(str(text))
    except ValueError:
        return None


# ------------------------------------------------------------------ fidelity

def _font_key(name):
    return re.sub(r"[\s_-]+", "", str(name)).lower()


def fidelity(run, slug, file):
    """A rebuilt file uses only the design's fonts and colours (and, warned, its sizes)."""
    d = sdir(run, slug)
    design = load_json(d / "design.json", None)
    if design is None:
        sys.exit(f"ERROR {slug} is not extracted")
    theme = load_json(d / "theme.json", {})
    fonts = {_font_key(f) for f in design.get("fonts", {})}
    fonts |= {_font_key(v) for v in (design.get("theme", {}).get("fonts") or {}).values() if v}
    fonts |= {_font_key(v) for v in (theme.get("fonts") or {}).values() if v}
    colors = {c.upper() for c in list(design.get("colors", {})) + list(design.get("fills", {}))
              + list(design.get("shading", {}))}
    colors |= {str(v).upper() for v in (design.get("theme", {}).get("colors") or {}).values() if v}
    colors |= {str(v).upper().lstrip("#") for v in (theme.get("colors") or {}).values()}
    sizes = {float(s) for s in design.get("sizes_pt", {})}
    problems, warnings = [], []
    slide_sizes = {v for (k, v) in officedoc.vocabulary(file, slides_only=True) if k == "size"}
    for (kind, value), n in sorted(officedoc.vocabulary(file).items()):
        if kind == "font" and _font_key(value) not in fonts:
            problems.append(f"font {value} ({n}×) is not in the design")
        elif kind == "color" and value.upper() not in colors:
            problems.append(f"colour {value} ({n}×) is not in the design")
        elif kind == "size" and value in slide_sizes and sizes and not any(abs(float(value) - s) <= 0.6 for s in sizes):
            warnings.append(f"size {value}pt ({n}×) is not one the design uses")
    vdir = Path(file).resolve().parent
    if vdir.parent.name == slug and vdir.name.startswith("v"):      # a rebuilt deliverable: record it
        (vdir / "check.json").write_text(json.dumps({
            "deliverable": Path(file).name, "kind": "fidelity", "ok": not problems,
            "problems": problems, "warnings": warnings,
            "checked": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=2) + "\n")
    for p in problems:
        print(f"PROBLEM {p}")
    for wmsg in warnings:
        print(f"warn    {wmsg}")
    print(f"{'PASS' if not problems else 'FAIL'} {Path(file).name} against {slug}'s design")
    return 0 if not problems else 1


def main():
    argv = sys.argv[1:]
    opts = {}
    for key in ("--after", "--note", "--by"):
        if key in argv:
            i = argv.index(key)
            opts[key[2:]] = argv[i + 1]
            del argv[i:i + 2]
    args = [x for x in argv if not x.startswith("--")]
    if len(args) < 2:
        sys.exit(__doc__)
    cmd, run = args[0], Path(args[1])
    if not run.is_dir():
        sys.exit(f"ERROR no such run: {run}")
    slug = subjects.find(run, args[2])["slug"] if len(args) > 2 else None
    if cmd == "validate" and slug:
        problems, _ = validate(run, slug)
        return 1 if problems else 0
    if cmd == "render" and slug:
        return render(run, slug)
    if cmd == "status":
        return status(run, slug)
    if cmd == "decide" and slug and len(args) >= 5:
        ids = ["all"] if args[3] == "all" else args[3].split(",")
        return decide(run, slug, ids, args[4], opts.get("after"), opts.get("note"), opts.get("by", "author"))
    if cmd == "check" and slug:
        return check(run, slug, args[3] if len(args) > 3 else None)
    if cmd == "fidelity" and slug and len(args) >= 4:
        return fidelity(run, slug, args[3])
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
