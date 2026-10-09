"""The Research app's backend: REST for the views, one WebSocket for live turns, and the
built front end.

Binds to 127.0.0.1 only. Every call except /api/health carries the per-launch token
(header `X-App-Token`, or `token` in the query for the WebSocket), and the Host header
must name this machine, so a web page elsewhere cannot drive the app.

Run: `uvicorn backend.main:app --port 8765` from `app/` (scripts/dev.sh does this).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import activity, config, keychain, render, sessions, workspace
from backend.providers.base import Event, ProviderError
from backend.turns import TurnManager

app = FastAPI(title="Research", docs_url=None, redoc_url=None)
manager = TurnManager()
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
_status_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _host_ok(host: str | None) -> bool:
    return (host or "").split(":")[0] in LOCAL_HOSTS


@app.middleware("http")
async def guard(request: Request, call_next: Any) -> Response:
    if not _host_ok(request.headers.get("host")):
        return JSONResponse({"detail": "forbidden host"}, status_code=403)
    path = request.url.path
    if path.startswith("/api/") and path != "/api/health":
        token = request.headers.get("x-app-token") or request.query_params.get("token")
        if token != config.TOKEN:
            return JSONResponse({"detail": "missing or wrong app token"}, status_code=401)
    response: Response = await call_next(request)
    return response


def _bad(exc: Exception, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


# ------------------------------------------------------------------ health and state


@app.get("/api/health")
def health() -> dict[str, Any]:
    # `clients` is the number of open windows; the launcher stops the backend when it
    # has been zero for a while.
    return {
        "ok": True,
        "app": "research",
        "running": manager.any_running(),
        "clients": len(manager.hub.everyone),
    }


@app.get("/api/commands")
def commands() -> list[dict[str, str]]:
    hidden = set(config.load_settings().get("hidden_commands") or [])
    return [c for c in workspace.commands() if c["name"] not in hidden]


@app.get("/api/guide", response_class=PlainTextResponse)
def guide() -> str:
    return workspace.guide()


# ------------------------------------------------------------------ connections and settings


def _status(conn: str, fresh: bool = False) -> dict[str, Any]:
    hit = _status_cache.get(conn)
    if hit and not fresh and time.time() - hit[0] < 30:
        return hit[1]
    provider = manager.provider(conn)
    st = provider.status().model_dump()
    _status_cache[conn] = (time.time(), st)
    return st


@app.get("/api/connections")
async def connections(fresh: bool = False) -> list[dict[str, Any]]:
    out = []
    for conn in config.CONNECTIONS:
        st = await asyncio.to_thread(_status, conn, fresh)
        u = await asyncio.to_thread(manager.provider(conn).usage)
        out.append({**st, "usage": u.model_dump() if u else None})
    return out


@app.get("/api/usage/{conn}")
async def connection_usage(conn: str) -> dict[str, Any]:
    try:
        u = await asyncio.to_thread(manager.provider(conn).usage)
    except ProviderError as exc:
        raise _bad(exc, 404) from exc
    return u.model_dump() if u else {}


@app.post("/api/connections/{conn}/login")
def login(conn: str) -> dict[str, Any]:
    provider = manager.provider(conn)
    if getattr(provider, "billing", "") == "key":
        raise HTTPException(400, "This connection uses an API key; add one instead.")
    try:
        provider.start_login()  # type: ignore[attr-defined]
    except ProviderError as exc:
        raise _bad(exc) from exc
    _status_cache.pop(conn, None)
    return {
        "ok": True,
        "message": "The sign-in page opens in your browser. Refresh this card when you are done.",
    }


class KeyBody(BaseModel):
    key: str


@app.post("/api/connections/{conn}/key")
def add_key(conn: str, body: KeyBody) -> dict[str, Any]:
    if not conn.endswith("-api"):
        raise HTTPException(400, "Only API-key connections take a key.")
    if not body.key.strip():
        raise HTTPException(400, "The key is empty.")
    try:
        keychain.put(conn, body.key.strip())
    except RuntimeError as exc:
        raise _bad(exc) from exc
    _status_cache.pop(conn, None)
    return {"ok": True}


@app.delete("/api/connections/{conn}/key")
def remove_key(conn: str) -> dict[str, Any]:
    keychain.delete(conn)
    _status_cache.pop(conn, None)
    return {"ok": True}


@app.post("/api/connections/{conn}/test")
async def test_connection(conn: str) -> dict[str, Any]:
    """Binary version and sign-in status only. No model turn."""
    return await asyncio.to_thread(_status, conn, True)


@app.post("/api/connections/{conn}/test-turn")
async def test_turn(conn: str) -> dict[str, Any]:
    """One small model turn, sent only when the author presses "Send a test message"."""
    session = sessions.create("Test message")
    await manager.send(session.id, "Reply with the single word ready. Do not use any tool.", conn)
    return {"session": session.id}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return {**config.load_settings(), "caps": activity.caps_config()}


@app.put("/api/settings")
def put_settings(body: dict[str, Any]) -> dict[str, Any]:
    caps = body.pop("caps", None)
    settings = config.save_settings(body)
    return {
        **settings,
        "caps": activity.save_caps(caps) if isinstance(caps, dict) else activity.caps_config(),
    }


# ------------------------------------------------------------------ sessions


@app.get("/api/sessions")
def list_sessions() -> list[dict[str, Any]]:
    out = sessions.list_all()
    for s in out:
        s["running"] = manager.is_running(s["id"])
    return out


class NewSession(BaseModel):
    title: str = "New session"


@app.post("/api/sessions")
def new_session(body: NewSession) -> dict[str, Any]:
    return sessions.payload(sessions.create(body.title))


@app.get("/api/sessions/{sid}")
def get_session(sid: str) -> dict[str, Any]:
    try:
        session = sessions.load(sid)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc
    pending = manager.running.get(sid)
    return {
        **sessions.payload(session),
        "running": manager.is_running(sid),
        "open_permissions": list(pending.permissions) if pending else [],
    }


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str) -> dict[str, Any]:
    if manager.is_running(sid):
        raise HTTPException(409, "Stop the running turn first.")
    sessions.delete(sid)
    return {"ok": True}


@app.post("/api/sessions/{sid}/keep")
def keep_session(sid: str) -> dict[str, Any]:
    """Continue the open provider session despite a configuration change."""
    session = sessions.load(sid)
    session.stale = False
    sessions.save(session)
    return {"ok": True}


@app.get("/api/sessions/{sid}/activity")
def session_activity(sid: str) -> dict[str, Any]:
    try:
        return activity.build(sid, manager.is_running(sid), manager.providers)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc


@app.post("/api/sessions/{sid}/raise-cap")
def raise_cap(sid: str) -> dict[str, Any]:
    session = sessions.load(sid)
    seg = session.current() or (session.segments[-1] if session.segments else None)
    if not seg or not seg.native_session_id:
        raise HTTPException(400, "This session has no provider session yet.")
    searches, fetches = activity.raise_cap(seg.native_session_id)
    return {"search_cap": searches, "fetch_cap": fetches}


class Attachment(BaseModel):
    name: str
    data: str  # base64


class AttachBody(BaseModel):
    files: list[Attachment]


@app.post("/api/sessions/{sid}/attach")
def attach(sid: str, body: AttachBody) -> dict[str, Any]:
    """Supplied sources go to the current run's `external_data/`. Before a run exists they
    wait in the session folder, and the prompt tells the agent where."""
    session = sessions.load(sid)
    run = session.runs[-1] if session.runs else None
    target = (
        (config.OUTPUTS / run / "external_data")
        if run
        else config.data_dir("sessions", sid, "attachments")
    )
    target.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in body.files:
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(f.name).name).strip() or "file"
        (target / name).write_bytes(base64.b64decode(f.data))
        saved.append(name)
    rel = (
        str(target.relative_to(config.ROOT)) if target.is_relative_to(config.ROOT) else str(target)
    )
    note = f"Attached files, saved in {rel}/: {', '.join(saved)}."
    if not run:
        note += " Move them into the run's external_data/ when you scaffold the run."
    return {"saved": saved, "folder": rel, "note": note}


# ------------------------------------------------------------------ runs and exports


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    return workspace.list_runs()


@app.get("/api/runs/{name}")
def run(name: str) -> dict[str, Any]:
    try:
        return workspace.run_detail(name)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc


class ProjectChat(BaseModel):
    new: bool = False


@app.post("/api/runs/{name}/chat")
def project_chat(name: str, body: ProjectChat) -> dict[str, Any]:
    """The project's conversation: the latest one, or a new one tied to the run."""
    try:
        workspace.run_dir(name)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc
    session = None if body.new else sessions.for_project(name)
    if session is None:
        session = sessions.create(name)
        session.project = name
        session.runs = [name]
        sessions.save(session)
    return {
        **sessions.payload(session),
        "running": manager.is_running(session.id),
        "open_permissions": [],
    }


