#!/usr/bin/env python3
"""section_map.py — read a report by section instead of whole.

    section_map.py <run|report.md>                     # the map: one line per section
    section_map.py <run|report.md> --show PAT [--show PAT]…   # those sections, numbered
    section_map.py <run|report.md> --find E42|"text"   # which sections hold it

The map gives each section's line range, word count, figure blocks and the evidence
IDs it cites, so a round or a single command can decide what to read from a few
hundred tokens instead of the whole document. A 30,000-word report costs about
40,000 tokens to read; its map costs a few hundred.

PAT matches as in section_guard.py: a case-insensitive substring of the heading, so
`--show 3.3` or `--show "Switching cost"` both work. Given a run folder, the master
document comes from `.run.json` through runmeta.py.

It reads and prints; it never writes.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runmeta                                            # noqa: E402
from section_guard import DERIVED, PREAMBLE, split_sections  # noqa: E402

EVIDENCE = re.compile(r"\[(E\d+(?:\s*[,;]\s*E\d+)*)\]")
EID = re.compile(r"E(\d+)")


def master(target):
    path = Path(target)
    if path.is_dir():
        primary = runmeta.primary(path)
        if primary is None:
            sys.exit(f"{path}: no master document yet")
        return primary
    return path


def ids_in(text):
    found = set()
    for group in EVIDENCE.findall(text):
        found.update(int(n) for n in EID.findall(group))
    return sorted(found)


def ranges(nums):
    """[3,4,5,9] -> 'E3–E5, E9'."""
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"E{start}" if start == prev else f"E{start}–E{prev}")
            start = prev = n
    if start is not None:
        out.append(f"E{start}" if start == prev else f"E{start}–E{prev}")
    return ", ".join(out)


def sections(text):
    """[(key, first_line, last_line, body)], line numbers 1-based and inclusive of the
    heading line."""
    out, line = [], 1
    for key, body in split_sections(text).items():
        head = 0 if key == PREAMBLE else 1
        n = head + body.count("\n")
        if key == PREAMBLE and not body.strip():
            continue
        out.append((key, line, line + max(n, 1) - 1, body))
        line += n
    return out


def matches(key, patterns):
    k = key.lower()
    return any(p.lower() in k for p in patterns)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    ap.add_argument("target", help="run folder or report file")
    ap.add_argument("--show", action="append", default=[], metavar="PAT")
    ap.add_argument("--find", metavar="E42|text")
    args = ap.parse_args()

    path = master(args.target)
    text = path.read_text()
    secs = sections(text)
    lines = text.splitlines()

    if args.show:
        hits = [s for s in secs if s[0] != PREAMBLE and matches(s[0], args.show)]
        if not hits:
            print(f"no section matches {args.show}", file=sys.stderr)
            return 1
        for key, first, last, _ in hits:
            print(f"--- {path.name}:{first}-{last}")
            for i in range(first, last + 1):
                print(f"{i:5}  {lines[i - 1] if i <= len(lines) else ''}")
        return 0

    if args.find:
        needle = args.find
        exact = re.compile(rf"\b{re.escape(needle)}\b") if EID.fullmatch(needle) else None
        found = 0
        for key, first, last, body in secs:
            hay = (key + "\n" + body)
            if (exact.search(hay) if exact else needle.lower() in hay.lower()):
                print(f"{first:5}-{last:<5} {key}")
                found += 1
        return 0 if found else 1

    print(f"{path}  ·  {len(text.split())} words  ·  {len(lines)} lines")
    for key, first, last, body in secs:
        words = len(body.split())
        figs = body.count("```figure")
        derived = any(d.lower() in key.lower() for d in DERIVED)
        cited = "" if derived else ranges(ids_in(body))
        extra = f"  ·  {figs} figure{'s' * (figs != 1)}" if figs else ""
        print(f"{first:5}-{last:<5} {words:>5}w  {key}{extra}")
        if cited:
            print(f"{'':19}{cited}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
