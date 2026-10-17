#!/usr/bin/env python3
"""library.py — every source page fetched once, kept as text, shared by every run.

    library.py fetch <url> [--run R] [--max-age DAYS] [--grep PAT [--context N]] [--range A:B]
    library.py get   <url> [--grep PAT …] [--range A:B]     # stored copy only, no network
    library.py check <run> [--ids E1,E7 | --file rounds/r2/to-verify.md] [--max-age DAYS]
    library.py search "<terms>" [--limit N]                  # stored pages by content
    library.py stats

fetch returns the stored copy when it is younger than --max-age (default 30 days),
otherwise downloads the page with a plain HTTP request, converts HTML or PDF to text,
and stores it. It prints a header and, by default, the first 2,500 characters; --grep
prints only matching lines with context, and --range prints a character span. Reading
a page this way costs a scout far less than a WebFetch of the same page, and the text
it read is kept for whoever checks the quote later.

A page the script cannot read (a login, a paywall, a page built by JavaScript, a
refusal) is recorded as such and fetch exits 2: use WebFetch for it, as before. A
stored copy is the page as fetched on its recorded date, by this script, not a model's
summary of it, which is what makes it usable as a check.

check is the mechanical half of verification. For each evidence row it looks for the
row's quote in the stored copy of the row's URL:

    MATCH     every segment of the quote is in the stored text
    PARTIAL   some segments are, some are not (an ellipsis, `|`, `;` or ` / ` splits a
              quote into segments, since scouts join table cells that way)
    ABSENT    the copy exists and no segment of the quote is in it. Not a verdict: a
              quote rebuilt from a table, or a page that changed, lands here too.
              Confirm with a live fetch, as verification always did
    STALE     matched, but the copy is older than --max-age
    NO-COPY   nothing stored (WebFetch was used, a local file, or a copy too thin to
              judge, such as a script-built page): verify as before

It makes no model call. The library lives in `library/` at the workspace root and is
excluded from git with the rest of the research material.
"""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import html.parser
import json
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "library"
PAGES = LIB / "pages"
INDEX = LIB / "index.jsonl"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
MAX_BYTES = 25_000_000
DEFAULT_AGE = 30
HEAD_CHARS = 2500
# Below THIN an HTML page is refused outright; below SHELL it is kept but flagged, since a
# page built by JavaScript leaves little more than its navigation for a plain request.
THIN = 400
SHELL = 1500


# ------------------------------------------------------------------ storage

def key(url):
    return hashlib.sha256(normal_url(url).encode()).hexdigest()[:20]


def normal_url(url):
    return url.split("#", 1)[0].strip().rstrip("/")


def index():
    """Latest record per key."""
    out = {}
    if INDEX.exists():
        for line in INDEX.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            out[rec["key"]] = rec
    return out


def record(rec):
    LIB.mkdir(exist_ok=True)
    with INDEX.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def stored(url):
    rec = index().get(key(url))
    if rec and rec.get("status") == "ok":
        path = PAGES / f"{rec['key']}.txt"
        if path.exists():
            return rec, path.read_text()
    return rec, None


def age_days(rec):
    return (time.time() - rec.get("fetched_ts", 0)) / 86400


# ------------------------------------------------------------------ fetching

class Text(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
    BLOCK = {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3", "h4",
             "h5", "h6", "table", "blockquote", "pre", "dd", "dt", "figcaption", "caption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self.in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag == "title":
            self.in_title = False
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)

    def text(self):
        raw = "".join(self.out)
        lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in raw.splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


RETRY_HTTP = {429, 500, 502, 503, 504}


def retry_delay(attempt, retry_after=""):
    """Bound a server's Retry-After or exponential wait to 60 seconds."""
    try:
        delay = float(retry_after)
    except ValueError:
        try:
            delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            delay = 2 ** (attempt + 1)
    return min(60, max(0, delay))


def download(url, retries=2):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=40) as res:
                ctype = res.headers.get("Content-Type", "")
                body = res.read(MAX_BYTES + 1)
                final = res.geturl()
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_HTTP or attempt >= retries:
                raise
            delay = retry_delay(attempt, exc.headers.get("Retry-After", "") if exc.headers else "")
        except (urllib.error.URLError, TimeoutError):
            if attempt >= retries:
                raise
            delay = retry_delay(attempt)
        print(f"Temporary fetch failure; retrying in {delay:g} seconds ({attempt + 1}/{retries}).", file=sys.stderr)
        time.sleep(delay)
    if len(body) > MAX_BYTES:
        raise ValueError("larger than 25 MB")
    return ctype, body, final


