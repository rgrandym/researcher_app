#!/usr/bin/env python3
"""Verify that an export lost nothing.

Conversion drops content silently and the damaged file looks fine — a clipped
table does not warn, and a renderer that swallows a figure still produces a
document that reads as complete. The only reliable detector is counting what
came out against what went in.

    python3 .claude/scripts/check_export.py source.md out.pdf out.docx out.html

Compares, for each artifact: the *set* of [E#] evidence IDs, the number of
exhibits, the number of [NEEDS DATA] placeholders, and the word count. Exits 1
if any artifact is missing something the source had. The word count is what
catches a clipped page in a document that cites nothing, such as a CV or a
letter, where every other comparison passes vacuously at zero.

Counts are compared as sets, not totals. Pandoc writes an image's caption twice
(alt text and visible caption), so raw totals legitimately differ between
formats while the set of cited IDs must not.
"""

import html as _html
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

CITE = re.compile(r"\[E\d+\]")
EXHIBIT = re.compile(r"(?:Figure|Table|Exhibit)\s+\d+")
# pandoc hard-wraps its HTML output, so the space inside the marker can
# arrive as a newline. A checker that reports present content as missing
# trains people to ignore it, which is the one failure it cannot afford.
NEEDS = re.compile(r"\[NEEDS\s+DATA")


