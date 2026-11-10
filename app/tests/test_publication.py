"""Proposals to write outside the workspace are read-only here: validated and snapshotted,
never carried out, and no route approves or performs a publication."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
from conftest import RUN

from backend import main, publication


def propose(root: Path, ops: list[dict], dest: str = "/tmp/elsewhere") -> None:
    folder = root / "outputs" / RUN / "publications"
    folder.mkdir(exist_ok=True)
    (folder / "p1.json").write_text(json.dumps({"title": "T", "destination_root": dest, "operations": ops}))


def source(root: Path, name: str = "doc.md", text: str = "hello\n") -> None:
    (root / "outputs" / RUN / name).write_text(text)


def w(path: str = "docs/A.md", src: str = "doc.md", expect: str = "absent") -> dict:
    return {"path": path, "action": "write", "source": src, "expect": expect}


def test_snapshot_carries_bytes_and_hash(root: Path) -> None:
    source(root)
    propose(root, [w(), {"path": "docs/B.md", "action": "delete", "expect": "sha256:" + "a" * 64}])
    snap = publication.snapshot(RUN, "p1")
    first = snap["operations"][0]
    assert base64.b64decode(first["content"]) == b"hello\n"
    assert first["sha256"] == "sha256:" + hashlib.sha256(b"hello\n").hexdigest()
    assert snap["expires"] - snap["issued"] == publication.TTL_SECONDS
    assert publication.list_proposals(RUN)[0]["operations"] == 2


@pytest.mark.parametrize("bad", ["../x.md", "/abs.md", "a//b.md", "a/./b.md", "a\\b.md", "a/\x01.md", ""])
def test_bad_target_paths_refused(root: Path, bad: str) -> None:
    source(root)
    propose(root, [w(path=bad)])
    with pytest.raises(publication.ProposalError):
        publication.snapshot(RUN, "p1")


def test_duplicate_targets_refused(root: Path) -> None:
    source(root)
    propose(root, [w("docs/A.md"), w("docs/a.md")])
    with pytest.raises(publication.ProposalError):
        publication.snapshot(RUN, "p1")


def test_source_must_stay_in_project_and_be_plain(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "secret.md"
    outside.write_text("x")
    run = root / "outputs" / RUN
    os.symlink(outside, run / "link.md")
    for src in ("../../../../secret.md", "link.md", "missing.md"):
        propose(root, [w(src=src)])
        with pytest.raises((publication.ProposalError, FileNotFoundError)):
            publication.snapshot(RUN, "p1")
    (run / "hard.md").write_text("x")
    os.link(run / "hard.md", run / "hard2.md")
    propose(root, [w(src="hard.md")])
    with pytest.raises(publication.ProposalError):
        publication.snapshot(RUN, "p1")


def test_relative_root_and_bad_expect_and_limits(root: Path) -> None:
    source(root)
    for ops, dest in (
        ([w()], "relative/dir"),
        ([w(expect="whatever")], "/tmp/x"),
        ([], "/tmp/x"),
        ([w(f"d/{i}.md") for i in range(33)], "/tmp/x"),
        ([{"path": "a.md", "action": "delete", "expect": "absent"}], "/tmp/x"),
        ([{"path": "a.md", "action": "run", "expect": "absent"}], "/tmp/x"),
    ):
        propose(root, ops, dest)
        with pytest.raises(publication.ProposalError):
            publication.snapshot(RUN, "p1")


def test_binary_source_refused(root: Path) -> None:
    (root / "outputs" / RUN / "bin.md").write_bytes(b"\xff\xfe\x00")
    propose(root, [w(src="bin.md")])
    with pytest.raises(publication.ProposalError):
        publication.snapshot(RUN, "p1")


def test_no_route_writes_outside_or_approves() -> None:
    """The backend exposes only GET routes for publications: nothing here can carry one out."""
    routes = [(r.path, sorted(r.methods)) for r in main.app.routes if "publication" in getattr(r, "path", "")]
    assert routes and all(methods == ["GET"] for _, methods in routes)
    forbidden = ("approve", "confirm", "execute", "apply", "publish")
    assert not [p for p, _ in routes if any(word in p for word in forbidden)]
    source_text = Path(publication.__file__).read_text()
    assert "write_text" not in source_text and "write_bytes" not in source_text and "open(" not in source_text
