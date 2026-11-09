"""Incremental verification must select every changed assertion and source row."""

import importlib.util
import json
import sys
from pathlib import Path

from conftest import REAL_ROOT


def _module():
    path = REAL_ROOT / ".claude/scripts/verification_scope.py"
    spec = importlib.util.spec_from_file_location("verification_scope_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uncited_passage_and_source_grade_are_fingerprinted(tmp_path: Path) -> None:
    scope = _module()
    doc = tmp_path / "draft.md"
    evidence = tmp_path / "evidence.jsonl"
    doc.write_text("# Answer\n\nThe supported claim [E1].\n\n# Detail\n\nA factual claim without an ID.\n")
    evidence.write_text(json.dumps({"id": "E1", "quote": "claim", "url": "https://example.org", "admiralty": "A1"}) + "\n")
    first = scope.snapshot(tmp_path, doc)
    doc.write_text(doc.read_text().replace("A factual claim", "A changed factual claim"))
    assert len({r["hash"] for r in scope.snapshot(tmp_path, doc)["paragraphs"]}
               - {r["hash"] for r in first["paragraphs"]}) == 1
    evidence.write_text(json.dumps({"id": "E1", "quote": "claim", "url": "https://example.org", "admiralty": "C3"}) + "\n")
    assert scope.snapshot(tmp_path, doc)["sources"]["[E1]"] != first["sources"]["[E1]"]


def test_duplicate_or_malformed_evidence_cannot_be_reused(tmp_path: Path) -> None:
    scope = _module()
    evidence = tmp_path / "evidence.jsonl"
    evidence.write_text('{"id":"E1"}\n{"id":"E1"}\n')
    try:
        scope.source_hashes(tmp_path)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate evidence was accepted")


def test_cli_keeps_changed_text_in_scope_file(tmp_path: Path, monkeypatch, capsys) -> None:
    scope = _module()
    (tmp_path / "evidence.jsonl").write_text('{"id":"E1","quote":"source"}\n')
    (tmp_path / "draft.md").write_text("# Detail\n\nFirst claim [E1].\n")
    monkeypatch.setattr(sys, "argv", ["verification_scope.py", "snapshot", str(tmp_path), "draft.md"])
    scope.main()
    stored = json.loads((tmp_path / ".verification-snapshot.json").read_text())
    assert stored["version"] == scope.VERSION
    assert "text" not in stored["paragraphs"][0]
    (tmp_path / "report.md").write_text("# Detail\n\nChanged claim [E1].\n")
    monkeypatch.setattr(sys, "argv", ["verification_scope.py", "diff", str(tmp_path), "report.md"])
    scope.main()
    printed = capsys.readouterr().out
    assert "Changed claim" not in printed
    assert "Changed claim [E1]" in (tmp_path / ".verification-scope.md").read_text()
