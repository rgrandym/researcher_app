#!/usr/bin/env python3
"""Section-level containment guard for a report.

Guarantees mechanically that work on one part of a document left every other
part byte-identical. Prose instructions cannot guarantee this; a hash can.

    section_guard.py snapshot <report.md>                 # record the current state
    section_guard.py check    <report.md> [--allow PAT]…  # nothing else may have moved
    section_guard.py sections <report.md>                 # list section keys + hashes

PAT is matched case-insensitively as a substring of the heading, so `--allow 3.3`
or `--allow "Switching cost"` both select the same section. Repeat for several.

check exits 1 if any section outside --allow changed, was added, or was removed.

The baseline lives beside the report as `.guard-<name>.json` and is rewritten
only by `snapshot`, never by `check`.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblio  # noqa: E402

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
PREAMBLE = "__preamble__"

# Sections that are rebuilt from the document rather than written into it. A
# citation removed in one section MUST change the Sources list; a closed data
# hole MUST change "Data still to obtain". Treating those as containment
# failures would train the reader to ignore the check.
DERIVED = biblio.DERIVED


def baseline_path(report):
    return report.parent / f".guard-{report.stem}.json"


def split_sections(text):
    """Ordered {heading: body}. Body excludes the heading line itself.

    Fenced code blocks are opaque: a `#` inside one is a comment, not a heading.
    """
    sections, key, buf, fence = {}, PREAMBLE, [], None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
        elif stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
        elif (m := HEADING.match(line)):
            sections[key] = "".join(buf)
            key, buf = f"{m.group(1)} {m.group(2)}", []
            continue
        buf.append(line)
    sections[key] = "".join(buf)
    return sections


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def snapshot_of(text):
    return {k: digest(v) for k, v in split_sections(text).items()}


def allowed(key, patterns):
    return any(p.lower() in key.lower() for p in patterns)


def label(key):
    return "(document preamble)" if key == PREAMBLE else key


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", choices=("snapshot", "check", "sections"))
    ap.add_argument("report", type=Path)
    ap.add_argument("--allow", action="append", default=[],
                    help="heading substring that is permitted to change")
    ap.add_argument("-b", "--baseline", type=Path)
    a = ap.parse_args()

    if not a.report.exists():
        sys.exit(f"no such file: {a.report}")
    text = a.report.read_text()
    base_file = a.baseline or baseline_path(a.report)

    if a.cmd == "sections":
        for k, v in split_sections(text).items():
            print(f"{digest(v)}  {len(v.splitlines()):4d} lines  {label(k)}")
        return

    if a.cmd == "snapshot":
        base_file.write_text(json.dumps(snapshot_of(text), indent=1))
        print(f"snapshot: {len(snapshot_of(text))} sections → {base_file}")
        return

    if not base_file.exists():
        sys.exit(f"no baseline at {base_file} — run `section_guard.py snapshot {a.report}` "
                 f"before editing, or there is nothing to compare against")
    old = json.loads(base_file.read_text())
    now = split_sections(text)
    new = {k: digest(v) for k, v in now.items()}

    drift, ok_changed, derived = [], [], []

    def bucket(kind, k):
        if k.strip().lower() in DERIVED:
            derived.append((kind, k))
        elif allowed(k, a.allow):
            ok_changed.append((kind, k))
        else:
            drift.append((kind, k))

    for k in new:
        if k not in old:
            bucket("ADDED", k)
        elif new[k] != old[k]:
            bucket("CHANGED", k)
    for k in old:
        if k not in new:
            bucket("REMOVED", k)

    unchanged = len(new) - len({k for _, k in drift + ok_changed + derived})
    for kind, k in sorted(ok_changed):
        print(f"ALLOWED  {kind:8} {label(k)}")
    for kind, k in sorted(derived):
        print(f"DERIVED  {kind:8} {label(k)}  (rebuilt, not authored — verify with audit_citations.py)")
    for kind, k in sorted(drift):
        print(f"DRIFT    {kind:8} {label(k)}")

    print(f"\n{unchanged} section(s) untouched · {len(ok_changed)} changed within scope · "
          f"{len(derived)} derived · {len(drift)} out-of-scope change(s)")
    if drift:
        print("\nOut-of-scope edits are a containment failure. Restore those sections to the\n"
              "baseline text, or if the change was genuinely required, say so explicitly and\n"
              "re-run with the section added to --allow.")
    sys.exit(1 if drift else 0)


if __name__ == "__main__":
    main()