def to_text(ctype, body, url):
    if "pdf" in ctype or body[:5] == b"%PDF-" or url.lower().endswith(".pdf"):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(body)
            tmp.flush()
            try:
                out = subprocess.run(["pdftotext", "-layout", tmp.name, "-"],
                                     capture_output=True, text=True, timeout=120)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ValueError(f"PDF text extraction failed: {exc}") from exc
            return "", out.stdout.strip(), "pdf"
    charset = re.search(r"charset=([\w-]+)", ctype)
    decoded = body.decode(charset.group(1) if charset else "utf-8", errors="replace")
    if "html" in ctype or "<html" in decoded[:2000].lower():
        p = Text()
        p.feed(decoded)
        return html.unescape(p.title.strip()), p.text(), "html"
    return "", decoded.strip(), "text"


def fetch(url, run="", max_age=DEFAULT_AGE):
    """(record, text or None). Uses the stored copy when it is fresh enough."""
    rec, text = stored(url)
    if text is not None and age_days(rec) <= max_age:
        return rec, text
    k = key(url)
    base = {"key": k, "url": normal_url(url), "fetched": time.strftime("%Y-%m-%d"),
            "fetched_ts": time.time(), "run": run}
    try:
        ctype, body, final = download(url)
        title, text, kind = to_text(ctype, body, url)
    except urllib.error.HTTPError as exc:
        rec = {**base, "status": "failed", "reason": f"HTTP {exc.code}"}
        record(rec)
        return rec, None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        rec = {**base, "status": "failed", "reason": str(exc)[:200]}
        record(rec)
        return rec, None
    if kind == "html" and len(text) < THIN:
        rec = {**base, "status": "failed",
               "reason": f"only {len(text)} characters of text: a script-built page or a block page"}
        record(rec)
        return rec, None
    PAGES.mkdir(parents=True, exist_ok=True)
    (PAGES / f"{k}.txt").write_text(text)
    rec = {**base, "status": "ok", "final_url": final, "title": title, "kind": kind,
           "chars": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
           "thin": kind == "html" and len(text) < SHELL}
    record(rec)
    return rec, text


# ------------------------------------------------------------------ reading

def show(rec, text, grep=None, context=1, span=None):
    print(f"URL: {rec['url']}")
    print(f"FETCHED: {rec['fetched']} · {rec.get('kind', '?')} · {rec.get('chars', 0):,} chars"
          + (f" · {rec['title']}" if rec.get("title") else ""))
    if rec.get("thin"):
        print("THIN: little text came back; the page is probably built by JavaScript. "
              "If what you need is not below, use WebFetch.")
    if span:
        a, _, b = span.partition(":")
        a, b = int(a or 0), int(b or len(text))
        print(f"RANGE {a}:{b}\n{text[a:b]}")
        return
    if grep:
        pat = re.compile(grep, re.I)
        lines = text.splitlines()
        hits = [i for i, ln in enumerate(lines) if pat.search(ln)]
        if not hits:
            print(f"NO MATCH for /{grep}/")
            return
        shown = set()
        for i in hits[:40]:
            lo, hi = max(0, i - context), min(len(lines), i + context + 1)
            if any(j in shown for j in range(lo, hi)):
                lo = max(lo, max(shown) + 1)
            if lo >= hi:
                continue
            print(f"--- line {lo + 1}")
            for j in range(lo, hi):
                print(lines[j])
                shown.add(j)
        if len(hits) > 40:
            print(f"… {len(hits) - 40} more matches; narrow the pattern")
        return
    print(text[:HEAD_CHARS])
    if len(text) > HEAD_CHARS:
        print(f"\n… {len(text) - HEAD_CHARS:,} more characters: use --grep PAT or --range A:B")


# ------------------------------------------------------------------ quote check

DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
QUOTES = {ord(c): "'" for c in "‘’‚‛′"} | \
         {ord(c): '"' for c in "“”„‟″"}


def norm(s):
    s = unicodedata.normalize("NFKC", s).translate(DASHES).translate(QUOTES)
    s = re.sub(r"-\s*\n\s*", "", s)       # words hyphenated across PDF lines
    s = re.sub(r"\s+", " ", s)
    return s.lower().strip()


def segments(quote):
    parts = re.split(r"\s*(?:\.\.\.|…|\[\.\.\.\]|\[…\]|\||;|\s/\s|\"\s*/\s*\")\s*", quote)
    return [p.strip(" \"'") for p in parts if len(p.strip(" \"'")) >= 12]


