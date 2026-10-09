"""HTML, figures and PDF for a run's master, by the workspace's own export scripts.

The same chain the /export skill documents, run by code with no model call:

    figures.py build    the ```figure blocks become charts (PNG and SVG) in a styled copy
    references.py render  [E#] become reader-facing citations (research runs only)
    style.py css        the style's stylesheet
    pandoc              self-contained HTML
    weasyprint          PDF from that HTML

The master is never modified. A preview renders into the app's own cache
(`app/data/render/`); "Export" renders into `<run>/export/<style>/`, where the
/export skill puts its files, and runs `check_export.py` on the result.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from backend import config, workspace

TIMEOUT_S = 300


class RenderError(Exception):
    pass


def styles() -> list[dict[str, str]]:
    out = []
    for path in sorted((config.ROOT / ".claude/styles").glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        out.append(
            {
                "name": path.stem,
                "description": str(data.get("description") or data.get("label") or ""),
            }
        )
    return out


def citation_system(run: Path) -> str:
    """The citation system the run's voice.md records; house when it names none."""
    try:
        text = (run / "voice.md").read_text().lower()
    except OSError:
        return "house"
    for system in ("chicago-notes", "chicago-ad", "mla"):
        if system in text:
            return system
    return "house"


def _script(name: str) -> str:
    return str(config.ROOT / ".claude/scripts" / name)


