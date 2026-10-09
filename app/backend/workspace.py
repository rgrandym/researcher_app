"""Everything the app reads from the workspace, and the checked, versioned saves of the
Workspace view.

Reads: the commands the prompt bar offers (from `.claude/skills/*/SKILL.md` and
`.claude/commands/*.md`), the run folders under `outputs/` with their lane and stage
status, the exports, and the guide. Lane and master come from the workspace's own
`runmeta.py`; stage status from `run_check.py`. Nothing here makes a model call.

Writes happen only when the author saves a file in the Workspace view: the save is
checked by script, written, and committed alone to the local repository.
"""

from __future__ import annotations

import difflib
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from backend import config

RUN_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9._-]+$")
RUN_IN_PATH = re.compile(r"outputs/(\d{4}-\d{2}-\d{2}-[A-Za-z0-9._-]+)")
STAGE_LINE = re.compile(r"^ {2}(ok|MISSING)\s+(\S+)\s+(.*)$")


def root() -> Path:
    return config.ROOT


def outputs() -> Path:
    return root() / "outputs"


# ------------------------------------------------------------------ frontmatter


def frontmatter(text: str) -> dict[str, str] | None:
    """The YAML frontmatter's flat keys, or None when there is no frontmatter block.
    Handles `key: value`, quoted values and folded (`>`, `|`) blocks: what skills use."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    out: dict[str, str] = {}
    key = None
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            out[key] = "" if value in (">", "|", ">-", "|-") else value.strip("'\"")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def body(text: str) -> str:
    """The text after the frontmatter."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            return text[end + 4 :].lstrip("\n")
    return text


# ------------------------------------------------------------------ commands


def commands() -> list[dict[str, str]]:
    """Every workspace command the prompt bar offers, with its description."""
    found: dict[str, dict[str, str]] = {}
    for path in sorted((root() / ".claude/skills").glob("*/SKILL.md")):
        meta = frontmatter(_read(path)) or {}
        name = meta.get("name") or path.parent.name
        if meta.get("user-invocable", "true").lower() == "false":
            continue
        found[name] = {
            "name": name,
            "description": meta.get("description", ""),
            "kind": "skill",
            "path": _rel(path),
        }
    for path in sorted((root() / ".claude/commands").glob("*.md")):
        meta = frontmatter(_read(path)) or {}
        found.setdefault(
            path.stem,
            {
                "name": path.stem,
                "description": meta.get("description", ""),
                "kind": "command",
                "path": _rel(path),
            },
        )
    return sorted(found.values(), key=lambda c: c["name"])


def expand_command(prompt: str) -> tuple[str, str | None]:
    """For a runtime without native skills (Codex): `/name args` becomes an instruction to
    read and follow the skill, or the command's body with `$ARGUMENTS` replaced. Returns
    (prompt, command name or None)."""
    m = re.match(r"^/([A-Za-z0-9:_-]+)\s*(.*)$", prompt.strip(), re.S)
    if not m:
        return prompt, None
    name, args = m.group(1), m.group(2).strip()
    skill = root() / ".claude/skills" / name / "SKILL.md"
    command = root() / ".claude/commands" / f"{name}.md"
    if skill.is_file():
        text = (
            f"The author invoked the workspace command /{name}. Read `.claude/skills/{name}/SKILL.md` "
            f"and follow it, together with any files it points to.\n\nArguments: {args or '(none)'}"
        )
        return text, name
    if command.is_file():
        text = (
            f"The author invoked the workspace command /{name} (`.claude/commands/{name}.md`). "
            f"Follow these instructions:\n\n{body(_read(command)).replace('$ARGUMENTS', args)}"
        )
        return text, name
    return prompt, None


# ------------------------------------------------------------------ runs


_runmeta: ModuleType | None = None


def runmeta() -> ModuleType | None:
    """The workspace's own runmeta.py, loaded from `.claude/scripts/`."""
    global _runmeta
    if _runmeta is None:
        path = root() / ".claude/scripts/runmeta.py"
        spec = importlib.util.spec_from_file_location("ws_runmeta", path)
        if spec is None or spec.loader is None or not path.exists():
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _runmeta = module
    return _runmeta


def run_dir(name: str) -> Path:
    if not RUN_NAME.match(name):
        raise ValueError(f"not a run name: {name}")
    path = outputs() / name
    if not path.is_dir():
        raise FileNotFoundError(name)
    return path


