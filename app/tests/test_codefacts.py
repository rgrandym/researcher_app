"""The project's record of what is known about a codebase: verified facts, ranges read,
searches run. Nothing is read or searched twice at the same version, and nothing
unverified gets in."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT = "outputs/2026-11-07-docs-audit"
CODE = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    if a is None:\n        raise ValueError('a')\n    return a - b\n" + "\n" * 20


def _sh(root: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(root / ".claude/scripts" / script), *args],
                          cwd=root, capture_output=True, text=True)


def _doc_run(root: Path, slug: str = "widget") -> Path:
    (root / "src").mkdir(exist_ok=True)
    if not (root / "src/widget.py").exists():
        (root / "src/widget.py").write_text(CODE)
    (root / PROJECT).mkdir(parents=True, exist_ok=True)
    out = _sh(root, "codedoc.py", "start", slug, "--target", f"docs/{slug.upper()}.md",
              "--anchor", "src/widget.py",
              "--scope", "src/widget.py", "--prompt", "/code-doc", "--project", PROJECT)
    assert out.returncode == 0, out.stderr
    # `start` prints the run and the master last, after the anchor and the inventory.
    return root / [l.strip() for l in out.stdout.splitlines() if l.strip()][-2]


def _facts(path: Path, *items: dict) -> Path:
    path.write_text("".join(json.dumps(i) + "\n" for i in items))
    return path


def test_a_fact_is_recorded_only_if_its_quote_is_at_its_lines(root: Path) -> None:
    run = _doc_run(root)
    good = {"file": "src/widget.py", "lines": "6-7", "claim": "sub rejects None",
            "quote": "if a is None:\n        raise ValueError('a')"}
    invented = {"file": "src/widget.py", "lines": "1-2", "claim": "add validates", "quote": "isinstance(a, int)"}
    wrong_lines = {"file": "src/widget.py", "lines": "1-2", "claim": "sub subtracts", "quote": "return a - b"}
    out = _sh(root, "codefacts.py", "add", str(run), str(_facts(run / "notes/f.jsonl", good, invented, wrong_lines)),
              "--by", "reader:widget")
    assert out.returncode == 1
    assert "recorded 1 fact(s), rejected 2" in out.stdout
    assert "quote not found" in out.stdout and "quote is at src/widget.py:8-8, not 1-2" in out.stdout
    store = (root / PROJECT / "code-docs/.facts.jsonl").read_text()
    assert "sub rejects None" in store and "add validates" not in store


def test_reads_are_shared_and_unread_ranges_shrink(root: Path) -> None:
    first = _doc_run(root, "widget")
    assert "src/widget.py: 1-28" in _sh(root, "codefacts.py", "unread", str(first), "src/widget.py").stdout
    _sh(root, "codefacts.py", "read", str(first), "src/widget.py", "1-8", "--by", "reader:a")
    second = _doc_run(root, "other")
    out = _sh(root, "codefacts.py", "unread", str(second), "src/widget.py").stdout
    assert "src/widget.py: 9-28" in out


def test_a_code_change_moves_or_stales_facts(root: Path) -> None:
    run = _doc_run(root)
    _sh(root, "codefacts.py", "add", str(run), str(_facts(run / "notes/f.jsonl",
        {"file": "src/widget.py", "lines": "8", "claim": "sub subtracts", "quote": "return a - b"},
        {"file": "src/widget.py", "lines": "2", "claim": "add adds", "quote": "return a + b"})), "--by", "r")
    (root / "src/widget.py").write_text("# header\n# header\n" + CODE.replace("return a + b", "return sum((a, b))"))
    out = _sh(root, "codefacts.py", "known", str(run), "src/widget.py").stdout
    assert "`src/widget.py:10-10` [MOVED] sub subtracts" in out
    assert "[STALE] add adds" in out
    assert "read 0%" in out or "read 3%" in out


def test_earlier_code_documents_are_offered_as_leads(root: Path) -> None:
    first = _doc_run(root, "widget")
    (first / "widget.md").write_text("# W\n\n## 1. Overview\n\nThe sub function rejects None `src/widget.py:5-8`.\n")
    _sh(root, "codedoc.py", "stamp", str(first))
    second = _doc_run(root, "other")
    out = _sh(root, "codefacts.py", "known", str(second), "src/widget.py").stdout
    assert "Already described in 1 other code document(s)" in out
    assert "widget.md L5: The sub function rejects None" in out
    # 1-4 is shorter than a gap worth reading again, so only 9-28 is left
    assert "src/widget.py: 9-28" in _sh(root, "codefacts.py", "unread", str(second), "src/widget.py").stdout


def test_a_search_is_answered_from_the_record_until_the_code_changes(root: Path) -> None:
    run = _doc_run(root)
    first = _sh(root, "codefacts.py", "search", str(run), "def sub", "src").stdout
    assert "src/widget.py:5:def sub(a, b):" in first and "from the record" not in first
    assert "from the record" in _sh(root, "codefacts.py", "search", str(run), "def sub", "src").stdout
    (root / "src/widget.py").write_text("\n" + CODE)
    again = _sh(root, "codefacts.py", "search", str(run), "def sub", "src").stdout
    assert "src/widget.py:6:def sub" in again and "from the record" not in again


def test_project_evidence_about_the_code_is_imported_once_and_verified(root: Path) -> None:
    run = _doc_run(root)
    code = root / "src/widget.py"
    rows = [
        {"id": "E1", "claim": "sub raises on None", "quote": "raise ValueError('a')", "url": f"file://{code}#L7"},
        {"id": "E2", "claim": "moved since", "quote": "return a - b", "url": f"file://{code}#L3"},
        {"id": "E3", "claim": "gone", "quote": "def multiply(a, b):", "url": f"file://{code}#L9"},
        {"id": "E4", "claim": "a web source", "quote": "anything", "url": "https://example.org"},
    ]
    (root / PROJECT / "evidence.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = _sh(root, "codefacts.py", "import", str(run)).stdout
    assert "imported 2 fact(s)" in out and "1 no longer match the code" in out
    assert "imported 0 fact(s)" in _sh(root, "codefacts.py", "import", str(run)).stdout
    known = _sh(root, "codefacts.py", "known", str(run), "src/widget.py").stdout
    assert "`src/widget.py:8-8` moved since" in known and "`src/widget.py:7-7` sub raises on None" in known


def test_run_card_orients_in_one_call(root: Path) -> None:
    from conftest import RUN

    out = _sh(root, "run_card.py", f"outputs/{RUN}")
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith(f"# {RUN}")
    assert "Author edits:" in out.stdout and "Stages missing:" in out.stdout
    assert len(out.stdout.splitlines()) < 120