def _run(cmd: list[str], env: dict[str, str] | None = None) -> str:
    try:
        done = subprocess.run(
            cmd,
            cwd=config.ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=env or config.child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderError(f"{Path(cmd[0]).name}: {exc}") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip()[-1500:]
        raise RenderError(f"{' '.join(Path(c).name for c in cmd[:3])} failed:\n{tail}")
    return (done.stdout + done.stderr).strip()


def _pandoc() -> str:
    found = config.binary("pandoc") or next(
        (p for p in ("/opt/homebrew/bin/pandoc", "/usr/local/bin/pandoc") if Path(p).exists()), None
    )
    if not found:
        raise RenderError("pandoc is not installed. Install it with `brew install pandoc`.")
    return found


def _source(run: Path, doc: str | None) -> Path:
    meta = workspace.run_meta(run)
    name = doc or meta.get("primary")
    if not name:
        raise RenderError("This run has no master document yet.")
    path = workspace.run_file(run.name, name)
    if path.suffix != ".md":
        raise RenderError("Only Markdown documents render to HTML.")
    return path


def build(
    run_name: str, doc: str | None, style: str, cite: bool, out: Path, figures_dir: Path
) -> dict[str, Any]:
    """Render one document into `out`: <stem>.md (reader copy), style.css, <stem>.html."""
    run = workspace.run_dir(run_name)
    src = _source(run, doc)
    if style not in {s["name"] for s in styles()}:
        raise RenderError(f"Unknown style: {style}")
    out.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    stem = "report" if src.name in ("report.md", "draft.md") else src.stem
    py = config.python()
    styled = out / "_styled.md"
    reader = out / f"{stem}.md"
    log = [
        _run(
            [
                py,
                _script("figures.py"),
                "build",
                str(src),
                "--style",
                style,
                "--outdir",
                str(figures_dir),
                "-o",
                str(styled),
                "--rel-from",
                str(out),
            ]
        )
    ]
    cited = cite and (run / "evidence.jsonl").is_file()
    if cited:
        log.append(
            _run(
                [
                    py,
                    _script("references.py"),
                    "render",
                    str(styled),
                    "--run",
                    str(run),
                    "-o",
                    str(reader),
                    "--citemap",
                    str(out / "citations.json"),
                    "--system",
                    citation_system(run),
                ]
            )
        )
    else:
        shutil.copyfile(styled, reader)
    css = [py, _script("style.py"), "css", style, "-o", str(out / "style.css")]
    log.append(_run([*css, "--cover"]))
    html = out / f"{stem}.html"
    pandoc = [
        _pandoc(),
        str(reader),
        "-s",
        "--section-divs",
        "--embed-resources",
        "-c",
        str(out / "style.css"),
        "-o",
        str(html),
    ]
    pandoc.insert(3, "--toc")
    # pandoc resolves the relative figure paths from the reader copy's folder.
    try:
        done = subprocess.run(
            pandoc,
            cwd=out,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=config.child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderError(f"pandoc: {exc}") from exc
    if done.returncode != 0:
        raise RenderError(f"pandoc failed:\n{done.stderr.strip()[-1500:]}")
    return {
        "html": html,
        "reader": reader,
        "stem": stem,
        "source": src,
        "cited": cited,
        "log": "\n".join(x for x in log if x),
    }


def figures(figures_dir: Path) -> list[dict[str, Any]]:
    """The rendered charts: one entry per figure, with its PNG and SVG when both exist."""
    found: dict[str, dict[str, Any]] = {}
    if figures_dir.is_dir():
        for p in sorted(figures_dir.iterdir()):
            if p.suffix.lower() in (".png", ".svg"):
                entry = found.setdefault(p.stem, {"name": p.stem, "files": {}})
                entry["files"][p.suffix.lower().lstrip(".")] = str(p)
    return list(found.values())


# ------------------------------------------------------------------ preview


def _cache(run_name: str, style: str, cite: bool) -> Path:
    return config.data_dir("render", run_name, f"{style}-{'cited' if cite else 'ids'}")


def preview(run_name: str, doc: str | None, style: str, cite: bool) -> dict[str, Any]:
    """Render into the app's cache, unless the cached HTML is newer than its inputs."""
    run = workspace.run_dir(run_name)
    src = _source(run, doc)
    cache = _cache(run_name, style, cite)
    stamp = cache / "source.json"
    inputs = [src, run / "evidence.jsonl", config.ROOT / ".claude/styles" / f"{style}.json"]
    newest = max((p.stat().st_mtime for p in inputs if p.exists()), default=0)
    try:
        meta = json.loads(stamp.read_text())
        if (
            meta.get("source") == src.name
            and meta.get("built", 0) >= newest
            and Path(meta["html"]).is_file()
        ):
            return {**meta, "figures": figures(cache / "figures"), "cached": True}
    except (OSError, ValueError, KeyError):
        pass
    result = build(run_name, doc, style, cite, cache / "out", cache / "figures")
    meta = {
        "source": src.name,
        "built": max(newest, src.stat().st_mtime) + 0.001,
        "html": str(result["html"]),
        "log": result["log"],
    }
    stamp.write_text(json.dumps(meta))
    return {**meta, "figures": figures(cache / "figures"), "cached": False}


def preview_file(run_name: str, style: str, cite: bool, rel: str) -> Path:
    """A file inside a preview cache (the HTML or a figure), checked to stay inside it."""
    base = _cache(run_name, style, cite).resolve()
    target = (base / rel).resolve()
    if base not in target.parents or not target.is_file():
        raise ValueError("not a rendered file")
    return target


# ------------------------------------------------------------------ export


def export(
    run_name: str, doc: str | None, style: str, cite: bool, formats: list[str]
) -> dict[str, Any]:
    """Render into <run>/export/<style>/ and add the requested formats, then check that
    the export lost nothing."""
    run = workspace.run_dir(run_name)
    out = run / "export" / style
    result = build(run_name, doc, style, cite, out, run / "figures" / style)
    made = [result["html"]] if "html" in formats or "pdf" in formats else []
    if "pdf" in formats:
        pdf = out / f"{result['stem']}.pdf"
        env = config.child_env()
        env["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(
            x for x in ("/opt/homebrew/lib", env.get("DYLD_FALLBACK_LIBRARY_PATH", "")) if x
        )
        code = (
            "import sys, weasyprint\n"
            "weasyprint.HTML(filename=sys.argv[1], base_url=sys.argv[2]).write_pdf(sys.argv[3])"
        )
        try:
            _run(
                [config.python(), "-c", code, str(result["html"]), str(out) + os.sep, str(pdf)],
                env=env,
            )
        except RenderError as exc:
            raise RenderError(
                f"PDF failed. weasyprint and pango must be installed for this Python.\n{exc}"
            ) from exc
        made.append(pdf)
    check = ""
    if made:
        citemap = out / "citations.json"
        cited = ["--citemap", str(citemap)] if result["cited"] and citemap.is_file() else []
        done = subprocess.run(
            [
                config.python(),
                _script("check_export.py"),
                *cited,
                str(result["reader"]),
                *map(str, made),
            ],
            cwd=config.ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=config.child_env(),
        )
        check = (done.stdout + done.stderr).strip()
        check = (
            "Export check passed.\n" if done.returncode == 0 else "Export check found losses:\n"
        ) + check
    return {
        "files": [str(p.relative_to(config.ROOT)) for p in made],
        "folder": str(out.relative_to(config.ROOT)),
        "check": check,
        "figures": figures(run / "figures" / style),
    }


def save_figures(
    run_name: str, style: str, cite: bool, names: list[str], kinds: list[str]
) -> list[str]:
    """Copy rendered figures from the preview into <run>/export/<style>/figures/."""
    run = workspace.run_dir(run_name)
    src = _cache(run_name, style, cite) / "figures"
    dest = run / "export" / style / "figures"
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for fig in figures(src):
        if names and fig["name"] not in names:
            continue
        for kind, path in fig["files"].items():
            if kind in kinds:
                target = dest / Path(path).name
                shutil.copyfile(path, target)
                saved.append(str(target.relative_to(config.ROOT)))
    return saved