def run_meta(path: Path) -> dict[str, Any]:
    rm = runmeta()
    if rm is None:
        return {"kind": "research", "masters": ["report.md", "draft.md"]}
    meta: dict[str, Any] = rm.meta(path)
    primary = rm.primary(path)
    meta["primary"] = primary.name if primary else None
    return meta


_stage_cache: dict[str, tuple[float, float, list[dict[str, str]]]] = {}


def stages(name: str, max_age: float = 15) -> list[dict[str, str]]:
    """`run_check.py` for one run, parsed. Re-run when the run changed, at most every
    `max_age` seconds."""
    path = run_dir(name)
    mtime = newest_mtime(path)
    hit = _stage_cache.get(name)
    if hit and (hit[1] >= mtime or time.time() - hit[0] < max_age):
        return hit[2]
    text = run_check_text(name)
    rows = []
    for line in text.splitlines():
        m = STAGE_LINE.match(line)
        if m:
            rows.append(
                {
                    "stage": m.group(2),
                    "ok": "yes" if m.group(1) == "ok" else "",
                    "detail": m.group(3).strip(),
                }
            )
    _stage_cache[name] = (time.time(), mtime, rows)
    return rows


def run_check_text(name: str) -> str:
    try:
        done = subprocess.run(
            [config.python(), str(root() / ".claude/scripts/run_check.py"), f"outputs/{name}"],
            cwd=root(),
            capture_output=True,
            text=True,
            timeout=30,
            env=config.child_env(),
        )
        return done.stdout.strip() or done.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"run_check.py could not run: {exc}"


def newest_mtime(path: Path) -> float:
    newest = path.stat().st_mtime
    for p in path.rglob("*"):
        if "export" in p.parts or ".history" in p.parts:
            continue
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            continue
    return newest


def list_runs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    base = outputs()
    if not base.is_dir():
        return out
    for path in base.iterdir():
        if not path.is_dir() or not RUN_NAME.match(path.name):
            continue
        meta = run_meta(path)
        prompt = _read(path / "prompt.md")
        out.append(
            {
                "name": path.name,
                "kind": meta.get("kind", "research"),
                "doc_kind": meta.get("doc_kind", "report"),
                "primary": meta.get("primary"),
                "mtime": path.stat().st_mtime,
                "prompt": _first_line(prompt),
            }
        )
    return sorted(out, key=lambda r: r["name"], reverse=True)


def run_detail(name: str) -> dict[str, Any]:
    path = run_dir(name)
    meta = run_meta(path)
    files = []
    for p in sorted(path.rglob("*")):
        if p.is_file() and ".history" not in p.parts and not p.name.startswith(".voice-mirror"):
            st = p.stat()
            files.append(
                {"path": str(p.relative_to(path)), "size": st.st_size, "mtime": st.st_mtime}
            )
    primary = meta.get("primary")
    return {
        "name": name,
        "path": str(path),
        "meta": meta,
        "stages": stages(name),
        "files": files,
        "master": _read(path / primary) if primary else "",
        "evidence_rows": count_jsonl(path / "evidence.jsonl"),
        "notes": len(list((path / "notes").glob("*.md"))) if (path / "notes").is_dir() else 0,
    }


def run_file(name: str, rel: str) -> Path:
    base = run_dir(name).resolve()
    target = (base / rel).resolve()
    if base not in target.parents and target != base:
        raise ValueError("outside the run")
    if not target.is_file():
        raise FileNotFoundError(rel)
    return target


class Conflict(Exception):
    pass


def save_run_file(name: str, rel: str, content: str, base_mtime: float | None) -> float:
    """The author's edit to a Markdown file in a run, as if saved from their editor. Refused
    when the file changed on disk since it was loaded, so neither side's edit is lost."""
    base = run_dir(name).resolve()
    target = (base / rel).resolve()
    if (
        base not in target.parents
        or target.suffix != ".md"
        or "export" in target.relative_to(base).parts
    ):
        raise ValueError("Only Markdown files in the run (outside export/) can be edited here.")
    if (
        target.exists()
        and base_mtime is not None
        and abs(target.stat().st_mtime - base_mtime) > 0.001
    ):
        raise Conflict(
            f"{rel} changed on disk since you opened it. Reload it, then make your edit again."
        )
    target.write_text(content)
    return target.stat().st_mtime


def trash_run(name: str) -> str:
    """Move a run folder to the macOS Trash. Recoverable from the Trash until it is emptied."""
    path = run_dir(name)
    trash = Path.home() / ".Trash"
    trash.mkdir(exist_ok=True)
    dest = trash / name
    if dest.exists():
        dest = trash / f"{name} {time.strftime('%H-%M-%S')}"
    shutil.move(str(path), str(dest))
    _stage_cache.pop(name, None)
    return str(dest)


