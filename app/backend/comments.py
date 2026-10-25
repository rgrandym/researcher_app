"""The author's comments on a run's master, anchored to its text, carried into every format.

Comments live beside the master in `<run>/.comments.json`, never in it: the master stays
what the gates, the agents and the edit absorption read. Each comment holds the exact
Markdown it covers (`quote`) and the text either side, so it is found again after the
document changes; a passage that can no longer be found is reported, never dropped.

At render time the comments become pandoc's own comment spans,

    <span class="comment-start" id="0" author="A" date="...">Comment text</span>covered
    text<span class="comment-end" id="0"></span>

(the HTML form of a span, because `[E1][Comment]{...}` would read as a reference link),

which pandoc writes as Word comments in a .docx. In HTML (and the PDF made from it)
`mark_html` turns them into highlighted passages with numbered notes.
"""

from __future__ import annotations

import bisect
import difflib
import html as htmllib
import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

from backend import appearance, workspace

FILE = ".comments.json"
# A highlight is a comment without words: a passage the author marked to come back to.
COLORS = ("yellow", "green", "blue", "pink")
MAX_TEXT = 4000
CONTEXT = 80

_FENCE = r"^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)[ \t]*$"
# Markdown that renders as no text the reader selects: figure specs and code fences, HTML
# comments and tags, link targets, attributes, evidence citations and cross-references.
_SKIP = re.compile(
    _FENCE
    + r"|<!--.*?-->"
    + r"|<[^>\n]+>"
    + r"|\]\([^)\n]*\)"
    + r"|\{[#.][^}\n]*\}"
    + r"|\[E\d+[^\]\n]{0,40}\]"
    + r"|\[\[[FT]\w+\]\]",
    re.S | re.M,
)
_TOKEN = re.compile(r"[^\W_]+")
_CODE = re.compile(r"`[^`\n]+`")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.M)
_START_SPAN = re.compile(r'<span class="comment-start" id="\d+"[^>]*>(?:\\.|[^<\\])*</span>')
_END_SPAN = re.compile(r'<span class="comment-end" id="\d+"></span>')
_ASCII_PUNCT = re.compile(r"([!-/:-@\[-`{-~])")


class AnchorError(ValueError):
    pass


# ------------------------------------------------------------------ storage


def _path(run: str) -> Path:
    return workspace.run_dir(run) / FILE


