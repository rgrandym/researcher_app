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


def _font(name: str) -> str:
    return ", ".join(f'"{n}"' if " " in n else n for n in appearance.FONT_STACKS[name])


# Layout every render carries: each caption directly below its table or figure, in small
# type and kept with it; tables and charts fitted to the text column, so a change to their
# settings resizes them within the text instead of spilling past it.
LAYOUT_CSS = f"""
/* Captions below, and tables and charts fitted to the text */
p:has(+ table):not(.table-caption) {{ font: inherit; color: inherit; margin: 0 0 0.85em; break-after: auto; page-break-after: auto; }}
table {{ max-width: 100%; margin: 1.2em auto 0.35em; }}
p.table-caption {{ margin: 0 0 1.4em; line-height: 1.35; break-before: avoid; page-break-before: avoid; }}
p.table-caption, p.table-caption strong {{ font-size: {appearance.CAPTION_PT}pt; }}
figure {{ margin: 1.4em 0; }}
figure img {{ display: block; width: 100%; max-width: 100%; height: auto; }}
figcaption {{ font-size: {appearance.CAPTION_PT}pt; margin-top: 0.35em; line-height: 1.35; }}
"""


def report_css(custom: dict[str, Any]) -> str:
    """Tables, table captions and figure captions in their own colours, fonts and sizes,
    so a change to the page palette or fonts does not reach them, nor theirs the page."""
    t, ch = custom["table_settings"], custom["chart"]
    return (
        "\n/* Tables and captions, apart from the page */\n"
        f"table {{ font-family: {_font(t['font_family'])}; font-size: {t['font_size_pt']}pt; }}\n"
        f"th {{ font-family: {_font(t['header_font'])}; font-size: {t['header_font_size_pt']}pt; "
        f"background: {t['header_bg']}; color: {t['header_fg']}; }}\n"
        f"td {{ background: {t['body_bg']}; color: {t['body_fg']}; }}\n"
        f"tbody tr:nth-child(even) td {{ background: {t['stripe_bg']}; }}\n"
        f"th strong, td strong {{ color: inherit; }}\n"
        f"p.table-caption, p.table-caption strong {{ font-family: {_font(t['header_font'])}; "
        f"font-size: {t['caption_font_size_pt']}pt; color: {t['caption_fg']}; }}\n"
        f"figcaption {{ color: {ch['caption_color']}; font-size: {ch['caption_font_size_pt']}pt; }}\n"
        f"figcaption strong {{ color: {ch['caption_label_color']}; }}\n"
    )


def table_css(overrides: dict[str, dict[str, Any]]) -> str:
    """The stylesheet rules for tables with individual settings, by their HTML ids."""
    rules = []
    for table_id, item in overrides.items():
        sel = f"#report-table-{table_id}"
        cap = f"#report-caption-{table_id}"
        look = item.get("borders", "horizontal")
        rules.append(
            f"{sel} {{ font-family: {_font(item['font_family'])}; font-size: {item['font_size_pt']}pt; "
            f"width: {item['width_percent']}%; max-width: 100%; margin-left: auto; margin-right: auto; "
            f"border-collapse: collapse; border: none; }}\n"
            f"{sel} th {{ font-family: inherit; font-size: {item['header_font_size_pt']}pt; "
            f"background: {item['header_bg']}; color: {item['header_fg']}; "
            f"padding: {item['cell_padding_em']}em; border: none; }}\n"
            f"{cap}, {cap} strong {{ font-size: {item['caption_font_size_pt']}pt; color: {item['caption_fg']}; }}\n"
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
_FIGURE_IMAGE = re.compile(r"!\[\*\*Figure \d+\.\*\*[^\n]*?\]\([^)\s]+\)(?!\{)")


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
    with_highlights: bool = False,
) -> dict[str, Any]:
    """Render one document into `out`: <stem>.md (reader copy), style.css, <stem>.html.
    With `text`, renders that in place of the saved document (the editor's unsaved copy)."""
    run = workspace.run_dir(run_name)
    master = _source(run, doc)
    src = master
    # Every table is numbered: one with no caption line gets an untitled one, in a working
    # copy rendered in place of the document. The document itself is never changed here.
    raw = master.read_text() if text is None else text
    captioned = appearance.captions_below(appearance.with_captions(raw))
    if text is not None or captioned != raw:
        src = out.parent / "src" / master.name
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(_absolute_images(captioned, run))
    if style not in {s["name"] for s in styles()}:
        raise RenderError(f"Unknown style: {style}")
    out.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    custom = appearance.effective(run_name, style, master.name)
    style_arg = style
    if custom is not None:
        effective_path = out / "_effective-style.json"
        effective_path.write_text(json.dumps(custom))
        style_arg = str(effective_path)
    stem = "report" if src.name in ("report.md", "draft.md") else src.stem
    noted = comments.open_for(run_name, master.name, with_comments, with_highlights)
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
    # Charts take the width of the text column in Word too (HTML sizes them by CSS).
    styled.write_text(_FIGURE_IMAGE.sub(r"\g<0>{width=100%}", styled.read_text()))
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
    with (out / "style.css").open("a") as stream:
        stream.write(LAYOUT_CSS)
        if custom or placed:
            if custom:
                stream.write(report_css(custom))
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

        # The caption paragraph is tagged too: it is styled with its table, and a click on
        # it in the preview picks that table.
        def caption_tag(text: str, table_id: str) -> str:
            at = text.rfind("<p", 0, text.rfind("<strong>Table"))
            return text[:at] + f'<p class="table-caption" id="report-caption-{table_id}"' + text[at + 2 :]

        def tag_above(match: re.Match[str]) -> str:
            table_id = by_number.get(match.group(2))
            if not table_id or sides.get(table_id) != "above":
                return match.group(0)
            return caption_tag(match.group(1), table_id) + f'<table id="report-table-{table_id}"'

        def tag_below(match: re.Match[str]) -> str:
            table_id = by_number.get(match.group(2))
            if not table_id or sides.get(table_id) != "below":
                return match.group(0)
            return f'<table id="report-table-{table_id}"' + caption_tag(match.group(1), table_id)

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
        "comments": sum(1 for c in placed.values() if not comments.is_highlight(c)),
        "table_ids": table_ids,
        "table_sides": sides,
        "table_overrides": table_overrides,
        "table_settings": custom["table_settings"] if custom and custom.get("table_custom") else None,
        "captions": (
            (custom["table_settings"]["caption_font_size_pt"], custom["table_settings"]["caption_fg"]),
            (custom["chart"]["caption_font_size_pt"], custom["chart"]["caption_color"]),
        ) if custom else ((appearance.CAPTION_PT, None), (appearance.CAPTION_PT, None)),
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
    docx_tables.captions(target, *result["captions"])
    items = dict(result["table_overrides"])
    if result["table_settings"]:
        # The report's own table settings dress every captioned table without its own.
        base = {**result["table_settings"], "cell_padding_em": 0.45, "width_percent": 100,
                "rule_style": "solid", "borders": "horizontal"}
        items = {table_id: items.get(table_id, base) for table_id in result["table_ids"]}
    docx_tables.apply(target, result["table_ids"], result["table_sides"], items, appearance.FONT_STACKS)
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


