#!/usr/bin/env python3
"""plagiarism.py — similarity check of a report against the sources it was built from.

    plagiarism.py check  <run|report.md> [--corpus run|library] [--urls FILE]
                         [--min-run 8] [--out plagiarism.md] [--json]
    plagiarism.py probes <run|report.md> [--limit 12]

check compares every sentence of the master document with the full text of the pages
the run read (the stored copy of each evidence row's URL in `library/`, or the row's
quote when no copy exists) and with the files in `external_data/`. `--corpus library`
adds every page in the shared library; `--urls` adds pages found by a web search (one
URL per line), fetching any that are not stored yet.

Two detectors, the methods commercial checkers use:

    verbatim     word 5-gram fingerprints, extended to the longest common run of words.
                 A run of --min-run words or more is a match.
    paraphrase   a sentence whose content words (stopwords and numbers removed, crude
                 stemming) are largely found, in largely the same order, inside one
                 short window of a source: the same sentence with words swapped.

Each match is classed by whether the report puts it in quotation marks and whether
the paragraph cites the matching source, then scored:

    similarity index   share of the report's words in unquoted verbatim runs
    paraphrase share   share in close-paraphrase sentences not already counted
    quoted share       share inside quotation marks that matches a source
    originality        100 minus similarity and paraphrase
    risk score         a weighted share: uncited verbatim 1.0, cited verbatim 0.5,
                       uncited paraphrase 0.6, cited paraphrase 0.3, AI-report text 1.0

It writes `<run>/plagiarism.md` (the findings, per section, with a fix for each) and
`<run>/plagiarism.json`. probes prints the distinctive sentences no local source
explains, as exact phrases for a web search. Neither command edits the report or
makes a model call. Exit 0 when the risk band is Low or Moderate, 1 when High or
Very high.
"""
import argparse
from collections import defaultdict
from difflib import SequenceMatcher
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import library                                             # noqa: E402
from section_guard import DERIVED, PREAMBLE, split_sections  # noqa: E402
from section_map import master                             # noqa: E402

SHINGLE = 5
EVIDENCE = re.compile(r"\[(E\d+(?:\s*[,;–-]\s*E?\d+)*)\]")
EID = re.compile(r"E?(\d+)")
WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
QUOTED = re.compile(r'"[^"\n]{3,}?"')          # after library.norm, curly quotes are "
SKIP_FILES = {"README.md", "WANTED.md", "index.json", ".index.json"}
TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".html", ".htm", ".json", ".pdf"}

STOP = set("""a about above after again against all also am an and any are as at be
because been before being below between both but by can could did do does doing down
during each few for from further had has have having he her here hers him his how i if
in into is it its itself just may me might more most must my no nor not now of off on
once only or other our ours out over own same shall she should so some such than that
the their theirs them then there these they this those through to too under until up
upon very was we were what when where which while who whom why will with within without
would you your yours per via across among around""".split())

BANDS = [(5, "Low"), (15, "Moderate"), (30, "High"), (101, "Very high")]
WEIGHT = {"verbatim-uncited": 1.0, "verbatim-cited": 0.5, "paraphrase-uncited": 0.6,
          "paraphrase-cited": 0.3, "ai-report": 1.0}
SEVERITY = {"verbatim-uncited": "High", "ai-report": "High", "verbatim-cited": "Medium",
            "paraphrase-uncited": "Medium", "paraphrase-cited": "Low", "quoted": "Info"}


def band(score):
    return next(name for top, name in BANDS if score < top)


def stem(w):
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "edly", "ed", "ers",
                "er", "es", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def keep(t):
    return t not in STOP and not t[0].isdigit() and len(t) > 2


def content(tokens):
    return [stem(t) for t in tokens if keep(t)]


def ids_in(text):
    out = set()
    for group in EVIDENCE.findall(text):
        out.update(f"E{n}" for n in EID.findall(group))
    return out


# ------------------------------------------------------------------ the report