def _load(run: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(_path(run).read_text())
    except FileNotFoundError:
        return []
    items = data.get("comments") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("The saved comments are invalid")
    return [c for c in items if isinstance(c, dict) and isinstance(c.get("id"), str)]


def _save(run: str, items: list[dict[str, Any]]) -> None:
    path = _path(run)
    fd, temp = tempfile.mkstemp(prefix=f"{FILE}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"version": 1, "comments": items}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _master(run: str, doc: str) -> str:
    folder = workspace.run_dir(run)
    if doc not in workspace.run_meta(folder).get("masters", []):
        raise ValueError("Comments go on a master document")
    return workspace.run_file(run, doc).read_text()


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Write the comment first")
    text: str = value.strip()
    if len(text) > MAX_TEXT:
        raise ValueError(f"A comment holds at most {MAX_TEXT} characters")
    return text


def _author(value: Any) -> str:
    name = re.sub(r"[\"\\\x00-\x1f]", "", value if isinstance(value, str) else "").strip()
    return name[:80] or "Author"


# ------------------------------------------------------------------ finding text


def _projection(md: str) -> list[tuple[str, int, int]]:
    """The words a reader sees, lowercased, with their offsets in the Markdown."""
    tokens: list[tuple[str, int, int]] = []
    pos = 0
    for skip in _SKIP.finditer(md):
        for m in _TOKEN.finditer(md, pos, skip.start()):
            tokens.append((m.group(0).lower(), m.start(), m.end()))
        pos = skip.end()
    for m in _TOKEN.finditer(md, pos):
        tokens.append((m.group(0).lower(), m.start(), m.end()))
    return tokens


def _words(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def _exact(needle: list[str], hay: list[str], lo: int, hi: int) -> list[int]:
    n = len(needle)
    first = needle[0]
    return [i for i in range(lo, hi - n + 1) if hay[i] == first and hay[i : i + n] == needle]


def _fuzzy(needle: list[str], hay: list[str], lo: int, hi: int) -> tuple[int, int] | None:
    """The token range in hay[lo:hi] that best matches needle, allowing the differences a
    rendering introduces (citations as author and year, "Table 4" for a cross-reference)."""
    window = hay[lo:hi]
    if not window or not needle:
        return None
    longest = difflib.SequenceMatcher(None, needle, window, autojunk=False).find_longest_match(
        0, len(needle), 0, len(window)
    )
    if longest.size < min(3, len(needle)):
        return None
    start = max(0, longest.b - longest.a - 5)
    end = min(len(window), longest.b + longest.size + (len(needle) - longest.a - longest.size) + 5)
    blocks = [
        b
        for b in difflib.SequenceMatcher(
            None, needle, window[start:end], autojunk=False
        ).get_matching_blocks()
        if b.size
    ]
    matched = sum(b.size for b in blocks)
    if not blocks or matched < max(1, 0.6 * len(needle)):
        return None
    first, last = blocks[0], blocks[-1]
    return lo + start + first.b, lo + start + last.b + last.size


def _context_score(md: str, start: int, end: int, prefix: str, suffix: str) -> int:
    before = _words(md[max(0, start - 200) : start])[-8:]
    after = _words(md[end : end + 200])[:8]
    want_before, want_after = _words(prefix)[-8:], _words(suffix)[:8]
    score = 0
    for a, b in zip(reversed(before), reversed(want_before), strict=False):
        if a != b:
            break
        score += 1
    for a, b in zip(after, want_after, strict=False):
        if a != b:
            break
        score += 1
    return score


def _sections(md: str, proj: list[tuple[str, int, int]], heading: str) -> list[tuple[int, int]]:
    """Token ranges of the sections whose heading reads as `heading`."""
    want = _words(heading)
    if not want:
        return []
    heads = list(_HEADING.finditer(md))
    out = []
    starts = [t[1] for t in proj]
    for i, m in enumerate(heads):
        if _words(_SKIP.sub(" ", m.group(2))) != want:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(md)
        out.append((bisect.bisect_left(starts, m.start()), bisect.bisect_left(starts, end)))
    return out


def _out_of_code(md: str, start: int, end: int) -> tuple[int, int]:
    for m in _CODE.finditer(md):
        if m.start() < start < m.end():
            start = m.start()
        if m.start() < end < m.end():
            end = m.end()
    return start, end


def _find(
    md: str, words: list[str], prefix: str, suffix: str, heading: str = ""
) -> tuple[int, int] | None:
    """The Markdown range whose visible words read as `words`, nearest the given context."""
    if not words:
        return None
    proj = _projection(md)
    hay = [t[0] for t in proj]
    scopes = _sections(md, proj, heading) + [(0, len(hay))]

    def chars(i: int, j: int) -> tuple[int, int]:
        return _out_of_code(md, proj[i][1], proj[j - 1][2])

    for lo, hi in scopes:
        hits = _exact(words, hay, lo, hi)
        if hits:
            ranges = [chars(i, i + len(words)) for i in hits]
            return max(ranges, key=lambda r: _context_score(md, r[0], r[1], prefix, suffix))
    for lo, hi in scopes:
        found = _fuzzy(words, hay, lo, hi)
        if found:
            return chars(*found)
    return None


def _check_range(md: str, start: int, end: int) -> None:
    covered = md[start:end]
    if any(m.group("fence") for m in _SKIP.finditer(covered)):
        raise AnchorError(
            "Select text on one side of the figure, or click the figure to comment on it."
        )
    if "\n" in covered and any(line.lstrip().startswith("|") for line in covered.split("\n")):
        raise AnchorError(
            "Select text inside one table cell, or click the table to comment on all of it."
        )


def _figure_span(md: str, figure_id: str) -> tuple[int, int] | None:
    for m in appearance.FIGURE_BLOCK.finditer(md):
        try:
            spec = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(spec, dict) and spec.get("id") == figure_id:
            return m.start(), m.end()
    return None


def _table_span(md: str, table_id: str) -> tuple[int, int] | None:
    for m in appearance.TABLE_CAP.finditer(md):
        if m.group(2) == table_id:
            return m.start(1), m.end(1)
    return None


def _element_id(md: str, kind: str, number: int) -> str:
    """The id of the nth figure or table, numbered in document order as figures.py does."""
    if kind == "figure":
        ids = [
            spec["id"]
            for m in appearance.FIGURE_BLOCK.finditer(md)
            for spec in [_json(m.group(1))]
            if isinstance(spec, dict) and isinstance(spec.get("id"), str)
        ]
    else:
        ids = [m.group(2) for m in appearance.TABLE_CAP.finditer(md)]
    if not 1 <= number <= len(ids):
        raise AnchorError(
            f"This {kind} has no caption the document can be matched on. Select text inside it instead."
        )
    return str(ids[number - 1])


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def locate(md: str, comment: dict[str, Any]) -> tuple[int, int] | None:
    """Where a comment's passage is in `md` now, or None when it is gone."""
    kind, target = comment.get("kind"), str(comment.get("target") or "")
    if kind == "figure":
        return _figure_span(md, target)
    if kind == "table":
        return _table_span(md, target)
    quote = str(comment.get("quote") or "")
    if not quote:
        return None
    prefix, suffix = str(comment.get("prefix") or ""), str(comment.get("suffix") or "")
    hits = [m.start() for m in re.finditer(re.escape(quote), md)]
    if hits:
        start = max(hits, key=lambda s: _context_score(md, s, s + len(quote), prefix, suffix))
        return start, start + len(quote)
    return _find(md, _words(_SKIP.sub(" ", quote)), prefix, suffix)


# ------------------------------------------------------------------ the store's operations


def _anchored(md: str, start: int, end: int) -> dict[str, str]:
    return {
        "quote": md[start:end],
        "prefix": md[max(0, start - CONTEXT) : start],
        "suffix": md[end : end + CONTEXT],
    }


def _line(md: str, offset: int) -> int:
    return md.count("\n", 0, offset) + 1


def listing(run: str, doc: str) -> list[dict[str, Any]]:
    """The document's comments, each with where it is now. A passage found by its words
    after an edit is re-anchored to the new text, so the next look is exact."""
    md = _master(run, doc)
    items = _load(run)
    out, healed = [], False
    for c in items:
        if c.get("doc") != doc:
            continue
        span = locate(md, c)
        view = dict(c)
        if span:
            fresh = _anchored(md, *span)
            if c.get("kind") == "text" and fresh["quote"] != c.get("quote"):
                c.update(fresh)
                view.update(fresh)
                healed = True
            view.update(
                found=True,
                start=span[0],
                end=span[1],
                line=_line(md, span[0]),
                quote=fresh["quote"],
            )
        else:
            view.update(found=False, start=None, end=None, line=None)
        out.append(view)
    if healed:
        _save(run, items)
    out.sort(key=lambda c: (c["start"] is None, c["start"] or 0, c.get("created", "")))
    return out


def create(
    run: str,
    doc: str,
    text: Any,
    author: Any,
    selection: dict[str, Any] | None = None,
    element: dict[str, Any] | None = None,
    highlight: bool = False,
    color: Any = "yellow",
) -> dict[str, Any]:
    md = _master(run, doc)
    body = "" if highlight else _text(text)
    who = _author(author)
    if color not in COLORS:
        raise ValueError("Choose a listed highlight colour")
    if element:
        kind = element.get("kind")
        number, given = element.get("number"), element.get("id")
        if kind not in ("figure", "table"):
            raise AnchorError("Choose a figure or a table")
        if isinstance(given, str) and appearance.ITEM_ID.fullmatch(given):
            target = given
        elif isinstance(number, int):
            target = _element_id(md, kind, number)
        else:
            raise AnchorError("Choose a figure or a table")
        span = (_figure_span if kind == "figure" else _table_span)(md, target)
        if not span:
            raise AnchorError(f"Could not find this {kind} in the document")
        anchor = {"kind": kind, "target": target, **_anchored(md, *span)}
    elif selection:
        words = _words(str(selection.get("text") or ""))
        if not words:
            raise AnchorError("Select some text to comment on")
        span = _find(
            md,
            words,
            str(selection.get("prefix") or ""),
            str(selection.get("suffix") or ""),
            str(selection.get("heading") or ""),
        )
        if not span:
            raise AnchorError(
                "Could not find this passage in the saved document. Save your edits first, or select text within one paragraph."
            )
        _check_range(md, *span)
        anchor = {"kind": "text", "target": "", **_anchored(md, *span)}
    else:
        raise AnchorError("Select text, a figure or a table to comment on")
    comment = {
        "id": secrets.token_hex(6),
        "doc": doc,
        "type": "highlight" if highlight else "comment",
        "color": color,
        **anchor,
        "text": body,
        "author": who,
        "created": _now(),
        "updated": _now(),
        "resolved": False,
    }
    items = _load(run)
    items.append(comment)
    _save(run, items)
    return comment


def update(
    run: str, cid: str, text: Any = None, resolved: Any = None, color: Any = None
) -> dict[str, Any]:
    items = _load(run)
    for c in items:
        if c["id"] == cid:
            if text is not None:
                c["text"] = _text(text)
                c["type"] = "comment"  # a highlight given words becomes a comment
            if color is not None:
                if color not in COLORS:
                    raise ValueError("Choose a listed highlight colour")
                c["color"] = color
            if resolved is not None:
                if not isinstance(resolved, bool):
                    raise ValueError("Resolved is yes or no")
                c["resolved"] = resolved
            c["updated"] = _now()
            _save(run, items)
            return c
    raise FileNotFoundError(cid)


def delete(run: str, cid: str) -> None:
    items = _load(run)
    kept = [c for c in items if c["id"] != cid]
    if len(kept) == len(items):
        raise FileNotFoundError(cid)
    _save(run, kept)


def is_highlight(c: dict[str, Any]) -> bool:
    return c.get("type") == "highlight"


def open_for(
    run: str, doc: str, comments: bool = True, highlights: bool = False
) -> list[dict[str, Any]]:
    """What a render carries of this document's: open comments, and highlights when asked
    (the app's own views show them; exports leave them out)."""
    return [
        c
        for c in _load(run)
        if c.get("doc") == doc
        and not c.get("resolved")
        and (highlights if is_highlight(c) else comments)
    ]


def stamp(run: str) -> bytes:
    """What changes when any comment changes, for the preview cache."""
    try:
        return _path(run).read_bytes()
    except FileNotFoundError:
        return b""


# ------------------------------------------------------------------ into the formats


def _escape(text: str) -> str:
    return _ASCII_PUNCT.sub(r"\\\1", " ".join(text.split()))


def _heading_id(text: str) -> str:
    """pandoc's automatic identifier for a heading, so a comment in it keeps the anchor."""
    t = re.sub(r"\[\^[^\]]*\]|\]\([^)]*\)|\{[#.][^}]*\}", "", text)
    t = re.sub(r"[*`\[\]]", "", t).lower()
    t = "".join(ch for ch in t if ch.isalnum() or ch in "_-. ")
    t = t.replace(" ", "-")
    t = re.sub(r"^[^a-zÀ-￿]+", "", t)
    return t or "section"


def _rendered_figure(md: str, figure_id: str) -> tuple[int, int] | None:
    """Inside the caption of the image figures.py made for a figure."""
    pattern = re.compile(
        r"!\[((?:(?!!\[).)*?)\]\(([^)\s]*?\b" + re.escape(figure_id) + r"\.(?:png|svg))\)", re.S
    )
    m = pattern.search(md)
    return (m.start(1), m.end(1)) if m else None


def inject(md: str, items: list[dict[str, Any]]) -> tuple[str, dict[str, dict[str, Any]]]:
    """`md` with each comment as pandoc comment spans; the comments by the numeric id
    each got (Word needs numbers). Comments whose passage is gone are left out."""
    inserts: list[tuple[int, int, str]] = []
    placed: dict[str, dict[str, Any]] = {}
    lines_done: set[int] = set()
    for c in items:
        if c.get("kind") == "figure":
            span = _rendered_figure(md, str(c.get("target")))
        else:
            # A rendered table caption has lost its {#T…}: find it by its words.
            span = locate(md, {**c, "kind": "text"})
        if not span:
            continue
        start, end = span
        if is_highlight(c):
            h = f"h{len(placed)}"
            placed[h] = c
            inserts.append((start, 0, f'<span class="hl-start" id="{h}"></span>'))
            inserts.append((end, 1, f'<span class="hl-end" id="{h}"></span>'))
            continue
        n = str(sum(1 for k in placed if not k.startswith("h")))
        placed[n] = c
        author = _author(c.get("author"))
        date = re.sub(r"[^0-9TZ:\-]", "", str(c.get("created") or _now()))
        inserts.append(
            (
                start,
                0,
                f'<span class="comment-start" id="{n}" author="{author}" date="{date}">{_escape(str(c.get("text") or ""))}</span>',
            )
        )
        inserts.append((end, 1, f'<span class="comment-end" id="{n}"></span>'))
        line_start = md.rfind("\n", 0, start) + 1
        line_end = md.find("\n", start)
        line_end = len(md) if line_end < 0 else line_end
        heading = _HEADING.match(md, line_start, line_end)
        if heading and line_start not in lines_done and "{#" not in heading.group(2):
            lines_done.add(line_start)
            inserts.append((line_end, 2, f" {{#{_heading_id(heading.group(2))}}}"))
    out = md
    for pos, _, text in sorted(inserts, key=lambda x: (x[0], x[1]), reverse=True):
        out = out[:pos] + text + out[pos:]
    return out, placed


def strip(md: str) -> str:
    """A rendered copy without the comment spans, for the export loss check."""
    return _END_SPAN.sub("", _START_SPAN.sub("", md))


_SPAN_START = re.compile(r'<span\b[^>]*\bclass="comment-start"[^>]*>', re.S)
_SPAN_END = re.compile(r'<span\b[^>]*\bclass="comment-end"[^>]*>', re.S)
_ID = re.compile(r'\bid="(\d+)"')
_HL = re.compile(r'<span\b[^>]*\bclass="hl-(start|end)"[^>]*>', re.S)
_HL_ID = re.compile(r'\bid="(h\d+)"')
_NO_MARK = ("style", "script", "svg", "title", "head", "textarea")


def _plain(text: str) -> str:
    return " ".join(text.split())


def mark_html(html: str, placed: dict[str, dict[str, Any]]) -> str:
    """Turn pandoc's comment spans into highlights: each passage in <mark>s, a numbered
    marker after it, and the note itself (hidden on screen, a footnote in print)."""
    if not placed:
        return html

    # The table of contents repeats the headings: there a comment is simply removed.
    def toc(m: re.Match[str]) -> str:
        block = re.sub(
            r'<span\b[^>]*class="comment-start"[^>]*>.*?</span>', "", m.group(0), flags=re.S
        )
        return re.sub(r'<span\b[^>]*class="comment-end"[^>]*>\s*</span>', "", block, flags=re.S)

    html = re.sub(r'<nav id="TOC".*?</nav>', toc, html, count=1, flags=re.S)
    # An image's alt text is its caption flattened, comment and all.
    for c in (c for c in placed.values() if not is_highlight(c)):
        flat = htmllib.escape(_plain(str(c.get("text") or "")), quote=True)
        if flat:
            html = re.sub(r'(alt="[^"]*?)' + re.escape(flat), r"\1", html)
    head, sep, body = html.partition("<body")
    if not sep:
        head, body = "", html
    parts = re.split(r"(<[^>]+>)", body)
    out: list[str] = []
    open_ids: list[str] = []
    open_hl: list[str] = []
    skip: list[str] = []
    number = 0
    numbers: dict[str, int] = {}
    i = 0
    while i < len(parts):
        part = parts[i]
        if part.startswith("<"):
            hl = _HL.fullmatch(part)
            if hl:
                m = _HL_ID.search(part)
                if m and m.group(1) in placed:
                    if hl.group(1) == "start":
                        open_hl.append(m.group(1))
                    elif m.group(1) in open_hl:
                        open_hl.remove(m.group(1))
                j = i + 1
                while j < len(parts) and parts[j] != "</span>":
                    j += 1
                i = j + 1
                continue
            if _SPAN_START.fullmatch(part):
                m = _ID.search(part)
                j = i + 1
                while j < len(parts) and parts[j] != "</span>":
                    j += 1
                if m and m.group(1) in placed:
                    number += 1
                    numbers[m.group(1)] = number
                    open_ids.append(m.group(1))
                i = j + 1
                continue
            if _SPAN_END.fullmatch(part):
                m = _ID.search(part)
                j = i + 1
                while j < len(parts) and parts[j] != "</span>":
                    j += 1
                if m and m.group(1) in open_ids:
                    n = m.group(1)
                    open_ids.remove(n)
                    c = placed[n]
                    cid = htmllib.escape(str(c["id"]), quote=True)
                    who = htmllib.escape(_author(c.get("author")))
                    text = htmllib.escape(_plain(str(c.get("text") or "")))
                    out.append(
                        f'<sup class="cmt-ref" data-c="{cid}" title="{who}: {text}">{numbers.get(n, "")}</sup>'
                        f'<span class="cmt-note" data-c="{cid}"><span class="cmt-who">{who}:</span> {text}</span>'
                    )
                i = j + 1
                continue
            tag = re.match(r"<(/?)([a-zA-Z0-9]+)", part)
            if tag and tag.group(2).lower() in _NO_MARK and not part.endswith("/>"):
                if tag.group(1):
                    if skip and skip[-1] == tag.group(2).lower():
                        skip.pop()
                else:
                    skip.append(tag.group(2).lower())
            out.append(part)
        elif (open_ids or open_hl) and not skip and part.strip():
            ids = " ".join(
                htmllib.escape(str(placed[n]["id"]), quote=True) for n in open_ids + open_hl
            )
            kinds = ["cmt"] if open_ids else []
            if open_hl:
                kinds.append(f"hl hl-{placed[open_hl[-1]].get('color', 'yellow')}")
            out.append(f'<mark class="{" ".join(kinds)}" data-c="{ids}">{part}</mark>')
        else:
            out.append(part)
        i += 1
    return head + sep + "".join(out)


CSS = """
/* Comments */
mark.cmt { background: #FFF0A3; color: inherit; border-radius: 2px; padding: 0 0.05em; }
mark.cmt { border-bottom: 1.5px dotted #B7791F; }
mark.hl { color: inherit; border-radius: 2px; padding: 0 0.05em; }
mark.hl-yellow { background: #FFF3A0; }
mark.hl-green { background: #C9F2C3; }
mark.hl-blue { background: #CFE5FF; }
mark.hl-pink { background: #FFD4E8; }
mark.cmt.cmt-active { background: #FFD43B; box-shadow: 0 0 0 2px #FFD43B; }
mark.hl.cmt-active { box-shadow: 0 0 0 2px #F0B400; }
sup.cmt-ref { font-size: 0.66em; font-weight: 700; color: #9A6700; margin-left: 0.1em; cursor: help; }
.cmt-note { display: none; }
@media print {
  sup.cmt-ref { display: none; }
  .cmt-note { display: block; float: footnote; font-size: 8pt; line-height: 1.35; color: #5C4600; }
  .cmt-note .cmt-who { font-weight: 700; }
}
"""
