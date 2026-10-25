"""HTML, figures and PDF for a run's master, by the workspace's own export scripts.

The same chain the /export skill documents, run by code with no model call:

    figures.py build    the ```figure blocks become charts (PNG and SVG) in a styled copy
    references.py render  [E#] become reader-facing citations (research runs only)
    style.py css        the style's stylesheet
    pandoc              self-contained HTML, and Word with the style's reference document
    weasyprint          PDF from that HTML

The author's comments (`comments.py`) ride along as pandoc comment spans: Word comments
in the .docx, highlighted passages with notes in the HTML, footnotes in the PDF.

The master is never modified. A preview renders into the app's own cache
(`app/data/render/`); "Export" renders into `<run>/export/<style>/`, where the
/export skill puts its files, and runs `check_export.py` on the result.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from backend import appearance, comments, config, workspace

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


def _rule(item: dict[str, Any], heavy: float = 1.0) -> str:
    width = item["rule_weight_pt"] * heavy
    if item.get("rule_style") == "double":
        width = max(width, 2.4)  # thinner, a double rule draws as one line
    return f"{width:.2f}pt {item.get('rule_style', 'solid')} {item['border']}"


def table_css(overrides: dict[str, dict[str, Any]]) -> str:
    """The stylesheet rules for tables with individual settings, by their HTML ids."""
    rules = []
    for table_id, item in overrides.items():
        sel = f"#report-table-{table_id}"
        font = ", ".join(f'"{name}"' if " " in name else name for name in appearance.FONT_STACKS[item["font_family"]])
        look = item.get("borders", "horizontal")
        rules.append(
            f"{sel} {{ font-family: {font}; font-size: {item['font_size_pt']}pt; "
            f"width: {item['width_percent']}%; border-collapse: collapse; border: none; }}\n"
            f"{sel} th {{ font-family: inherit; background: {item['header_bg']}; color: {item['header_fg']}; "
            f"padding: {item['cell_padding_em']}em; border: none; }}\n"
            f"{sel} td {{ background: {item['body_bg']}; color: {item['body_fg']}; "
            f"padding: {item['cell_padding_em']}em; border: none; }}\n"
            f"{sel} tbody tr:nth-child(even) td {{ background: {item['stripe_bg']}; }}"
        )
        if look == "horizontal":
            rules.append(f"{sel} th, {sel} td {{ border-bottom: {_rule(item)}; }}")
        elif look == "grid":
            rules.append(f"{sel} th, {sel} td {{ border: {_rule(item)}; }}")
        elif look == "minimal":
            rules.append(
                f"{sel} {{ border-top: {_rule(item, 1.6)}; border-bottom: {_rule(item, 1.6)}; }}\n"
                f"{sel} th {{ border-bottom: {_rule(item, 1.2)}; }}"
            )
        elif look == "boxed":
            rules.append(f"{sel} {{ border: {_rule(item)}; }}\n{sel} th {{ border-bottom: {_rule(item, 1.2)}; }}")
        else:
            rules.append(f"{sel} th {{ border-bottom: {_rule(item, 1.2)}; }}")
    return "\n/* Individual tables */\n" + "\n".join(rules) + "\n"


_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def _absolute_images(text: str, folder: Path) -> str:
    """Images written relative to the run, made absolute for a copy rendered elsewhere."""

    def fix(m: re.Match[str]) -> str:
        target = m.group(2)
        if re.match(r"^(?:[a-z]+:|/|#)", target, re.I) or not (folder / target).exists():
            return m.group(0)
        return f"![{m.group(1)}]({(folder / target).resolve()})"

    return _IMAGE.sub(fix, text)


def build(
    run_name: str,
    doc: str | None,
    style: str,
    cite: bool,
    out: Path,
    figures_dir: Path,
    with_comments: bool = True,
    text: str | None = None,
) -> dict[str, Any]:
    """Render one document into `out`: <stem>.md (reader copy), style.css, <stem>.html.
    With `text`, renders that in place of the saved document (the editor's unsaved copy)."""
    run = workspace.run_dir(run_name)
    master = _source(run, doc)
    src = master
    if text is not None:
        src = out.parent / "src" / master.name
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(_absolute_images(text, run))
    if style not in {s["name"] for s in styles()}:
        raise RenderError(f"Unknown style: {style}")
    out.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    custom = appearance.effective(run_name, style)
    style_arg = style
    if custom is not None:
        effective_path = out / "_effective-style.json"
        effective_path.write_text(json.dumps(custom))
        style_arg = str(effective_path)
    stem = "report" if src.name in ("report.md", "draft.md") else src.stem
    noted = comments.open_for(run_name, master.name) if with_comments else []
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
                style_arg,
                "--outdir",
                str(figures_dir),
                "-o",
                str(styled),
                "--rel-from",
                str(out),
            ]
        )
    ]
    placed: dict[str, dict[str, Any]] = {}
    if noted:
        marked, placed = comments.inject(styled.read_text(), noted)
        styled.write_text(marked)
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
    css = [py, _script("style.py"), "css", style_arg, "-o", str(out / "style.css")]
    log.append(_run([*css, "--cover"]))
    table_overrides = custom.get("item_overrides", {}).get("tables", {}) if custom else {}
    if table_overrides or placed:
        with (out / "style.css").open("a") as stream:
            if table_overrides:
                stream.write(table_css(table_overrides))
            if placed:
                stream.write(comments.CSS)
    # The export loss check compares the outputs with a reader copy that has no comments.
    check_copy = reader
    if placed:
        check_copy = out / "_check.md"
        check_copy.write_text(comments.strip(reader.read_text()))
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
    # Every captioned table gets its id, so a click on it names it and its own styles reach it.
    source_md = src.read_text()
    table_ids = [m.group(2) for m in appearance.TABLE_CAP.finditer(source_md)]
    sides = appearance.table_sides(source_md)
    if table_ids:
        by_number = {str(i): table_id for i, table_id in enumerate(table_ids, 1)}
        caption = r'<p[^>]*>\s*<strong>Table (\d+)\.</strong>'
        above = re.compile(rf"({caption}(?:(?!</p>).)*</p>\s*)<table\b", re.S)
        below = re.compile(rf"<table\b((?:(?!<table\b).)*?</table>\s*{caption})", re.S)

        def tag_above(match: re.Match[str]) -> str:
            table_id = by_number.get(match.group(2))
            if not table_id or sides.get(table_id) != "above":
                return match.group(0)
            return match.group(1) + f'<table id="report-table-{table_id}"'

        def tag_below(match: re.Match[str]) -> str:
            table_id = by_number.get(match.group(2))
            if not table_id or sides.get(table_id) != "below":
                return match.group(0)
            return f'<table id="report-table-{table_id}"' + match.group(1)

        html.write_text(below.sub(tag_below, above.sub(tag_above, html.read_text())))
    if placed:
        html.write_text(comments.mark_html(html.read_text(), placed))
    return {
        "html": html,
        "reader": reader,
        "check_reader": check_copy,
        "stem": stem,
        "source": src,
        "style_arg": style_arg,
        "cited": cited,
        "comments": len(placed),
        "table_ids": table_ids,
        "table_sides": sides,
        "table_overrides": table_overrides,
        "log": "\n".join(x for x in log if x),
    }