@app.get("/api/runs/{name}/file")
def run_file(name: str, path: str) -> Response:
    try:
        target = workspace.run_file(name, path)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc
    if target.suffix.lower() in (
        ".md",
        ".txt",
        ".jsonl",
        ".json",
        ".csv",
        ".py",
        ".yaml",
        ".yml",
        ".bib",
        ".tsv",
    ):
        response = PlainTextResponse(target.read_text(errors="replace")[:2_000_000])
        response.headers["X-Mtime"] = repr(target.stat().st_mtime)  # for the edit conflict check
        return response
    return FileResponse(target)


class RunFileBody(BaseModel):
    path: str
    content: str
    mtime: float | None = None


@app.put("/api/runs/{name}/file")
def save_run_file(name: str, body: RunFileBody) -> dict[str, Any]:
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this run. Save when its turn finishes.")
    try:
        mtime = workspace.save_run_file(name, body.path, body.content, body.mtime)
    except workspace.Conflict as exc:
        raise _bad(exc, 409) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc
    return {"ok": True, "mtime": mtime}


def _run_busy(name: str) -> bool:
    owner = manager.locks.get(name)
    return bool(owner and manager.is_running(owner))


@app.delete("/api/runs/{name}")
def delete_run(name: str) -> dict[str, Any]:
    """Remove a project and everything the app holds about it.

    The run folder goes to the macOS Trash (recoverable until the Trash is emptied).
    Its conversations go: the project's Chat-tab ones, and any that only ever worked on
    this run. A conversation that also touched other runs is kept, with this run struck
    from it. The render cache and the run's lock file are deleted."""
    own, shared = [], []
    for s in sessions.list_all():
        session = sessions.load(s["id"])
        if session.project == name or session.runs == [name]:
            own.append(session)
        elif name in session.runs:
            shared.append(session)
    if _run_busy(name) or any(manager.is_running(s.id) for s in own):
        raise HTTPException(409, "An agent is working on this project. Stop it first.")
    try:
        where = workspace.trash_run(name)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc
    for session in own:
        sessions.delete(session.id)
    for session in shared:
        session.runs = [r for r in session.runs if r != name]
        sessions.save(session)
    shutil.rmtree(config.DATA / "render" / name, ignore_errors=True)
    (config.DATA / "locks" / f"{name}.lock").unlink(missing_ok=True)
    manager.locks.pop(name, None)
    return {"ok": True, "trash": where, "removed_sessions": [s.id for s in own]}