def _doc_cache(run_name: str, style: str, cite: bool, run: Path, src: Path) -> Path:
    """Each document's own preview cache: two windows showing different documents of a run
    neither rebuild in turn nor write over each other's intermediate files."""
    key = str(src.relative_to(run.resolve())).replace("/", "__")
    return _cache(run_name, style, cite) / "docs" / key


_preview_locks: dict[str, threading.Lock] = {}


def preview(run_name: str, doc: str | None, style: str, cite: bool) -> dict[str, Any]:
    """Render into the app's cache, unless the cached HTML is newer than its inputs."""
    run = workspace.run_dir(run_name)
    src = _source(run, doc)
    cache = _doc_cache(run_name, style, cite, run, src)
    cache.mkdir(parents=True, exist_ok=True)
    with _preview_locks.setdefault(str(cache), threading.Lock()):
        return _preview(run_name, doc, style, cite, run, src, cache)


def _preview(run_name: str, doc: str | None, style: str, cite: bool, run: Path, src: Path, cache: Path) -> dict[str, Any]:
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
    # The rendering code itself: an updated app re-renders rather than serving old output.
    for code in sorted((*Path(__file__).parent.glob("*.py"), *(config.ROOT / ".claude/scripts").glob("*.py"))):
        digest.update(f"{code.name}:{code.stat().st_mtime_ns}".encode())
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
    result = build(run_name, doc, style, cite, cache / "out", cache / "figures", with_highlights=True)
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
        result = build(
            run_name, doc, style, cite, base / "out", base / "figures", text=text, with_highlights=True
        )
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


def record_path(out: Path, stem: str) -> Path:
    """Where an export records how it was made, beside the files it wrote."""
    return out / f".{stem}.export.json"


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
    # How this copy was made, so it can be made again the same way when the document changes.
    record_path(out, result["stem"]).write_text(json.dumps({
        "doc": str(_source(run, doc).relative_to(run.resolve())),
        "cite": cite, "comments": with_comments, "formats": formats,
    }) + "\n")
    return {
        "files": [str(p.relative_to(config.ROOT)) for p in made],
        "folder": str(out.relative_to(config.ROOT)),
        "check": check,
        "comments": result["comments"],
        "figures": figures(run / "figures" / style),
    }


def save_figures(
    run_name: str, style: str, cite: bool, names: list[str], kinds: list[str], doc: str | None = None
) -> list[str]:
    """Copy rendered figures from a document's preview into <run>/export/<style>/figures/."""
    run = workspace.run_dir(run_name)
    src = _doc_cache(run_name, style, cite, run, _source(run, doc)) / "figures"
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
