"""Find passages and sources changed since the last independent verification.

The snapshot is only a scope aid. A missing or unreadable snapshot requires a full
verification; it never turns a changed claim into a supported one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

EVIDENCE = re.compile(r"\[E\d+\]")
HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)
VERSION = 2


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def paragraphs(text: str) -> list[dict[str, str | list[str]]]:
    out = []
    heading = ""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        matches = list(HEADING.finditer(block))
        if matches:
            heading = matches[-1].group(1)
        refs = sorted(set(EVIDENCE.findall(block)))
        # Include uncited passages too. An edit can introduce a new assertion before
        # the citation audit has had a chance to flag it.
        out.append({"hash": digest(block), "heading": heading, "text": block, "refs": refs})
    return out


def source_hashes(run: Path) -> dict[str, str]:
    result = {}
    for number, line in enumerate((run / "evidence.jsonl").read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"invalid evidence row {number}") from exc
        if not isinstance(row, dict) or not re.fullmatch(r"E\d+", str(row.get("id") or "")):
            raise ValueError(f"invalid evidence ID on row {number}")
        ref = f"[{row['id']}]"
        if ref in result:
            raise ValueError(f"duplicate evidence ID {ref}")
        result[ref] = digest(json.dumps(row, sort_keys=True, ensure_ascii=False))
    return result


def snapshot(run: Path, document: Path) -> dict:
    return {"version": VERSION, "document": document.name,
            "paragraphs": paragraphs(document.read_text()),
            "sources": source_hashes(run)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "diff"))
    parser.add_argument("run", type=Path)
    parser.add_argument("document", nargs="?", default="report.md")
    args = parser.parse_args()
    path = args.run / ".verification-snapshot.json"
    document = args.run / args.document
    try:
        current = snapshot(args.run, document)
    except (OSError, ValueError) as exc:
        print(f"FULL VERIFY: cannot fingerprint current document or evidence ({exc})")
        if args.action == "snapshot":
            raise SystemExit(1) from exc
        return
    if args.action == "snapshot":
        compact = {**current, "paragraphs": [
            {key: value for key, value in row.items() if key != "text"}
            for row in current["paragraphs"]
        ]}
        path.write_text(json.dumps(compact, indent=2) + "\n")
        print(f"Recorded {len(current['paragraphs'])} passages from {document.name}")
        return
    try:
        before = json.loads(path.read_text())
        if (before.get("version") != VERSION or not isinstance(before.get("paragraphs"), list)
                or not isinstance(before.get("sources"), dict)):
            raise ValueError("invalid snapshot")
    except (OSError, ValueError):
        print("FULL VERIFY: no valid prior snapshot")
        return
    old = {row["hash"] for row in before["paragraphs"]}
    new = {row["hash"] for row in current["paragraphs"]}
    changed_sources = {ref for ref in current["sources"].keys() | before["sources"].keys()
                       if before["sources"].get(ref) != current["sources"].get(ref)}
    changed = [row for row in current["paragraphs"]
               if row["hash"] not in old or changed_sources.intersection(row["refs"])]
    removed = [row for row in before["paragraphs"] if row["hash"] not in new]
    lines = [f"Changed passages: {len(changed)}; removed passages: {len(removed)}; changed sources: {len(changed_sources)}"]
    for row in changed:
        lines.append(f"\n## {row['heading']} {' '.join(row['refs'])}\n{row['text']}")
    if removed:
        lines.append("\nRemoved passages or replaced claims need a downstream conclusion check:")
        for row in removed:
            lines.append(f"- {row['heading']}: {' '.join(row['refs'])}")
    scope_path = args.run / ".verification-scope.md"
    scope_path.write_text("\n".join(lines) + "\n")
    print(lines[0])
    print(f"Scope: {scope_path}")


if __name__ == "__main__":
    main()