def count_jsonl(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    for line in _read(path).splitlines():
        if line.strip():
            try:
                json.loads(line)
                n += 1
            except ValueError:
                pass
    return n


def runs_in(text: str) -> set[str]:
    return set(RUN_IN_PATH.findall(text))


# ------------------------------------------------------------------ exports

# Deliverables only: not the stylesheets, citation maps and page renders beside them.
EXPORT_TYPES = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".md", ".odt", ".epub"}


def list_exports() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    base = outputs()
    if not base.is_dir():
        return out
    for path in base.glob("*/export/**/*"):
        run = path.relative_to(base).parts[0]
        rel = path.relative_to(base / run / "export")
        if (
            not path.is_file()
            or len(rel.parts) > 2
            or path.suffix.lower() not in EXPORT_TYPES
            or path.name.startswith((".", "_", "reference."))
            or path.stem.endswith("_src")
        ):
            continue
        style = rel.parts[0] if len(rel.parts) > 1 else ""
        out.append(
            {
                "run": run,
                "style": style,
                "name": path.name,
                "path": str(path.relative_to(root())),
                "size": path.stat().st_size,
                "mtime": path.stat().st_mtime,
            }
        )
    return sorted(out, key=lambda e: (e["run"], e["style"], e["name"]), reverse=False)


def export_path(rel: str) -> Path:
    target = (root() / rel).resolve()
    base = outputs().resolve()
    if (
        base not in target.parents
        or "export" not in target.relative_to(base).parts
        or not target.is_file()
    ):
        raise ValueError("not an export")
    return target


# ------------------------------------------------------------------ the guide


def guide() -> str:
    return _read(root() / "USERGUIDE.md")


# ------------------------------------------------------------------ Workspace view: listing

GROUPS: list[tuple[str, list[str]]] = [
    ("Skills", [".claude/skills/*/SKILL.md", ".claude/skills/*/references/**/*.md"]),
    ("Commands", [".claude/commands/*.md"]),
    ("Agents", [".claude/agents/*.md"]),
    ("Shared doctrine", [".claude/references/*.md"]),
    ("Voice", [".claude/voice/profile.md"]),
    ("Workspace rules", ["CLAUDE.md", "AGENTS.md", "USERGUIDE.md"]),
    ("Scripts", [".claude/scripts/*.py", ".claude/scripts/*.sh"]),
    ("Hooks and settings", [".claude/settings.json", ".claude/monitor.json", ".codex/hooks.json"]),
    ("Mods", [".claude/skills/research-monitor/**/*"]),
    ("App prompts", ["app/prompts/*.md"]),
]


def workspace_files() -> list[dict[str, Any]]:
    groups = []
    seen: set[str] = set()
    for label, patterns in GROUPS:
        files = []
        for pattern in patterns:
            for path in sorted(root().glob(pattern)):
                rel = _rel(path)
                if (
                    not path.is_file()
                    or rel in seen
                    or "node_modules" in path.parts
                    or "__pycache__" in path.parts
                ):
                    continue
                if label == "Skills" and "research-monitor" in path.parts:
                    continue
                seen.add(rel)
                files.append({"path": rel, "name": _label(path), "mtime": path.stat().st_mtime})
        groups.append({"group": label, "files": files})
    return groups


def editable(rel: str) -> Path:
    """A path the Workspace view may write: one listed there, or a new skill or command."""
    target = (root() / rel).resolve()
    if root().resolve() not in target.parents:
        raise ValueError("outside the workspace")
    rel_norm = str(target.relative_to(root().resolve()))
    if rel_norm.startswith(("outputs/", ".git/")) or "/external_data/" in rel_norm:
        raise ValueError("not editable from the Workspace view")
    listed = {f["path"] for g in workspace_files() for f in g["files"]}
    new_ok = re.match(
        r"^\.claude/(skills/[A-Za-z0-9_-]+/SKILL\.md|commands/[A-Za-z0-9_-]+\.md|agents/[A-Za-z0-9_-]+\.md)$",
        rel_norm,
    )
    if rel_norm not in listed and not new_ok:
        raise ValueError("not a Workspace file")
    return target


TEMPLATES = {
    "skill": "---\nname: {name}\ndescription: {description}\n---\n\n# {title}\n\nWhat this skill does, step by step.\n",
    "command": "---\ndescription: {description}\n---\n\n{title}. Target: $ARGUMENTS\n",
    "agent": "---\nname: {name}\ndescription: {description}\ntools: Read, Grep\n---\n\nWhat this agent does.\n",
}