@app.get("/api/styles")
def list_styles() -> list[dict[str, str]]:
    return render.styles()


class RenderBody(BaseModel):
    doc: str | None = None
    style: str = "meridian"
    cite: bool = True
    formats: list[str] = []


def _rendered_view(name: str, body: RenderBody, meta: dict[str, Any]) -> dict[str, Any]:
    base = Path(meta["html"]).parent.parent

    def rel(p: str) -> str:
        return str(Path(p).resolve().relative_to(base.resolve()))

    return {
        "html": rel(meta["html"]),
        "figures": [
            {"name": f["name"], "files": {k: rel(v) for k, v in f["files"].items()}}
            for f in meta["figures"]
        ],
        "cached": meta.get("cached"),
        "built": meta.get("built"),
        "log": meta.get("log", ""),
        "style": body.style,
        "cite": body.cite,
    }


@app.post("/api/runs/{name}/render")
async def render_run(name: str, body: RenderBody) -> dict[str, Any]:
    """HTML preview of the master in a style, by the workspace's export scripts."""
    try:
        meta = await asyncio.to_thread(render.preview, name, body.doc, body.style, body.cite)
    except (render.RenderError, FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc
    return _rendered_view(name, body, meta)


@app.get("/api/runs/{name}/rendered")
def rendered_file(
    name: str, style: str, cite: bool, path: str, download: bool = False
) -> FileResponse:
    try:
        target = render.preview_file(name, style, cite, path)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc
    if download:
        return FileResponse(target, filename=f"{name}-{style}-{target.name}")
    # The path stays the same across rebuilds, so the browser must not reuse an old copy.
    return FileResponse(target, headers={"Cache-Control": "no-store"})


@app.post("/api/runs/{name}/export")
async def export_run(name: str, body: RenderBody) -> dict[str, Any]:
    """Write HTML and/or PDF into <run>/export/<style>/ and check nothing was lost."""
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this run. Export when its turn finishes.")
    formats = [f for f in body.formats if f in ("html", "pdf")] or ["html"]
    try:
        return await asyncio.to_thread(
            render.export, name, body.doc, body.style, body.cite, formats
        )
    except (render.RenderError, FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc


class FiguresBody(BaseModel):
    style: str
    cite: bool = True
    names: list[str] = []
    kinds: list[str] = ["png", "svg"]


@app.post("/api/runs/{name}/figures/save")
def save_figures(name: str, body: FiguresBody) -> dict[str, Any]:
    try:
        saved = render.save_figures(name, body.style, body.cite, body.names, body.kinds)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc
    return {"saved": saved}


@app.post("/api/reveal")
def reveal(body: dict[str, str]) -> dict[str, Any]:
    """Show a file under outputs/ in Finder."""
    target = (config.ROOT / str(body.get("path", ""))).resolve()
    if config.OUTPUTS.resolve() not in target.parents or not target.exists():
        raise HTTPException(400, "not a file under outputs/")
    subprocess.Popen(["open", "-R", str(target)], start_new_session=True)
    return {"ok": True}


def _code_binary() -> str | None:
    return config.binary("code") or next(
        (
            p
            for p in (
                "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
                "/usr/local/bin/code",
            )
            if Path(p).exists()
        ),
        None,
    )


@app.post("/api/runs/{name}/vscode")
def open_vscode(name: str) -> dict[str, Any]:
    path = workspace.run_dir(name)
    code = _code_binary()
    if code:
        subprocess.Popen([code, str(path)], start_new_session=True, env=config.child_env())
    else:
        subprocess.Popen(["open", "-a", "Visual Studio Code", str(path)], start_new_session=True)
    return {"ok": True}


@app.post("/api/runs/{name}/reveal")
def reveal_run(name: str) -> dict[str, Any]:
    subprocess.Popen(["open", "-R", str(workspace.run_dir(name))], start_new_session=True)
    return {"ok": True}


@app.get("/api/exports")
def exports() -> list[dict[str, Any]]:
    return workspace.list_exports()


class PathBody(BaseModel):
    path: str


@app.post("/api/exports/open")
def open_export(body: PathBody) -> dict[str, Any]:
    try:
        target = workspace.export_path(body.path)
    except ValueError as exc:
        raise _bad(exc) from exc
    subprocess.Popen(["open", str(target)], start_new_session=True)
    return {"ok": True}


@app.post("/api/exports/reveal")
def reveal_export(body: PathBody) -> dict[str, Any]:
    try:
        target = workspace.export_path(body.path)
    except ValueError as exc:
        raise _bad(exc) from exc
    subprocess.Popen(["open", "-R", str(target)], start_new_session=True)
    return {"ok": True}


# ------------------------------------------------------------------ Workspace view


@app.get("/api/workspace/files")
def ws_files() -> list[dict[str, Any]]:
    return workspace.workspace_files()


@app.get("/api/workspace/file")
def ws_file(path: str) -> dict[str, Any]:
    try:
        target = workspace.editable(path)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {
        "path": path,
        "content": target.read_text(errors="replace") if target.exists() else "",
        "exists": target.exists(),
    }


class DiffBody(BaseModel):
    path: str
    content: str


@app.post("/api/workspace/diff")
def ws_diff(body: DiffBody) -> dict[str, Any]:
    try:
        workspace.editable(body.path)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {
        "diff": workspace.diff(body.path, body.content),
        "problems": workspace.check(body.path, body.content),
    }


class SaveBody(BaseModel):
    path: str
    content: str
    message: str = ""


@app.post("/api/workspace/save")
async def ws_save(body: SaveBody) -> dict[str, Any]:
    if manager.any_running():
        raise HTTPException(
            409, "A turn is running and may be reading this file. Save when it finishes."
        )
    try:
        result = await asyncio.to_thread(workspace.save, body.path, body.content, body.message)
    except ValueError as exc:
        raise _bad(exc) from exc
    if result["ok"]:
        result["stale_sessions"] = sessions.mark_stale_after(time.time())
    return result


class NewFileBody(BaseModel):
    kind: str
    name: str
    description: str = ""


@app.post("/api/workspace/new")
def ws_new(body: NewFileBody) -> dict[str, Any]:
    if body.kind not in workspace.TEMPLATES:
        raise HTTPException(400, "Choose skill, command or agent.")
    try:
        rel, text = workspace.new_file(body.kind, body.name, body.description)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"path": rel, "content": text}


@app.get("/api/workspace/history")
def ws_history(path: str) -> list[dict[str, str]]:
    try:
        return workspace.history(path)
    except ValueError as exc:
        raise _bad(exc) from exc


@app.get("/api/workspace/commit", response_class=PlainTextResponse)
def ws_commit(path: str, rev: str) -> str:
    try:
        workspace.editable(path)
        return workspace.show_commit(path, rev)
    except ValueError as exc:
        raise _bad(exc) from exc


class RestoreBody(BaseModel):
    path: str
    rev: str


@app.post("/api/workspace/restore")
async def ws_restore(body: RestoreBody) -> dict[str, Any]:
    if manager.any_running():
        raise HTTPException(409, "A turn is running. Restore when it finishes.")
    try:
        workspace.editable(body.path)
        result = await asyncio.to_thread(workspace.restore, body.path, body.rev)
    except ValueError as exc:
        raise _bad(exc) from exc
    if result["ok"]:
        result["stale_sessions"] = sessions.mark_stale_after(time.time())
    return result


class ImproveBody(BaseModel):
    path: str
    request: str


@app.post("/api/workspace/improve")
async def ws_improve(body: ImproveBody) -> dict[str, Any]:
    try:
        return await manager.improve(body.path, body.request)
    except (ValueError, ProviderError) as exc:
        raise _bad(exc) from exc


# ------------------------------------------------------------------ Claude Code sessions from VS Code


def _vscode_dir() -> Path:
    return Path.home() / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(config.ROOT))