def report_units(path):
    """Sentences (and table rows) of the master, with section, line, cited IDs and the
    token-level quoted mask. Headings, figure blocks, comments and the derived
    sections (sources, data still to obtain) are left out."""
    text = path.read_text()
    units, line = [], 1
    for key, body in split_sections(text).items():
        head = 0 if key == PREAMBLE else 1
        section = "(opening)" if key == PREAMBLE else key.lstrip("# ").strip()
        skip = key in DERIVED or any(d.lower() in key.lower() for d in DERIVED)
        start = line + head
        line += head + body.count("\n")
        if skip:
            continue
        fence = False
        para, para_line = [], start
        for i, raw in enumerate(body.splitlines() + [""]):
            if raw.strip().startswith(("```", "~~~")):
                fence = not fence
                continue
            if fence or raw.strip().startswith(("<!--", "![", "<", "#")):
                continue
            if not raw.strip():
                if para:
                    units.extend(split_para(" ".join(para), section, para_line))
                para, para_line = [], start + i + 1
                continue
            if raw.lstrip().startswith("|"):
                if not re.fullmatch(r"\s*\|[\s:|-]+\|?\s*", raw):
                    units.extend(split_para(raw.replace("|", " "), section, start + i, table=True))
                continue
            if not para:
                para_line = start + i
            para.append(raw.strip().lstrip("-*> ").strip())
    return units


def split_para(text, section, line, table=False):
    cited = ids_in(text)
    clean = re.sub(r"\[[^\]]*\]\([^)]*\)", lambda m: m.group(0)[1:m.group(0).index("]")], text)
    clean = EVIDENCE.sub("", clean).replace("**", "").replace("`", "")
    out = []
    for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", clean):
        normed = library.norm(sent)
        quoted = [(m.start(), m.end()) for m in QUOTED.finditer(normed)]
        tokens, mask = [], []
        for m in WORD.finditer(normed):
            tokens.append(m.group(0))
            mask.append(any(a <= m.start() < b for a, b in quoted))
        if tokens:
            out.append({"section": section, "line": line, "text": sent.strip(),
                        "cited": cited, "tokens": tokens, "quoted": mask, "table": table})
    return out


# ------------------------------------------------------------------ the corpus

def corpus(run, mode, urls_file):
    docs, seen = [], set()

    def add(key, label, url, eids, text, kind):
        if key in seen or not text or len(text) < 40:
            return
        seen.add(key)
        docs.append({"key": key, "label": label, "url": url, "eids": set(eids),
                     "kind": kind, "tokens": WORD.findall(library.norm(text))})

    by_url = defaultdict(list)
    rows = []
    ledger = run / "evidence.jsonl" if run else None
    if ledger and ledger.exists():
        for line in ledger.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            rows.append(row)
            if row.get("url"):
                by_url[library.normal_url(row["url"])].append(row["id"])
    for row in rows:
        url = row.get("url") or ""
        eids = by_url.get(library.normal_url(url), [row["id"]]) if url else [row["id"]]
        label = row.get("title") or row.get("publisher") or url or row["id"]
        stored = library.stored(url)[1] if url.startswith("http") else None
        if stored:
            add(library.key(url), label, url, eids, stored, "source")
        else:
            add(f"quote:{row['id']}", f"{label} (quote only)", url, [row["id"]],
                row.get("quote", ""), "source")

    if run:
        ext = run / "external_data"
        for p in sorted(ext.rglob("*")) if ext.exists() else []:
            if p.is_dir() or p.name in SKIP_FILES or p.name.startswith(".") \
                    or p.suffix.lower() not in TEXT_EXT:
                continue
            try:
                if p.suffix.lower() in (".pdf", ".html", ".htm"):
                    ctype = "application/pdf" if p.suffix.lower() == ".pdf" else "text/html"
                    text = library.to_text(ctype, p.read_bytes(), str(p))[1]
                else:
                    text = p.read_text(errors="replace")
            except (OSError, ValueError):
                continue
            rel = p.relative_to(run)
            kind = "ai-report" if "ai_reports" in rel.parts else "supplied"
            add(f"file:{rel}", str(rel), str(rel), [], text, kind)

    extra = []
    if urls_file:
        extra = [u.strip() for u in Path(urls_file).read_text().splitlines()
                 if u.strip().startswith("http")]
    for url in extra:
        rec, text = library.stored(url)
        if text is None:
            try:
                library.fetch(url, run=run.name if run else "")
            except Exception as exc:                # noqa: BLE001 — a dead link is not fatal
                print(f"could not fetch {url}: {exc}", file=sys.stderr)
            rec, text = library.stored(url)
        if text:
            add(library.key(url), (rec or {}).get("title") or url, url,
                by_url.get(library.normal_url(url), []), text, "web")

    if mode == "library":
        for key, rec in library.index().items():
            if rec.get("status") != "ok" or key in seen:
                continue
            path = library.PAGES / f"{key}.txt"
            if path.exists():
                add(key, rec.get("title") or rec["url"], rec["url"],
                    by_url.get(library.normal_url(rec["url"]), []), path.read_text(), "library")
    return docs


