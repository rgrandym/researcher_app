from pathlib import Path

from backend import final_sections


def test_final_section_survives_scope_and_snapshot(tmp_path: Path) -> None:
    doc = tmp_path / "report.md"
    doc.write_text("# Introduction\nApproved.\n\n# Discussion\nDraft.\n")
    guard = final_sections.guard()
    final_sections.set_final(doc, "# Introduction", True)
    assert final_sections.sections(doc)[0]["final"] is True
    changed = "# Introduction\nApproved.\n\n# Discussion\nRevised.\n"
    assert final_sections.changed_final(doc, changed) == []

    changed = "# Introduction\nRewritten.\n\n# Discussion\nRevised.\n"
    assert final_sections.changed_final(doc, changed) == ["# Introduction"]
    doc.write_text(changed)
    assert guard.lock_drift(doc, guard.split_sections(doc.read_text())) == ["# Introduction"]

    final_sections.set_final(doc, "# Introduction", False)
    assert final_sections.changed_final(doc, changed) == []