def _vscode_rows(path: Path, limit: int | None = None) -> list[tuple[str, str]]:
    """(role, text) pairs of a Claude Code transcript, main thread only."""
    out: list[tuple[str, str]] = []
    with contextlib.suppress(OSError), path.open(errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("isSidechain") or row.get("type") not in ("user", "assistant"):
                continue
            content = (row.get("message") or {}).get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "\n".join(
                    str(b.get("text"))
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            else:
                continue
            if text.strip() and not text.startswith(
                ("<command-", "<local-command", "<system-reminder")
            ):
                out.append((str(row["type"]), text))
                if limit and len(out) >= limit:
                    break
    return out


@app.get("/api/vscode-sessions")
def vscode_sessions() -> list[dict[str, Any]]:
    base = _vscode_dir()
    if not base.is_dir():
        return []
    files = sorted(base.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]
    out = []
    for f in files:
        first = next((t for r, t in _vscode_rows(f, 6) if r == "user"), "")
        out.append(
            {
                "id": f.stem,
                "title": sessions.title_from(first) if first else f.stem[:8],
                "mtime": f.stat().st_mtime,
            }
        )
    return out


@app.post("/api/vscode-sessions/{native}/import")
def import_vscode(native: str) -> dict[str, Any]:
    if not re.match(r"^[0-9a-f-]{36}$", native):
        raise HTTPException(400, "bad session id")
    path = _vscode_dir() / f"{native}.jsonl"
    if not path.is_file():
        raise HTTPException(404, "not found")
    rows = _vscode_rows(path)
    first = next((t for r, t in rows if r == "user"), "Claude Code session")
    session = sessions.create(sessions.title_from(first))
    session.imported_from = native
    seg = sessions.Segment(provider="claude-sub", native_session_id=native)
    conf = config.load_settings()["connections"].get("claude-sub", {})
    seg.model, seg.effort = conf.get("model", ""), conf.get("effort", "")
    session.segments.append(seg)
    session.runs = sorted(
        {r for _, t in rows for r in workspace.runs_in(t) if (config.OUTPUTS / r).is_dir()}
    )
    sessions.save(session)
    for role, text in rows:
        sessions.append(
            session.id,
            Event(
                type="user" if role == "user" else "assistant_text",
                data={"text": text},
                provider="claude-sub",
            ),
        )
    return sessions.payload(session)


# ------------------------------------------------------------------ the live socket


@app.websocket("/api/ws/session")
async def ws_session(ws: WebSocket) -> None:
    if ws.query_params.get("token") != config.TOKEN or not _host_ok(ws.headers.get("host")):
        await ws.close(code=4401)
        return
    await ws.accept()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    manager.hub.everyone.add(queue)

    async def pump() -> None:
        while True:
            await ws.send_json(await queue.get())

    sender = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive_json()
            await _handle(ws, msg)
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        manager.hub.everyone.discard(queue)


async def _handle(ws: WebSocket, msg: dict[str, Any]) -> None:
    kind = msg.get("type")
    sid = str(msg.get("session") or "")
    try:
        if kind == "send":
            await manager.send(sid, str(msg.get("text") or ""), msg.get("connection") or None)
        elif kind == "stop":
            await manager.stop(sid)
        elif kind == "permission":
            answers = msg.get("answers")
            await manager.answer(
                sid,
                str(msg.get("id")),
                str(msg.get("decision")),
                {str(k): str(v) for k, v in answers.items()} if isinstance(answers, dict) else None,
            )
        elif kind == "switch":
            await manager.switch(
                sid,
                str(msg.get("connection")),
                msg.get("pending") or None,
                str(msg.get("reason") or "switch"),
            )
        elif kind == "ping":
            await ws.send_json({"type": "pong"})
    except (ProviderError, FileNotFoundError, ValueError) as exc:
        await ws.send_json({"type": "error", "session": sid, "text": str(exc)})


# ------------------------------------------------------------------ the front end


if (config.WEB_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=config.WEB_DIST, html=True), name="web")
else:

    @app.get("/", response_class=PlainTextResponse)
    def no_frontend() -> str:
        return "The front end is not built. Run `npm run build` in app/web, or use scripts/dev.sh."