# ------------------------------------------------------------------ detection

def verbatim(units, docs, min_run):
    """Longest common word runs between the report and each document."""
    flat, owner = [], []
    for u_i, u in enumerate(units):
        for t_i, tok in enumerate(u["tokens"]):
            flat.append(tok)
            owner.append((u_i, t_i))
    grams = defaultdict(list)
    for i in range(len(flat) - SHINGLE + 1):
        grams[tuple(flat[i:i + SHINGLE])].append(i)
    runs = []
    for d_i, doc in enumerate(docs):
        dt = doc["tokens"]
        found, seen = {}, set()          # found: report start -> length; seen: (i, j) pairs
        for j in range(len(dt) - SHINGLE + 1):
            for i in grams.get(tuple(dt[j:j + SHINGLE]), ()):
                if (i, j) in seen:
                    continue
                a, b = i, j
                while a > 0 and b > 0 and flat[a - 1] == dt[b - 1]:
                    a, b = a - 1, b - 1
                n = 0
                while a + n < len(flat) and b + n < len(dt) and flat[a + n] == dt[b + n]:
                    n += 1
                seen.update((a + k, b + k) for k in range(n))
                if n >= min_run and found.get(a, 0) < n:
                    found[a] = n
        covered = -1
        for a in sorted(found):
            n = found[a]
            if a + n <= covered:
                continue
            runs.append({"doc": d_i, "start": a, "len": n})
            covered = a + n
    return flat, owner, runs


def paraphrase(unit, docs, skip_docs):
    """Best (doc, containment, order ratio, window text) for one sentence."""
    sc = content(unit["tokens"])
    sset = set(sc)
    if len(sset) < 8:
        return None
    best = None
    for d_i, doc in enumerate(docs):
        if d_i in skip_docs:
            continue
        if "cset" not in doc:
            doc["cpos"] = [k for k, t in enumerate(doc["tokens"]) if keep(t)]
            doc["cseq"] = [stem(doc["tokens"][k]) for k in doc["cpos"]]
            doc["cset"] = set(doc["cseq"])
        if len(sset & doc["cset"]) < 0.7 * len(sset):
            continue
        seq, width = doc["cseq"], max(len(sc) * 2, 12)
        hits = [p for p, w in enumerate(seq) if w in sset]
        lo = 0
        for hi in range(len(hits)):
            while hits[hi] - hits[lo] >= width:
                lo += 1
            if hi - lo + 1 < 0.7 * len(sset):
                continue
            window = seq[hits[lo]:hits[hi] + 1]
            contain = len(sset & set(window)) / len(sset)
            if contain < 0.7:
                continue
            ratio = SequenceMatcher(None, sc, window, autojunk=False).ratio()
            if best is None or (contain, ratio) > (best[1], best[2]):
                cp = doc["cpos"]
                best = (d_i, contain, ratio,
                        " ".join(doc["tokens"][cp[hits[lo]]:cp[hits[hi]] + 1]))
    if best and best[1] >= 0.75 and best[2] >= 0.55:
        return best
    return None