def new_file(kind: str, name: str, description: str) -> tuple[str, str]:
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
        raise ValueError("Use lower-case letters, digits and hyphens.")
    rel = {
        "skill": f".claude/skills/{name}/SKILL.md",
        "command": f".claude/commands/{name}.md",
        "agent": f".claude/agents/{name}.md",
    }[kind]
    if (root() / rel).exists():
        raise ValueError(f"{rel} already exists")
    text = TEMPLATES[kind].format(
        name=name,
        description=description or "One line on when to use it.",
        title=name.replace("-", " ").capitalize(),
    )
    return rel, text


# ------------------------------------------------------------------ Workspace view: checks


def check(rel: str, content: str) -> list[str]:
    """Problems that block a save, by file type. Script checks only, no model call."""
    problems: list[str] = []
    path = root() / rel
    name = path.name
    in_mod = "research-monitor" in Path(rel).parts
    if (
        rel.startswith((".claude/skills/", ".claude/commands/", ".claude/agents/"))
        and name.endswith(".md")
        and not in_mod
        and "references" not in Path(rel).parts
    ):
        meta = frontmatter(content)
        if meta is None:
            problems.append("The frontmatter block (between --- lines) is missing or not closed.")
        else:
            if (name == "SKILL.md" or rel.startswith(".claude/agents/")) and not meta.get("name"):
                problems.append("The frontmatter has no `name`.")
            if not meta.get("description"):
                problems.append("The frontmatter has no `description`.")
    if name.endswith(".json"):
        try:
            data = json.loads(content)
        except ValueError as exc:
            problems.append(f"Not valid JSON: {exc}")
        else:
            problems += _hook_files(data)
    if name.endswith(".py"):
        problems += _compile(content)
    if name.endswith(".sh"):
        problems += _shell(content)
    if rel == ".claude/voice/profile.md":
        problems += _voice(content)
    if in_mod:
        problems += _mod_checks(path, content)
    return problems


def _hook_files(data: Any) -> list[str]:
    """Every hook command must name a file that exists."""
    problems = []
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return []
    for event, entries in hooks.items():
        for entry in entries or []:
            for hook in (entry or {}).get("hooks") or []:
                cmd = str((hook or {}).get("command") or "")
                expanded = re.sub(
                    r"\$\{CLAUDE_PROJECT_DIR[^}]*\}|\$CLAUDE_PROJECT_DIR|\$\(git rev-parse --show-toplevel\)",
                    str(root()),
                    cmd,
                )
                try:
                    words = shlex.split(expanded)
                except ValueError:
                    problems.append(f"{event}: the hook command does not parse: {cmd}")
                    continue
                for word in words:
                    if re.search(r"\.(py|sh|js|ts|mjs)$", word):
                        target = Path(word) if Path(word).is_absolute() else root() / word
                        if not target.exists():
                            problems.append(
                                f"{event}: the hook names {word}, which does not exist."
                            )
    return problems