def _docx(result: dict[str, Any], out: Path) -> Path:
    """Word from the reader copy, in the style's reference document; comments become
    Word comments, and tables with individual settings keep them."""
    from backend import docx_tables

    ref = out / "reference.docx"
    _run([config.python(), _script("style.py"), "docx-ref", result["style_arg"], "-o", str(ref)])
    target = out / f"{result['stem']}.docx"
    try:
        done = subprocess.run(
            [_pandoc(), str(result["reader"]), f"--reference-doc={ref}", "-o", str(target)],
            cwd=out,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=config.child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderError(f"pandoc: {exc}") from exc
    if done.returncode != 0:
        raise RenderError(f"pandoc (Word) failed:\n{done.stderr.strip()[-1500:]}")
    docx_tables.apply(
        target, result["table_ids"], result["table_sides"], result["table_overrides"], appearance.FONT_STACKS
    )
    return target


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
    appearance_file = run / appearance.FILE
    global_defaults_file = config.DATA / "appearance-defaults.json"
    digest = hashlib.sha256()
    for source in (appearance_file, global_defaults_file):
        if source.exists():
            digest.update(source.read_bytes())
    digest.update(comments.stamp(run_name))
    appearance_hash = digest.hexdigest()
    meta: dict[str, Any] = {}
    try:
        meta = json.loads(stamp.read_text())
        if (
            meta.get("source") == src.name
            and meta.get("appearance_hash", "") == appearance_hash
            and meta.get("built", 0) >= newest
            and Path(meta["html"]).is_file()
        ):
            return {**meta, "figures": figures(cache / "figures"), "cached": True}
    except (OSError, ValueError, KeyError):
        pass
    result = build(run_name, doc, style, cite, cache / "out", cache / "figures")
    meta = {
        "source": src.name,
        "appearance_hash": appearance_hash,
        "built": max(time.time(), newest + 0.001, float(meta.get("built", 0)) + 0.001),
        "html": str(result["html"]),
        "log": result["log"],
    }
    stamp.write_text(json.dumps(meta))
    return {**meta, "figures": figures(cache / "figures"), "cached": False}


_live_locks: dict[str, threading.Lock] = {}


def live(run_name: str, doc: str | None, style: str, cite: bool, text: str) -> dict[str, Any]:
    """Render the editor's unsaved text, for the HTML view beside a popped-out editor.
    Never cached and never written to the run: it lands in the preview cache's live/."""
    if len(text) > 2_000_000:
        raise RenderError("The document is too large to preview while editing.")
    base = _cache(run_name, style, cite) / "live"
    lock = _live_locks.setdefault(f"{run_name}/{style}/{cite}", threading.Lock())
    with lock:
        result = build(run_name, doc, style, cite, base / "out", base / "figures", text=text)
    return {
        "source": result["source"].name,
        "built": time.time(),
        "html": str(result["html"]),
        "log": result["log"],
        "figures": figures(base / "figures"),
        "cached": False,
        "live": True,
    }


def cache_dir(run_name: str, style: str, cite: bool) -> Path:
    return _cache(run_name, style, cite)


def preview_file(run_name: str, style: str, cite: bool, rel: str) -> Path:
    """A file inside a preview cache (the HTML or a figure), checked to stay inside it."""
    base = _cache(run_name, style, cite).resolve()
    target = (base / rel).resolve()
    if base not in target.parents or not target.is_file():
        raise ValueError("not a rendered file")
    return target


# ------------------------------------------------------------------ export


def export(
    run_name: str,
    doc: str | None,
    style: str,
    cite: bool,
    formats: list[str],
    with_comments: bool = True,
) -> dict[str, Any]:
    """Render into <run>/export/<style>/ and add the requested formats, then check that
    the export lost nothing."""
    run = workspace.run_dir(run_name)
    out = run / "export" / style
    result = build(run_name, doc, style, cite, out, run / "figures" / style, with_comments)
    made = [result["html"]] if "html" in formats or "pdf" in formats else []
    if "docx" in formats:
        made.append(_docx(result, out))
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
                str(result["check_reader"]),
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
        "comments": result["comments"],
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