# ------------------------------------------------------------------ scoring

FIX = {
    "verbatim-uncited": "These words are the source's own and the paragraph does not cite it. "
                        "Cite {src}, then either put the exact words in quotation marks or "
                        "restate the point in your own sentence structure.",
    "verbatim-cited": "Cited, but {n} consecutive words are copied. Quote them exactly in "
                      "quotation marks, or keep the fact and rewrite the wording and order. "
                      "If the run is a name or a title, no change is needed.",
    "paraphrase-uncited": "Close paraphrase of a source the paragraph does not cite. Cite "
                          "{src} and rebuild the sentence around your own point rather "
                          "than swapping synonyms into the source's structure.",
    "paraphrase-cited": "Follows the cited source's sentence too closely. Lead with your own "
                        "conclusion, merge it with other evidence, or quote the key phrase.",
    "ai-report": "Wording comes from a supplied AI-generated report, which is not a source. "
                 "Rewrite it from the primary sources and cite those.",
    "quoted": "Correctly quoted. Keep it only if the exact wording carries weight; "
              "otherwise summarise.",
}


def cite_label(doc):
    return ", ".join(f"[{e}]" for e in sorted(doc["eids"], key=lambda e: int(e[1:]))) \
        or "the source (add it to the evidence ledger first)"