WORD = re.compile(r"[A-Za-z][A-Za-z\'-]{2,}")
_STYLE = re.compile(r"<(style|script)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def words_of(t, path=None):
    """Word count of the prose, for detecting a renderer that dropped text.

    A piece with no citations and no exhibits passes every set comparison in
    this script vacuously, so a letter or a CV whose second page was clipped
    would report OK. Counting words is the check that still bites there.
    Markdown syntax is not counted, so the source and the rendered output are
    comparable to within a few per cent. Markup is stripped first: an HTML file
    carries its whole stylesheet as text and a .docx carries its XML, and
    counting those would report a document as larger the more of it was lost.
    """
    ext = Path(path).suffix.lower() if path else ""
    # Comments never render: a revised document's <!-- why: ... --> notes would otherwise
    # count as text its export had lost.
    t = _COMMENT.sub(" ", t)
    if ext in (".html", ".htm", ".docx", ".pptx", ".xlsx"):
        t = _TAG.sub(" ", _STYLE.sub(" ", t))
    return len(WORD.findall(t))


def text_of(path):
    """Extract searchable text from whatever format this is."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".html", ".htm"):
        # pandoc escapes & as &amp;, so "R&D Systems" stops matching a
        # citation string unless entities are resolved first.
        return _html.unescape(p.read_text(encoding="utf-8", errors="replace"))
    if ext in (".md", ".txt", ".css"):
        return p.read_text(encoding="utf-8", errors="replace")
    if ext == ".pdf":
        # Both modes, concatenated. -layout preserves columns but wraps long
        # cell text; the default mode reflows but interleaves columns. A string
        # invisible to one is usually visible to the other, and a loss check
        # that reports present content as missing trains people to ignore it.
        r = subprocess.run(["pdftotext", "-layout", str(p), "-"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"pdftotext failed on {p}: {r.stderr.strip()}")
        return r.stdout
    if ext in (".docx", ".pptx", ".xlsx"):
        with zipfile.ZipFile(p) as z:
            parts = [n for n in z.namelist()
                     if re.match(r"(word/document|ppt/slides/slide\d+|xl/sharedStrings)", n)
                     and n.endswith(".xml")]
            return "\n".join(z.read(n).decode("utf-8", "replace") for n in parts)
    sys.exit(f"don't know how to read {p}")


_WS = re.compile(r"\s+")
_PUNCT = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
                        "\u2013": "-", "\u2014": "-", "\u00a0": " "})


def _flatten(s):
    """Whitespace- and punctuation-insensitive form, for substring matching
    across renderers that re-wrap lines and substitute dashes and quotes."""
    return _WS.sub(" ", s.translate(_PUNCT)).strip()


def match_text(path):
    """Text used for finding citation strings. For a PDF this is both
    extraction modes concatenated: -layout preserves columns but wraps long
    cell text, the default reflows but interleaves them, and a string invisible
    to one is usually visible to the other. Counting (exhibits, placeholders)
    still uses the single canonical extraction, so the reported totals are not
    doubled by this.
    """
    if Path(path).suffix.lower() != ".pdf":
        return text_of(path)
    outs = []
    for mode in (["-layout"], []):
        r = subprocess.run(["pdftotext", *mode, str(path), "-"],
                           capture_output=True, text=True)
        outs.append(r.stdout if r.returncode == 0 else "")
    return "\n".join(outs)


def profile(path, citemap=None):
    """What this artifact contains, in the terms a loss check needs.

    With --citemap the source no longer carries [E#] markers: references.py has
    already rendered them as author-date parentheticals. Counting [E#] would
    then compare empty set against empty set and pass regardless of what was
    lost, so the check switches to the rendered citation strings instead.
    """
    t = text_of(path)
    if citemap:
        haystack = match_text(path)
        # A rendered citation is several words long, and pdftotext wraps lines
        # while pandoc re-flows them. Comparing raw substrings therefore reports
        # citations as lost that are present and merely broken across a line.
        # Collapse whitespace and normalise the punctuation renderers rewrite,
        # then compare.
        flat = _flatten(haystack)
        present, loose = set(), set()
        for eid, cite in citemap.items():
            needle = _flatten(cite)
            if needle in flat:
                present.add(eid)
                continue
            # Inside a narrow table cell a citation is hyphenated and wrapped,
            # so no contiguous form of it survives extraction. Fall back to
            # requiring every significant token, and report how many needed it.
            toks = [w for w in re.split(r"[\s,]+", needle) if len(w) > 3]
            if toks and all(w in flat for w in toks):
                present.add(eid)
                loose.add(eid)
        return {
            "ids": present,
            "loose": loose,
            "exhibits": len(set(EXHIBIT.findall(t))),
            "placeholders": len(NEEDS.findall(t)),
            "words": words_of(t, path),
        }
        return {
            "ids": present,
            "exhibits": len(set(EXHIBIT.findall(t))),
            "placeholders": len(NEEDS.findall(t)),
        }
    return {
        "ids": set(CITE.findall(t)),
        "loose": set(),
        "exhibits": len(set(EXHIBIT.findall(t))),
        "placeholders": len(NEEDS.findall(t)),
        "words": words_of(t, path),
    }


def main():
    args = sys.argv[1:]
    citemap = None
    if "--citemap" in args:
        i = args.index("--citemap")
        citemap = json.loads(Path(args[i + 1]).read_text(encoding="utf-8"))
        del args[i:i + 2]
    if len(args) < 2:
        sys.exit(__doc__)
    src_path, *outs = args
    src = profile(src_path, citemap)
    unit = "rendered citations" if citemap else "evidence IDs"
    print(f"source {Path(src_path).name}: {len(src['ids'])} {unit} · "
          f"{src['exhibits']} exhibits · {src['placeholders']} placeholders · "
          f"{src['words']} words")

    bad = False
    for out in outs:
        got = profile(out, citemap)
        lost = src["ids"] - got["ids"]
        extra = got["ids"] - src["ids"]
        flags = []
        if lost:
            flags.append(f"LOST {len(lost)}: {', '.join(sorted(lost)[:8])}")
        if extra:
            flags.append(f"UNKNOWN {', '.join(sorted(extra)[:8])}")
        if got["exhibits"] < src["exhibits"]:
            flags.append(f"exhibits {got['exhibits']} < {src['exhibits']}")
        if got["placeholders"] < src["placeholders"]:
            flags.append(f"placeholders {got['placeholders']} < {src['placeholders']}")
        # Text loss with nothing countable to lose: the only signal a piece
        # carrying no citations and no exhibits gives when a page is clipped.
        if src["words"] and got["words"] < src["words"] * 0.9:
            flags.append(f"words {got['words']} < {src['words']} "
                         f"({got['words'] / src['words']:.0%} survived)")
        # a raster figure hides its own text, so only the caption is countable
        status = "OK  " if not flags else "FAIL"
        bad |= bool(flags)
        note = f" ({len(got['loose'])} matched token-wise, wrapped in tables)" if got.get("loose") else ""
        print(f"{status} {Path(out).name}: {len(got['ids'])} IDs{note} · "
              f"{got['exhibits']} exhibits · {got['placeholders']} placeholders · "
              f"{got['words']} words"
              + (f"  ← {'; '.join(flags)}" if flags else ""))

    if bad:
        print("\nContent was lost. Change the renderer, not the report.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
