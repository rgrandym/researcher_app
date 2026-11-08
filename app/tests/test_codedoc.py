"""/code-doc: a code document cites the code, says when the code moved, and is updated in
place rather than written beside itself."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DOC = """# The widget module

Commit abc1234, 2026-11-08.

## 1. Overview and responsibilities

The module adds two numbers and returns the sum `src/widget.py:1-2`.

## 2. Architecture and system interactions

```text
caller --> add() --> int
```

The caller passes two integers to `add` `src/widget.py:1`.

## 3. Complete technical and reproduction specification

### Detailed architecture

`add(a, b)` returns `a + b` `src/widget.py:2`.

### Tech stack and dependencies

| Library | Version |
|---|---|
| none | [Not defined in codebase] |

### Reproduction guide

1. Import the function from `src/widget.py:1` and call it with two integers.

## 4. Code health, gaps and improvements

- **Low** `src/widget.py:2`: no type check, so `add("a", "b")` concatenates. Fix: annotate and validate.

## 5. Supplemental implementation details

Inference: callers rely on integer results, since the only call site passes integers.
"""


def _script(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / ".claude/scripts/codedoc.py"), *args],
        cwd=root, capture_output=True, text=True,
    )


def _run(root: Path) -> tuple[Path, Path]:
    (root / "src").mkdir(exist_ok=True)
    (root / "src/widget.py").write_text("def add(a, b):\n    return a + b\n")
    out = _script(root, "start", "widget", "--target", "src/widget.py",
                  "--scope", "src/widget.py", "--prompt", "/code-doc src/widget.py")
    assert out.returncode == 0, out.stderr
    run, master = out.stdout.split()
    return root / run, root / master


def test_start_scaffolds_a_code_doc_run_and_finds_it_again(root: Path) -> None:
    run, master = _run(root)
    meta = json.loads((run / ".run.json").read_text())
    assert meta["kind"] == "code-doc" and meta["masters"] == ["widget.md"]
    assert master == run / "widget.md"
    assert "/code-doc src/widget.py" in (run / "prompt.md").read_text()

    again = _script(root, "start", "widget-again", "--target", "src/widget.py",
                    "--scope", "src/widget.py", "--prompt", "/code-doc src/widget.py again")
    assert again.stdout.split()[0] == str(run.relative_to(root))
    assert "again" in (run / "prompt.md").read_text()
    assert len(list((root / "outputs").glob("*code-doc*"))) == 1


def test_project_code_doc_stays_in_project_and_is_found_on_rerun(root: Path) -> None:
    standalone, _ = _run(root)
    project = root / "outputs/2026-11-08-widget-audit"
    project.mkdir(parents=True)
    args = ("start", "widget", "--target", "src/widget.py", "--scope", "src/widget.py",
            "--prompt", "/code-doc src/widget.py", "--project", "outputs/2026-11-08-widget-audit")
    first = _script(root, *args)
    assert first.returncode == 0, first.stderr
    run = project / "code-docs/widget"
    assert first.stdout.split()[0] == str(run.relative_to(root))
    assert (run / ".run.json").is_file()
    again = _script(root, *args)
    assert again.returncode == 0, again.stderr
    assert again.stdout.split()[0] == str(run.relative_to(root))
    assert list((root / "outputs").glob("*code-doc*")) == [standalone]


def test_a_cited_document_passes(root: Path) -> None:
    run, master = _run(root)
    master.write_text(DOC)
    out = _script(root, "check", str(master))
    assert out.returncode == 0, out.stdout
    assert "ERROR" not in out.stdout


def test_bad_references_and_uncited_statements_fail(root: Path) -> None:
    run, master = _run(root)
    master.write_text(
        DOC.replace("`src/widget.py:1-2`", "`src/widget.py:1-9`")
        .replace("`src/widget.py:2`.", "`src/gone.py:2`.")
        .replace("Inference: callers", "Callers")
        + "\nI read the whole module first `src/widget.py:1`.\n"
    )
    out = _script(root, "check", str(master)).stdout
    assert "outside the file" in out
    assert "src/gone.py` does not exist" in out
    assert "no code reference" in out
    assert "agent self-reference" in out


def test_missing_sections_and_diagram_fail(root: Path) -> None:
    run, master = _run(root)
    text = DOC.replace("```text\ncaller --> add() --> int\n```\n", "").replace(
        "### Reproduction guide", "### Usage")
    master.write_text(text)
    out = _script(root, "check", str(master)).stdout
    assert "has no diagram" in out
    assert "no 'reproduction guide' subsection" in out


def test_status_names_the_sections_a_code_change_affects(root: Path) -> None:
    run, master = _run(root)
    master.write_text(DOC)
    assert _script(root, "stamp", str(run)).returncode == 0
    assert _script(root, "status", str(run)).returncode == 0

    (root / "src/widget.py").write_text("def add(a, b):\n    return int(a) + int(b)\n")
    (root / "src/extra.py").write_text("X = 1\n")
    data = json.loads((run / ".run.json").read_text())
    data["scope"].append("src/extra.py")
    (run / ".run.json").write_text(json.dumps(data))
    out = _script(root, "status", str(run))
    assert out.returncode == 1
    assert "CHANGED src/widget.py (cited in: 1. Overview" in out.stdout
    assert "NEW src/extra.py" in out.stdout


def test_gate_checks_code_references_not_evidence_ids(root: Path) -> None:
    run, master = _run(root)
    master.write_text(DOC)
    _script(root, "stamp", str(run))
    gate = subprocess.run(
        [sys.executable, str(root / ".claude/scripts/gate.py"), str(master)],
        cwd=root, capture_output=True, text=True,
    )
    assert "[E" not in gate.stdout and "evidence" not in gate.stdout.lower(), gate.stdout
    master.write_text(DOC.replace("`src/widget.py:2`.", "`src/widget.py:40`."))
    gate = subprocess.run(
        [sys.executable, str(root / ".claude/scripts/gate.py"), str(master)],
        cwd=root, capture_output=True, text=True,
    )
    assert gate.returncode != 0 and "outside the file" in gate.stdout + gate.stderr


def test_run_check_shows_code_doc_stages(root: Path) -> None:
    run, master = _run(root)
    master.write_text(DOC)
    out = subprocess.run(
        [sys.executable, str(root / ".claude/scripts/run_check.py"), str(run), "--ship"],
        cwd=root, capture_output=True, text=True,
    )
    assert out.returncode == 1
    assert "references" in out.stdout and "review" in out.stdout
    assert "evidence" not in out.stdout

    (run / "review.md").write_text("Ready.\n")
    (run / "repair-log.md").write_text("Nothing to repair.\n")
    _script(root, "stamp", str(run))
    out = subprocess.run(
        [sys.executable, str(root / ".claude/scripts/run_check.py"), str(run), "--ship"],
        cwd=root, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stdout
