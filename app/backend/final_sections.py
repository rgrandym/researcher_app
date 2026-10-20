"""Load the report section guard for app controls."""

import importlib.util
import sys
from pathlib import Path

from backend import workspace


def guard():
    scripts = workspace.root() / ".claude" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("research_section_guard", scripts / "section_guard.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("section guard unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sections(doc: Path) -> list[dict[str, str | bool]]:
    module = guard()
    locked = module.read_locks(doc)
    return [{"heading": key, "final": key in locked} for key in module.split_sections(doc.read_text())
            if key != module.PREAMBLE]


def set_final(doc: Path, heading: str, final: bool) -> None:
    guard().set_lock(doc, heading, final)


def changed_final(doc: Path, content: str) -> list[str]:
    module = guard()
    return module.lock_drift(doc, module.split_sections(content))
