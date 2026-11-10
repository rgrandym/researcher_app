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


def _paths(out: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    """The run and master `start` printed. They are its last two lines, after the anchor,
    the inventory and the scope total."""
    assert out.returncode == 0, out.stderr or out.stdout
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    return lines[-2], lines[-1]


def _script(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / ".claude/scripts/codedoc.py"), *args],
        cwd=root, capture_output=True, text=True,
    )


def _run(root: Path) -> tuple[Path, Path]:
    (root / "src").mkdir(exist_ok=True)
    (root / "src/widget.py").write_text("def add(a, b):\n    return a + b\n")
    out = _script(root, "start", "widget", "--target", "src/widget.py", "--anchor", "src/widget.py",
                  "--scope", "src/widget.py", "--prompt", "/code-doc src/widget.py")
    run, master = _paths(out)
    return root / run, root / master


def test_start_scaffolds_a_code_doc_run_and_finds_it_again(root: Path) -> None:
    run, master = _run(root)
    meta = json.loads((run / ".run.json").read_text())
    assert meta["kind"] == "code-doc" and meta["masters"] == ["widget.md"]
    assert master == run / "widget.md"
    assert "/code-doc src/widget.py" in (run / "prompt.md").read_text()

    again = _script(root, "start", "widget-again", "--target", "src/widget.py", "--anchor", "src/widget.py",
                    "--scope", "src/widget.py", "--prompt", "/code-doc src/widget.py again")
    assert _paths(again)[0] == str(run.relative_to(root))
    assert "again" in (run / "prompt.md").read_text()
    assert len(list((root / "outputs").glob("*code-doc*"))) == 1


def test_project_code_doc_stays_in_project_and_is_found_on_rerun(root: Path) -> None:
    standalone, _ = _run(root)
    project = root / "outputs/2026-11-08-widget-audit"
    project.mkdir(parents=True)
    args = ("start", "widget", "--target", "src/widget.py", "--anchor", "src/widget.py",
            "--scope", "src/widget.py",
            "--prompt", "/code-doc src/widget.py", "--project", "outputs/2026-11-08-widget-audit")
    first = _script(root, *args)
    assert first.returncode == 0, first.stderr
    run = project / "code-docs/widget"
    assert _paths(first)[0] == str(run.relative_to(root))
    assert (run / ".run.json").is_file()
    again = _script(root, *args)
    assert again.returncode == 0, again.stderr
    assert _paths(again)[0] == str(run.relative_to(root))
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


def test_map_leads_and_claims_give_cheap_context(root: Path) -> None:
    run, master = _run(root)
    (root / "src/panel.ts").write_text(
        "export function render(x: number) {\n  const local = 1\n  return x + local\n}\n"
        "export interface Props { a: number }\n"
    )
    out = _script(root, "map", str(run))
    assert out.returncode == 0 and "(rebuilt)" in out.stdout
    rows = (run / "notes/codemap.tsv").read_text()
    assert "src/widget.py:1\tdef\tadd" in rows
    assert "src/panel.ts:1\tfunction\trender" in rows and "src/panel.ts:5\tinterface\tProps" in rows
    assert "local" not in rows
    assert "(current)" in _script(root, "map", str(run)).stdout

    master.write_text(DOC)
    out = _script(root, "claims", str(master))
    assert out.returncode == 0
    sheet = (run / "notes/claims.md").read_text()
    assert "> The module adds two numbers" in sheet
    assert "     2      return a + b" in sheet

    assert "no earlier work" in _script(root, "leads", str(run)).stdout


def test_leads_point_to_the_projects_earlier_work(root: Path) -> None:
    (root / "src").mkdir(exist_ok=True)
    (root / "src/widget.py").write_text("def add(a, b):\n    return a + b\n")
    project = root / "outputs/2026-11-07-docs-audit"
    (project / "subjects/widget-guide").mkdir(parents=True)
    (project / "subjects/widget-guide/changes.json").write_text(json.dumps({"changes": [{}, {}, {}]}))
    (project / "notes").mkdir()
    (project / "notes/widget.md").write_text("WIDGET_GUIDE.md says add() validates input.\n")
    (project / "notes/other.md").write_text("unrelated\n")
    out = _script(root, "start", "widget", "--target", "docs/WIDGET_GUIDE.md",
                  "--anchor", "src/widget.py", "--scope", "src/widget.py",
                  "--prompt", "/code-doc docs/WIDGET_GUIDE.md", "--project", "outputs/2026-11-07-docs-audit")
    assert out.returncode == 0, out.stderr
    leads = _script(root, "leads", _paths(out)[0]).stdout
    assert "subjects/widget-guide/changes.json (3 change(s) already traced to the code)" in leads
    assert "notes/widget.md" in leads and "other.md" not in leads


def test_readers_notes_must_use_full_references(root: Path) -> None:
    run, _ = _run(root)
    (run / "notes/read-core.md").write_text(
        "# core\n\n- add returns a sum `src/widget.py:1-2`\n- shorthand `W:2`\n- past the end `src/widget.py:9`\n")
    out = _script(root, "notes", str(run))
    assert out.returncode == 1
    assert "`W` does not exist" in out.stdout and "is outside the file" in out.stdout
    (run / "notes/read-core.md").write_text("# core\n\n- add returns a sum `src/widget.py:1-2`\n")
    assert "OK notes" in _script(root, "notes", str(run)).stdout