def rows(run, ids=None, file=None):
    ledger = Path(run) / "evidence.jsonl"
    wanted = None
    if ids:
        wanted = {i.strip() for i in ids.split(",") if i.strip()}
    if file:
        text = (Path(run) / file).read_text() if not Path(file).exists() else Path(file).read_text()
        wanted = (wanted or set()) | set(re.findall(r"E\d+", text))
    out = []
    for line in ledger.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if wanted is None or row.get("id") in wanted:
            out.append(row)
    return out


def check(run, ids=None, file=None, max_age=DEFAULT_AGE):
    counts = {}
    for row in rows(run, ids, file):
        url, quote = row.get("url", ""), row.get("quote", "")
        if not url.startswith("http"):
            verdict, note = "NO-COPY", "local or non-web source"
        else:
            rec, text = stored(url)
            segs = segments(quote)
            if text is None:
                verdict, note = "NO-COPY", (rec or {}).get("reason", "not in the library")
            elif rec.get("thin"):
                verdict, note = "NO-COPY", "stored copy too thin to judge (script-built page)"
            elif not segs:
                verdict, note = "NO-COPY", "quote too short to check mechanically"
            else:
                hay = norm(text)
                found = [norm(s) in hay for s in segs]
                if all(found):
                    old = age_days(rec) > max_age
                    verdict = "STALE" if old else "MATCH"
                    note = f"copy of {rec['fetched']}"
                elif any(found):
                    verdict, note = "PARTIAL", f"{found.count(False)} of {len(segs)} segments missing"
                else:
                    verdict, note = "ABSENT", f"copy of {rec['fetched']}; confirm with a live fetch"
        counts[verdict] = counts.get(verdict, 0) + 1
        print(f"{row.get('id', '?'):7} {verdict:8} {note}")
    summary = " · ".join(f"{k.lower()} {v}" for k, v in sorted(counts.items()))
    print(f"CHECKED {sum(counts.values())} | {summary}")
    return 1 if counts.get("ABSENT") or counts.get("PARTIAL") else 0


# ------------------------------------------------------------------ the rest

def search(terms, limit=10):
    words = [w.lower() for w in terms.split() if len(w) > 2]
    scored = []
    for rec in index().values():
        if rec.get("status") != "ok":
            continue
        path = PAGES / f"{rec['key']}.txt"
        if not path.exists():
            continue
        text = path.read_text().lower()
        score = sum(text.count(w) for w in words)
        if score and all(w in text for w in words):
            scored.append((score, rec))
    for score, rec in sorted(scored, key=lambda x: -x[0])[:limit]:
        print(f"{score:5}  {rec['fetched']}  {rec['url']}" + (f"  · {rec['title'][:60]}" if rec.get("title") else ""))
    return 0 if scored else 1


def stats():
    recs = index().values()
    ok = [r for r in recs if r.get("status") == "ok"]
    failed = [r for r in recs if r.get("status") != "ok"]
    size = sum((PAGES / f"{r['key']}.txt").stat().st_size for r in ok if (PAGES / f"{r['key']}.txt").exists())
    print(f"{len(ok)} pages stored ({size / 1e6:.1f} MB), {len(failed)} unreadable by script")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "get"):
        p = sub.add_parser(name)
        p.add_argument("url")
        p.add_argument("--run", default="")
        p.add_argument("--max-age", type=float, default=DEFAULT_AGE)
        p.add_argument("--grep")
        p.add_argument("--context", type=int, default=1)
        p.add_argument("--range", dest="span")
    p = sub.add_parser("check")
    p.add_argument("run")
    p.add_argument("--ids")
    p.add_argument("--file")
    p.add_argument("--max-age", type=float, default=DEFAULT_AGE)
    p = sub.add_parser("search")
    p.add_argument("terms")
    p.add_argument("--limit", type=int, default=10)
    sub.add_parser("stats")
    args = ap.parse_args()

    if args.cmd in ("fetch", "get"):
        if args.cmd == "fetch":
            rec, text = fetch(args.url, args.run, args.max_age)
        else:
            rec, text = stored(args.url)
        if text is None:
            reason = (rec or {}).get("reason", "not in the library")
            print(f"UNREADABLE BY SCRIPT: {normal_url(args.url)} ({reason}). Use WebFetch.")
            return 2
        show(rec, text, args.grep, args.context, args.span)
        return 0
    if args.cmd == "check":
        return check(args.run, args.ids, args.file, args.max_age)
    if args.cmd == "search":
        return search(args.terms, args.limit)
    return stats()


if __name__ == "__main__":
    sys.exit(main())