def _compile(content: str) -> list[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(content)
    try:
        done = subprocess.run(
            [config.python(), "-m", "py_compile", fh.name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (
            []
            if done.returncode == 0
            else [f"Python does not compile: {done.stderr.strip()[-600:]}"]
        )
    finally:
        Path(fh.name).unlink(missing_ok=True)


def _shell(content: str) -> list[str]:
    done = subprocess.run(["bash", "-n"], input=content, capture_output=True, text=True, timeout=30)
    return (
        []
        if done.returncode == 0
        else [f"The shell script does not parse: {done.stderr.strip()[-600:]}"]
    )


def _voice(content: str) -> list[str]:
    """`voice.py lint` must still run against the new profile (exit 0 or 1; a crash fails)."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(content)
    try:
        done = subprocess.run(
            [
                config.python(),
                str(root() / ".claude/scripts/voice.py"),
                "lint",
                str(root() / "USERGUIDE.md"),
                "--profile",
                fh.name,
            ],
            cwd=root(),
            capture_output=True,
            text=True,
            timeout=60,
            env=config.child_env(),
        )
        if done.returncode in (0, 1) and "Traceback" not in done.stderr:
            return []
        return [f"voice.py lint no longer runs with this profile: {done.stderr.strip()[-600:]}"]
    finally:
        Path(fh.name).unlink(missing_ok=True)


def _mod_checks(path: Path, content: str) -> list[str]:
    """The mod: `claude plugin validate` and `claude plugin test` on a copy with the change."""
    claude = config.binary("claude")
    if not claude:
        return ["Claude Code is needed to validate the mod and was not found."]
    mod = root() / ".claude/skills/research-monitor"
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "research-monitor"
        subprocess.run(["cp", "-R", str(mod), str(copy)], check=False)
        target = copy / path.relative_to(mod)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        for args in (["plugin", "validate", str(copy)], ["plugin", "test", str(copy)]):
            done = subprocess.run(
                [claude, *args], capture_output=True, text=True, timeout=180, env=config.child_env()
            )
            if done.returncode != 0:
                problems.append(
                    f"claude {' '.join(args[:2])} failed: {(done.stdout + done.stderr).strip()[-600:]}"
                )
    return problems


# ------------------------------------------------------------------ Workspace view: diff, save, history


def diff(rel: str, new: str, old: str | None = None) -> str:
    if old is None:
        old = _read(root() / rel)
    return "".join(
        difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}")
    )


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root(), capture_output=True, text=True, timeout=30)


def save(rel: str, content: str, message: str) -> dict[str, Any]:
    """Check, write, and commit this one file. Never pushes; never commits another file."""
    target = editable(rel)
    problems = check(rel, content)
    if problems:
        return {"ok": False, "problems": problems}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    commit = _commit(rel, message or f"Edit {rel}")
    return {"ok": True, "problems": [], "commit": commit}


def _commit(rel: str, message: str) -> str | None:
    if git("check-ignore", "-q", rel).returncode == 0:
        return None  # an ignored file is saved but not versioned
    git("add", "--", rel)
    done = git("commit", "--only", "-m", message, "--", rel)
    if done.returncode != 0:
        return None
    return git("rev-parse", "--short", "HEAD").stdout.strip() or None


def history(rel: str) -> list[dict[str, str]]:
    editable(rel)
    done = git("log", "--follow", "--format=%H%x09%h%x09%aI%x09%s", "--", rel)
    out = []
    for line in done.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            out.append({"rev": parts[0], "short": parts[1], "date": parts[2], "message": parts[3]})
    return out


def show_commit(rel: str, rev: str) -> str:
    if not re.match(r"^[0-9a-f]{7,40}$", rev):
        raise ValueError("bad revision")
    return git("show", "--format=%h %aI%n%s%n", rev, "--", rel).stdout


def restore(rel: str, rev: str) -> dict[str, Any]:
    if not re.match(r"^[0-9a-f]{7,40}$", rev):
        raise ValueError("bad revision")
    done = git("show", f"{rev}:{rel}")
    if done.returncode != 0:
        raise ValueError(done.stderr.strip() or "no such version")
    return save(rel, done.stdout, f"Restore {rel} to {rev[:7]}")


# ------------------------------------------------------------------ gates


def gate(doc: Path) -> tuple[int, str]:
    """`gate.py` on one master document: (exit code, findings)."""
    try:
        done = subprocess.run(
            [config.python(), str(root() / ".claude/scripts/gate.py"), str(doc)],
            cwd=root(),
            capture_output=True,
            text=True,
            timeout=180,
            env=config.child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 0, f"gate.py could not run: {exc}"
    return done.returncode, (done.stdout + done.stderr).strip()


def masters_changed_since(runs: set[str], since: float) -> list[Path]:
    out = []
    rm = runmeta()
    for name in runs:
        try:
            path = run_dir(name)
        except (ValueError, FileNotFoundError):
            continue
        names = rm.masters(path) if rm else ["report.md", "draft.md"]
        for m in names:
            doc = path / m
            if doc.is_file() and doc.stat().st_mtime >= since:
                out.append(doc)
    return out


# ------------------------------------------------------------------ helpers


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(root().resolve()))


def _label(path: Path) -> str:
    rel = _rel(path)
    if path.name == "SKILL.md":
        return path.parent.name
    if "/skills/" in rel and "references" in path.parts:
        return f"{rel.split('/')[2]} / {path.name}"
    return (
        path.name
        if "research-monitor" not in path.parts
        else str(path.relative_to(root() / ".claude/skills/research-monitor"))
    )


def _first_line(text: str) -> str:
    """The first line of the verbatim prompt, past the scaffold's header."""
    if "## Verbatim prompt" in text:
        text = text.split("## Verbatim prompt", 1)[1]
    for line in text.splitlines():
        line = line.strip().lstrip("#>").strip()
        if line and not line.startswith("**") and line.lower() not in ("request", "prompt"):
            return line[:200]
    return ""