def analyse(units, docs, min_run):
    flat, owner, runs = verbatim(units, docs, min_run)
    total = len(flat)
    state = ["original"] * total
    findings = []

    for r in sorted(runs, key=lambda r: -r["len"]):
        doc = docs[r["doc"]]
        idx = range(r["start"], r["start"] + r["len"])
        fresh = [k for k in idx if state[k] == "original"]
        if len(fresh) < min_run // 2:
            continue
        quoted = sum(units[owner[k][0]]["quoted"][owner[k][1]] for k in idx) > r["len"] / 2
        u = units[owner[r["start"]][0]]
        cited = bool(doc["eids"] & u["cited"])
        kind = ("quoted" if quoted else "ai-report" if doc["kind"] == "ai-report"
                else "verbatim-cited" if cited else "verbatim-uncited")
        for k in fresh:
            state[k] = kind
        findings.append({"type": kind, "section": u["section"], "line": u["line"],
                         "words": r["len"], "excerpt": " ".join(flat[r["start"]:r["start"] + r["len"]]),
                         "sentence": u["text"], "doc": r["doc"]})

    base = 0
    for u_i, u in enumerate(units):
        span = range(base, base + len(u["tokens"]))
        base += len(u["tokens"])
        if sum(state[k] == "original" for k in span) < 0.6 * len(span):
            continue
        hit = paraphrase(u, docs, skip_docs=set())
        if not hit:
            continue
        d_i, contain, ratio, window = hit
        doc = docs[d_i]
        cited = bool(doc["eids"] & u["cited"])
        kind = "ai-report" if doc["kind"] == "ai-report" else \
            "paraphrase-cited" if cited else "paraphrase-uncited"
        for k in span:
            if state[k] == "original":
                state[k] = kind
        findings.append({"type": kind, "section": u["section"], "line": u["line"],
                         "words": len(u["tokens"]), "excerpt": window, "sentence": u["text"],
                         "doc": d_i, "overlap": round(contain, 2), "order": round(ratio, 2)})

    pct = lambda n: round(100 * n / total, 1) if total else 0.0
    count = defaultdict(int)
    for s in state:
        count[s] += 1
    verbatim_n = count["verbatim-cited"] + count["verbatim-uncited"] + count["ai-report"]
    para_n = count["paraphrase-cited"] + count["paraphrase-uncited"]
    risk = sum(WEIGHT.get(s, 0) for s in state)

    sections = defaultdict(lambda: defaultdict(int))
    base = 0
    for u in units:
        for k in range(base, base + len(u["tokens"])):
            sections[u["section"]]["words"] += 1
            sections[u["section"]][state[k]] += 1
            sections[u["section"]]["risk"] += WEIGHT.get(state[k], 0)
        base += len(u["tokens"])

    by_source = defaultdict(int)
    for f in findings:
        if f["type"] != "quoted":
            by_source[f["doc"]] += f["words"]

    for f in findings:
        doc = docs[f["doc"]]
        f["source"] = {"label": doc["label"], "url": doc["url"], "eids": sorted(doc["eids"]),
                       "kind": doc["kind"]}
        f["severity"] = SEVERITY[f["type"]]
        if f["type"] == "verbatim-cited":
            f["severity"] = "Low" if f["words"] < 12 else "Medium" if f["words"] < 20 else "High"
        if f["type"] == "verbatim-uncited" and f["words"] < 12:
            f["severity"] = "Medium"
        if f["type"] == "paraphrase-cited" and f["overlap"] >= 0.85 and f["order"] >= 0.7:
            f["severity"] = "Medium"
        f["fix"] = FIX[f["type"]].format(src=cite_label(doc), n=f["words"])
        del f["doc"]

    return {
        "words": total,
        "similarity_index": pct(verbatim_n),
        "paraphrase_share": pct(para_n),
        "quoted_share": pct(count["quoted"]),
        "originality": round(100 - pct(verbatim_n) - pct(para_n), 1),
        "risk_score": pct(risk),
        "risk_band": band(pct(risk)),
        "sources_checked": len(docs),
        "sources_quote_only": sum(d["key"].startswith("quote:") for d in docs),
        "top_sources": [{"label": docs[d]["label"], "url": docs[d]["url"],
                         "eids": sorted(docs[d]["eids"]), "share": pct(n)}
                        for d, n in sorted(by_source.items(), key=lambda x: -x[1])[:10]],
        "sections": [{"section": s, "words": v["words"],
                      "similarity": round(100 * (v["verbatim-cited"] + v["verbatim-uncited"]
                                                 + v["ai-report"]) / v["words"], 1),
                      "paraphrase": round(100 * (v["paraphrase-cited"]
                                                 + v["paraphrase-uncited"]) / v["words"], 1),
                      "risk": round(100 * v["risk"] / v["words"], 1),
                      "band": band(100 * v["risk"] / v["words"])}
                     for s, v in sections.items()],
        "findings": sorted(findings, key=lambda f: (
            ["High", "Medium", "Low", "Info"].index(f["severity"]), -f["words"])),
        "state": state,
    }


# ------------------------------------------------------------------ output

