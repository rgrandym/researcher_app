"""Regression checks for the code-doc scope and document boundary."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codedoc  # noqa: E402


class CodeDocBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "src").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "src" / "node.py").write_text("def run():\n    return 1\n")
        (self.root / "docs" / "runbook.md").write_text("# Runbook\n")
        root_patch = patch.object(codedoc, "ROOT", self.root)
        code_patch = patch.object(codedoc, "CODE_ROOT", self.root)
        root_patch.start()
        code_patch.start()
        self.addCleanup(root_patch.stop)
        self.addCleanup(code_patch.stop)

    def test_reference_document_cannot_anchor_a_run(self):
        with self.assertRaisesRegex(SystemExit, "reference document"):
            codedoc.start("runbook", "docs/runbook.md", ["docs/runbook.md"],
                          "request", anchor="docs/runbook.md")
        self.assertFalse((self.root / "outputs").exists())

    def test_reference_document_cannot_name_a_new_run(self):
        with self.assertRaisesRegex(SystemExit, "reference document cannot be the code-doc target"):
            codedoc.start("runbook", "docs/runbook.md (the whole workflow)",
                          ["src/node.py"], "request", anchor="src/node.py")
        self.assertFalse((self.root / "outputs").exists())

    def test_oversized_scope_stops_before_run_creation(self):
        (self.root / "src" / "large.py").write_text("x\n" * 6001)
        with self.assertRaisesRegex(SystemExit, "6000 lines"):
            codedoc.start("node", "node", ["src"], "request", anchor="src/node.py")
        self.assertFalse((self.root / "outputs").exists())

    def test_too_many_small_files_stops_before_run_creation(self):
        for number in range(40):
            (self.root / "src" / f"part{number}.py").write_text("x\n")
        with self.assertRaisesRegex(SystemExit, "41 files"):
            codedoc.start("node", "node", ["src"], "request", anchor="src/node.py")
        self.assertFalse((self.root / "outputs").exists())

    def test_new_documents_end_with_code_health(self):
        run = codedoc.start("node", "node", ["src/node.py"], "request",
                             anchor="src/node.py")
        meta = json.loads((run / ".run.json").read_text())
        self.assertEqual(meta["format_version"], 2)
        doc = run / "node.md"
        sections = [
            "## 1. Overview and responsibilities",
            "## 2. Architecture and system interactions\n\n```text\nnode\n```",
            "## 3. Complete technical and reproduction specification",
            "### Detailed architecture",
            "### Tech stack and dependencies",
            "### Reproduction guide",
            "## 4. Supplemental implementation details",
            "## 5. Code health, gaps and suggested improvements",
        ]
        doc.write_text("# Node\n\nCommit test.\n\n" + "\n\n".join(sections) + "\n")
        errors, _ = codedoc.check(doc)
        self.assertEqual(errors, [])
        doc.write_text(doc.read_text() + "\n## Appendix\n")
        errors, _ = codedoc.check(doc)
        self.assertTrue(any("code health must be the final section" in error for error in errors))
        doc.write_text(doc.read_text().replace("\n## Appendix\n", ""))
        doc.write_text(doc.read_text().replace(
            sections[-2] + "\n\n" + sections[-1],
            sections[-1] + "\n\n" + sections[-2],
        ))
        errors, _ = codedoc.check(doc)
        self.assertTrue(any("sections out of order" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