def write_md(path, report_path, result, min_run, mode):
    r = result
    lines = [
        f"# Similarity check: {report_path.name}", "",
        f"Corpus: {r['sources_checked']} sources ({mode}); "
        f"{r['sources_quote_only']} available only as the ledger's quote. "
        f"Verbatim threshold: {min_run} words.", "",
        "| Measure | Value |", "|---|---|",
        f"| Originality | **{r['originality']}%** |",
        f"| Plagiarism risk | **{r['risk_score']}% ({r['risk_band']})** |",
        f"| Similarity index (unquoted verbatim) | {r['similarity_index']}% |",
        f"| Close paraphrase | {r['paraphrase_share']}% |",
        f"| Quoted and matched (excluded) | {r['quoted_share']}% |",
        f"| Words checked | {r['words']} |", "",
        "Risk bands: Low under 5, Moderate 5 to 15, High 15 to 30, Very high 30 and over.", "",
        "## Sections", "",
        "| Section | Words | Similarity | Paraphrase | Risk | Band |", "|---|---|---|---|---|---|",
    ]
    for s in r["sections"]:
        lines.append(f"| {s['section']} | {s['words']} | {s['similarity']}% | "
                     f"{s['paraphrase']}% | {s['risk']}% | {s['band']} |")
    lines += ["", "## Matched sources", ""]
    for s in r["top_sources"] or []:
        ids = " ".join(f"[{e}]" for e in s["eids"]) or "(not in the ledger)"
        lines.append(f"- {s['share']}% {ids} {s['label']} {s['url']}")
    if not r["top_sources"]:
        lines.append("- None.")
    lines += ["", "## Findings", ""]
    if not r["findings"]:
        lines.append("No passage matched a source above the thresholds.")
    for n, f in enumerate(r["findings"], 1):
        src = f["source"]
        ids = " ".join(f"[{e}]" for e in src["eids"]) or "not cited anywhere in the run"
        extra = f", overlap {f['overlap']}, order {f['order']}" if "overlap" in f else ""
        lines += [
            f"### P{n}. {f['severity']} · {f['type']} · {f['section']} (line {f['line']})",
            f"- **Report:** {f['sentence'][:400]}",
            f"- **Matched:** \"{f['excerpt'][:300]}\" ({f['words']} words{extra})",
            f"- **Source:** {src['label']} {ids} {src['url']}",
            f"- **Fix:** {f['fix']}", "",
        ]
    lines += ["## Not covered", "",
              "Paywalled journals, student-paper archives and pages no search returned are "
              "outside this check. A low score means the report does not reuse the wording "
              "of the sources it read or the pages the web search found; it is not a "
              "guarantee against every published text.", ""]
    path.write_text("\n".join(lines))


def probes(units, state, limit):
    base, cands = 0, []
    for u in units:
        span = range(base, base + len(u["tokens"]))
        base += len(u["tokens"])
        toks = u["tokens"]
        words = [t for t in toks if not t[0].isdigit()]
        if u["table"] or len(words) < 14 or len(words) < 0.8 * len(toks) \
                or any(state[k] != "original" for k in span):
            continue
        score = len(content(toks)) + (6 if not u["cited"] else 0)
        mid = max(0, len(toks) // 2 - 5)
        cands.append((score, u["section"], u["line"], " ".join(toks[mid:mid + 10]), u["text"]))
    cands.sort(key=lambda c: -c[0])
    return cands[:limit]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["check", "probes"])
    ap.add_argument("target")
    ap.add_argument("--corpus", choices=["run", "library"], default="run")
    ap.add_argument("--urls", help="file of extra source URLs, one per line")
    ap.add_argument("--min-run", type=int, default=8)
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--out", default="plagiarism.md")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    report = master(a.target)
    run = report.parent if (report.parent / "evidence.jsonl").exists() \
        or (report.parent / "prompt.md").exists() else None
    units = report_units(report)
    docs = corpus(run, a.corpus, a.urls)
    result = analyse(units, docs, a.min_run)

    if a.cmd == "probes":
        for score, section, line, phrase, text in probes(units, result["state"], a.limit):
            print(f'{section} (line {line})\t"{phrase}"')
        return 0

    state = result.pop("state")
    out = Path(a.out) if Path(a.out).is_absolute() else (run or report.parent) / a.out
    out.with_suffix(".json").write_text(json.dumps(result, indent=1))
    write_md(out, report, result, a.min_run, a.corpus)
    if a.json:
        print(json.dumps(result, indent=1))
    else:
        print(f"{report}: originality {result['originality']}%, risk {result['risk_score']}% "
              f"({result['risk_band']}); similarity {result['similarity_index']}%, "
              f"paraphrase {result['paraphrase_share']}%, quoted {result['quoted_share']}%; "
              f"{len(result['findings'])} findings, {result['sources_checked']} sources "
              f"-> {out}")
    del state
    return 1 if result["risk_band"] in ("High", "Very high") else 0


if __name__ == "__main__":
    sys.exit(main())
