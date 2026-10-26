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
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import accounts, activity, appearance, autoedits, comments, config, edit_state, final_sections, keychain, render, revision, sessions, usage, workspace
from backend.providers.base import Event, ProviderError
from backend.providers.claude import ClaudeProvider
from backend.turns import TurnManager

app = FastAPI(title="Research", docs_url=None, redoc_url=None)
manager = TurnManager()
watcher = autoedits.Watcher(manager)


@app.on_event("startup")
async def start_watcher() -> None:
    """Hand edits to a master start /user-edits by themselves (backend/autoedits.py)."""
    app.state.watcher_task = asyncio.create_task(watcher.loop())
    if os.environ.get("RESEARCH_EXIT_WHEN_IDLE") == "1":
        app.state.idle_task = asyncio.create_task(exit_when_idle())


async def exit_when_idle() -> None:
    """Stop this backend once no app window has been connected for a while and no turn is
    running: closing the app closes its backend, even if the launcher that started it is
    gone. Only backends the launcher starts set RESEARCH_EXIT_WHEN_IDLE (not dev.sh)."""
    grace = float(os.environ.get("RESEARCH_IDLE_EXIT_S", "30"))
    started = last_seen = time.time()
    while True:
        await asyncio.sleep(2)
        now = time.time()
        if manager.hub.everyone or manager.any_running():
            last_seen = now
            continue
        # A window that never connected (a failed launch) gets longer before the backend gives up.
        limit = grace if last_seen > started else max(grace, 120)
        if now - last_seen >= limit:
            print(f"No app window for {int(now - last_seen)} s and no turn running: stopping.", flush=True)
            os.kill(os.getpid(), signal.SIGTERM)
            return
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
    # has been zero for a while. `stale`: the backend's code changed after it started, so
    # the window may call what this process does not have yet; the header offers Restart.
    return {
        "ok": True,
        "app": "research",
        "running": manager.any_running(),
        "clients": len(manager.hub.everyone),
        "stale": _code_stamp() > CODE_STAMP,
    }


def _code_stamp() -> float:
    """The newest modification time among the backend's own Python files."""
    base = Path(__file__).resolve().parent
    return max((p.stat().st_mtime for p in base.rglob("*.py")), default=0.0)


CODE_STAMP = _code_stamp()


@app.post("/api/restart")
async def restart() -> dict[str, Any]:
    """Restart this backend in place to load changed code: same process id, port, token and
    arguments, so the launcher keeps watching it and the window reconnects by itself.
    Refused while a turn runs, since the restart would cut it off."""
    if manager.any_running():
        raise HTTPException(409, "A turn is running. Restart when it finishes.")

    def again() -> None:
        os.execv(sys.executable, [sys.executable, "-m", "uvicorn", *sys.argv[1:]])

    asyncio.get_running_loop().call_later(0.4, again)
    return {"ok": True}


@app.post("/api/stop-all")
async def stop_all_turns() -> dict[str, Any]:
    """Stop all active turns while leaving the app available to inspect their results."""
    return {"stopping": await manager.stop_all()}


@app.get("/api/commands")
def commands() -> list[dict[str, str]]:
    hidden = set(config.load_settings().get("hidden_commands") or [])
    # The app's own command: a message without a command is a read-only question (turns.py).
    own = [
        {
            "name": "continue",
            "description": "Resume the work in progress (the last command's task) with your reply. "
            "A message without a command is answered as a quick, read-only question.",
            "kind": "app",
            "path": "",
        },
        {
            "name": "do",
            "description": "Carry out a one-off task that no other command covers (make a style, "
            "fix a table header), with every tool, on the chat model.",
            "kind": "app",
            "path": "",
        },
    ]
    return sorted([*(c for c in workspace.commands() if c["name"] not in hidden), *own], key=lambda c: c["name"])


@app.get("/api/guide", response_class=PlainTextResponse)
def guide() -> str:
    return workspace.guide()


# ------------------------------------------------------------------ connections and settings


def _status(conn: str, fresh: bool = False) -> dict[str, Any]:
    hit = _status_cache.get(conn)
    if hit and not fresh and time.time() - hit[0] < 30:
        return hit[1]
    provider = manager.provider(conn)
    st = (provider.status(fresh=fresh) if isinstance(provider, ClaudeProvider)
          else provider.status()).model_dump()
    _status_cache[conn] = (time.time(), st)
    return st


@app.get("/api/connections")
async def connections(fresh: bool = False) -> list[dict[str, Any]]:
    out = []
    manager.sync_accounts()
    for conn in config.connection_ids():
        st = await asyncio.to_thread(_status, conn, fresh)
        u = await asyncio.to_thread(manager.provider(conn).usage)
        out.append({**st, "usage": u.model_dump() if u else None})
    by_email: dict[str, list[dict[str, Any]]] = {}
    for item in out:
        if item["runtime"] == "claude" and item["billing"] == "plan" and item.get("account"):
            by_email.setdefault(str(item["account"]).strip().casefold(), []).append(item)
    for matches in by_email.values():
        if len(matches) < 2:
            continue
        names = ", ".join(str(item["label"]) for item in matches)
        first = matches[0]
        first["message"] += f" Another connection uses this same account: {names}."
        for item in matches[1:]:
            item["signed_in"] = False
            item["message"] = (
                f"Duplicate Claude sign-in: {names} use {item['account']}. "
                "Sign this connection out and sign in with its intended account."
            )
    return out


@app.get("/api/usage/{conn}")
async def connection_usage(conn: str) -> dict[str, Any]:
    try:
        provider = manager.provider(conn)
        u = await asyncio.to_thread(provider.usage, refresh_local=True) if isinstance(provider, ClaudeProvider) else await asyncio.to_thread(provider.usage)
    except ProviderError as exc:
        raise _bad(exc, 404) from exc
    return u.model_dump() if u else {}


class LoginBody(BaseModel):
    email: str = ""


@app.post("/api/connections/{conn}/login")
def login(conn: str, body: LoginBody | None = None) -> dict[str, Any]:
    provider = manager.provider(conn)
    if getattr(provider, "billing", "") == "key":
        raise HTTPException(400, "This connection uses an API key; add one instead.")
    email = body.email.strip() if body else getattr(provider, "email", "")
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(400, "Enter a valid email address.")
    try:
        if isinstance(provider, ClaudeProvider):
            provider.start_login(email)
            accounts.set_expected_email(conn, email)
            manager.sync_accounts()
        else:
            provider.start_login()  # type: ignore[attr-defined]
    except ProviderError as exc:
        raise _bad(exc) from exc
    _status_cache.pop(conn, None)
    return {
        "ok": True,
        "message": "The sign-in page opens in your browser. If it shows a different Claude "
        "account, sign out of claude.ai there first, then sign in again. The app will "
        "check the signed-in email against the one you entered. Refresh this card when done.",
    }


@app.post("/api/connections/{conn}/logout")
def logout(conn: str) -> dict[str, Any]:
    """Sign one Claude subscription out. Codex is shared with other apps and never signed
    out from here."""
    provider = manager.provider(conn)
    if not hasattr(provider, "logout") or getattr(provider, "billing", "") != "plan":
        raise HTTPException(400, "Only a Claude subscription signs out here.")
    try:
        provider.logout()  # type: ignore[attr-defined]
    except ProviderError as exc:
        raise _bad(exc) from exc
    _status_cache.pop(conn, None)
    return {"ok": True, "message": "Signed out. Sign in again to use this account."}


class AccountBody(BaseModel):
    label: str
    email: str = ""
    config_dir: str = ""


@app.post("/api/accounts")
def add_account(body: AccountBody) -> dict[str, Any]:
    """Add a Claude subscription account, with its own Claude Code config folder."""
    try:
        account = accounts.add(body.label, body.email, body.config_dir)
    except ProviderError as exc:
        raise _bad(exc) from exc
    manager.sync_accounts()
    return account


@app.delete("/api/accounts/{conn}")
def remove_account(conn: str) -> dict[str, Any]:
    """Sign an added account out and take it out of the app; its folder stays on disk."""
    if any(manager.runs_on(s, conn) for s in manager.running):
        raise HTTPException(409, "A turn is running on this account. Remove it when it finishes.")
    try:
        account = accounts.remove(conn)
    except ProviderError as exc:
        raise _bad(exc, 404) from exc
    manager.sync_accounts()
    _status_cache.pop(conn, None)
    return account


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
        pending = manager.running.get(sid)
        return activity.build(sid, manager.is_running(sid), manager.providers, set(pending.permissions) if pending else set())
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc


@app.post("/api/sessions/{sid}/retry")
async def retry_session(sid: str) -> dict[str, Any]:
    """Carry the last prompt on from the current task state."""
    try:
        await manager.retry(sid)
    except ProviderError as exc:
        raise _bad(exc, 409) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc
    return {"ok": True}


class ResumeLater(BaseModel):
    connection: str
    at: float | None = None


@app.post("/api/sessions/{sid}/resume-later")
def resume_later(sid: str, body: ResumeLater) -> dict[str, Any]:
    """Carry the task on with this connection when its usage window resets: at `at`, or the
    reset its usage reports, or the reset the last limit message named, or in an hour."""
    try:
        session = sessions.load(sid)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc
    at = body.at
    if at is None:
        try:
            u = manager.provider(body.connection).usage()
        except Exception:  # noqa: BLE001  usage is advisory
            u = None
        full = [w.resets_at for w in (u.windows if u else []) if (w.used_percent or 0) >= 100 and w.resets_at]
        last = next(
            (e.data.get("resets_at") or usage.reset_from_text(str(e.data.get("text") or ""))
             for e in reversed(sessions.transcript(sid)) if e.type == "error" and e.data.get("kind") == "limit"),
            None,
        )
        at = max(full) if full else last or time.time() + 3600
    session.resume_at, session.resume_connection = float(at) + 60, body.connection  # a minute's margin
    sessions.save(session)
    return {"resume_at": session.resume_at, "connection": body.connection}


@app.delete("/api/sessions/{sid}/resume-later")
def cancel_resume(sid: str) -> dict[str, Any]:
    session = sessions.load(sid)
    session.resume_at, session.resume_connection = None, None
    sessions.save(session)
    return {"ok": True}


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


class ApplyCritiqueBody(BaseModel):
    path: str = "critique.md"
    scope: str = "all"
    answers: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


def _critique_context(name: str, path: str) -> tuple[Path, Path, str, Path]:
    if not re.fullmatch(r"critique[\w-]*\.md", path):
        raise HTTPException(400, "Choose a critique file in this run.")
    try:
        run_path = workspace.run_dir(name)
        critique = workspace.run_file(name, path)
        primary = workspace.run_meta(run_path).get("primary")
        if not primary:
            raise ValueError("This run has no article to repair.")
        doc = workspace.run_file(name, primary)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc
    if not critique.read_text().strip():
        raise HTTPException(400, "The critique file is empty.")
    marker = run_path / ".critique-isolation-failed"
    if marker.exists() and critique.stat().st_mtime <= marker.stat().st_mtime:
        raise HTTPException(409, "This critique did not pass independent review. Rerun /critique first.")
    return run_path, critique, primary, doc


def _critique_questions(run_path: Path, critique: Path) -> list[dict[str, Any]]:
    question_file = run_path / f"{critique.stem}-questions.json"
    if not question_file.is_file() or question_file.stat().st_mtime < critique.stat().st_mtime:
        return []
    try:
        data = json.loads(question_file.read_text())
        raw = data.get("questions", [])
        if not isinstance(raw, list):
            return []
        questions = []
        for item in raw[:12]:
            if not isinstance(item, dict) or not item.get("id") or not item.get("question"):
                continue
            options = item.get("options", [])
            questions.append({
                "id": str(item["id"])[:80],
                "finding": str(item.get("finding", ""))[:200],
                "question": str(item["question"])[:600],
                "options": [
                    {"label": str(option.get("label", ""))[:100],
                     "description": str(option.get("description", ""))[:250]}
                    for option in options[:4] if isinstance(option, dict) and option.get("label")
                ] if isinstance(options, list) else [],
            })
        return questions
    except (OSError, ValueError, AttributeError):
        return []


@app.get("/api/runs/{name}/critique-questions")
def critique_questions(name: str, path: str = "critique.md") -> dict[str, Any]:
    run_path, critique, _, _ = _critique_context(name, path)
    return {"questions": _critique_questions(run_path, critique)}


@app.post("/api/runs/{name}/apply-critique")
async def apply_critique(name: str, body: ApplyCritiqueBody) -> dict[str, str]:
    """Start /repair only after the author has answered the critique questions."""
    run_path, critique, primary, doc = _critique_context(name, body.path)
    if body.scope not in {"all", "material", "specified"}:
        raise HTTPException(400, "Choose which findings to apply.")
    if body.scope == "specified" and not body.notes.strip():
        raise HTTPException(400, "Describe which findings to apply.")
    questions = _critique_questions(run_path, critique)
    missing = [question["id"] for question in questions if not body.answers.get(question["id"], "").strip()]
    if missing:
        raise HTTPException(400, "Answer every author question before starting repair.")
    if len(body.notes) > 10_000 or any(len(answer) > 2_000 for answer in body.answers.values()):
        raise HTTPException(400, "The feedback is too long; shorten it before submitting.")
    if edit_state.active(doc):
        raise HTTPException(409, "Absorb the latest saved author edits before applying critique feedback.")
    if _run_busy(name):
        raise HTTPException(409, "An agent is already working on this run.")
    session = sessions.for_project(name)
    if session is None:
        session = sessions.create(name)
        session.project = name
        session.runs = [name]
        sessions.save(session)
    decisions = run_path / f"repair-feedback-{time.time_ns()}.json"
    decisions.write_text(json.dumps({
        "critique": body.path,
        "scope": body.scope,
        "answers": {question["id"]: body.answers[question["id"]].strip() for question in questions},
        "notes": body.notes.strip(),
        "questions": questions,
    }, indent=2) + "\n")
    prompt = (
        f"/repair outputs/{name}/{body.path} Apply its findings to {primary}. "
        f"Read outputs/{name}/{decisions.name} first and follow the author's answers and scope. "
        "Respect final sections, ask about any unresolved author decision before editing it, "
        "and record every finding's disposition."
    )
    try:
        await manager.send(session.id, prompt)
    except ProviderError as exc:
        raise _bad(exc, 409) from exc
    return {"session": session.id}


@app.get("/api/runs/{name}/subjects")
def run_subjects(name: str) -> dict[str, Any]:
    try:
        return {"subjects": revision.subjects(name)}
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc


@app.get("/api/runs/{name}/changes/{slug}")
def run_changes(name: str, slug: str) -> dict[str, Any]:
    try:
        return revision.plan(name, slug)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404) from exc


class DecisionsBody(BaseModel):
    decisions: dict[str, dict[str, Any]] = Field(default_factory=dict)


@app.put("/api/runs/{name}/changes/{slug}/decisions")
def save_decisions(name: str, slug: str, body: DecisionsBody) -> dict[str, Any]:
    """The author's decisions on a change plan. Only the author writes them."""
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this project; decide once it has finished.")
    try:
        return revision.decide(name, slug, body.decisions)
    except FileNotFoundError as exc:
        raise _bad(exc, 404) from exc
    except ValueError as exc:
        raise _bad(exc, 400) from exc


@app.post("/api/runs/{name}/changes/{slug}/from-markdown")
def plan_from_markdown(name: str, slug: str) -> dict[str, Any]:
    """Rebuild a Word document's plan from revised.md, after the author edited it."""
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this project; update the plan once it has finished.")
    try:
        return revision.from_markdown(name, slug)
    except FileNotFoundError as exc:
        raise _bad(exc, 404) from exc
    except ValueError as exc:
        raise _bad(exc, 400) from exc


@app.post("/api/runs/{name}/documents/{slug}/diff")
def document_diff(name: str, slug: str) -> dict[str, Any]:
    """What a revised document's master changed against the original, as diff.md."""
    try:
        return revision.document_diff(name, slug)
    except FileNotFoundError as exc:
        raise _bad(exc, 404) from exc
    except ValueError as exc:
        raise _bad(exc, 400) from exc


class DocumentExportBody(BaseModel):
    formats: list[str] = ["docx", "pdf"]
    track: bool = False
    author: str = ""


@app.post("/api/runs/{name}/documents/{slug}/export")
async def document_export(name: str, slug: str, body: DocumentExportBody) -> dict[str, Any]:
    """Export a revised document to Word in the original's design, and PDF. A script, no turn."""
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this run. Export when its turn finishes.")
    try:
        return await asyncio.to_thread(revision.document_export, name, slug, body.formats, body.track, body.author)
    except FileNotFoundError as exc:
        raise _bad(exc, 404) from exc
    except ValueError as exc:
        raise _bad(exc, 400) from exc


class ApplyChangesBody(BaseModel):
    slug: str
    mode: str = "tracked"
    author: str = ""
    notes: str = ""


@app.post("/api/runs/{name}/apply-changes")
async def apply_changes(name: str, body: ApplyChangesBody) -> dict[str, str]:
    """Start /revise (or /rebuild for a PDF) on the accepted changes."""
    if body.mode not in {"tracked", "clean"}:
        raise HTTPException(400, "Choose tracked changes or a clean copy.")
    if _run_busy(name):
        raise HTTPException(409, "An agent is already working on this run.")
    try:
        _, prompt = revision.apply_request(name, body.slug, body.mode, body.author, body.notes)
    except FileNotFoundError as exc:
        raise _bad(exc, 404) from exc
    except ValueError as exc:
        raise _bad(exc, 400) from exc
    session = sessions.for_project(name)
    if session is None:
        session = sessions.create(name)
        session.project = name
        session.runs = [name]
        sessions.save(session)
    try:
        await manager.send(session.id, prompt)
    except ProviderError as exc:
        raise _bad(exc, 409) from exc
    return {"session": session.id}


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


@app.get("/api/runs/{name}/edits")
def hand_edits(name: str, doc: str | None = None) -> dict[str, Any]:
    """What the author changed by hand since the last agent write, for the Edit tab."""
    try:
        return autoedits.status(name, _doc(name, doc))
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404 if isinstance(exc, FileNotFoundError) else 400) from exc


class EditsBody(BaseModel):
    doc: str | None = None


@app.post("/api/runs/{name}/edits/keep")
async def keep_edits(name: str, body: EditsBody) -> dict[str, Any]:
    """Keep the author's edit as written: closed by script, no agent turn."""
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this run. Try when its turn finishes.")
    try:
        target = _doc(name, body.doc)
        result = await asyncio.to_thread(autoedits.keep, name, target)
        return {**result, "status": autoedits.status(name, target)}
    except autoedits.KeepRefused as exc:
        raise _bad(exc, 422) from exc
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired) as exc:
        raise _bad(exc) from exc


@app.post("/api/runs/{name}/edits/absorb")
async def absorb_edits(name: str, body: EditsBody) -> dict[str, Any]:
    """Start /user-edits on the author's edit, in the project's conversation."""
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this run. Try when its turn finishes.")
    try:
        master = workspace.run_file(name, _doc(name, body.doc))
        if not autoedits.status(name, master.name)["pending"]:
            raise ValueError("There is no unabsorbed edit to absorb.")
        session = await watcher.absorb(name, master, master.stat().st_mtime, asked=True)
    except ProviderError as exc:
        raise _bad(exc, 409) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc
    return {"session": session}


@app.get("/api/runs/{name}/final-sections")
def run_final_sections(name: str) -> list[dict[str, str | bool]]:
    try:
        doc = workspace.run_file(name, workspace.run_meta(workspace.run_dir(name))["primary"])
        return final_sections.sections(doc)
    except (FileNotFoundError, ValueError, KeyError, TypeError) as exc:
        raise _bad(exc, 404) from exc


class FinalSectionBody(BaseModel):
    heading: str
    final: bool


@app.put("/api/runs/{name}/final-sections")
def update_final_section(name: str, body: FinalSectionBody) -> dict[str, bool]:
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this run. Try when its turn finishes.")
    try:
        doc = workspace.run_file(name, workspace.run_meta(workspace.run_dir(name))["primary"])
        final_sections.set_final(doc, body.heading, body.final)
    except (FileNotFoundError, ValueError, KeyError, TypeError) as exc:
        raise _bad(exc) from exc
    return {"ok": True}


@app.put("/api/runs/{name}/file")
def save_run_file(name: str, body: RunFileBody) -> dict[str, Any]:
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this run. Save when its turn finishes.")
    try:
        run_path = workspace.run_dir(name)
        primary = workspace.run_meta(run_path).get("primary")
        if body.path == primary:
            doc = workspace.run_file(name, body.path)
            changed = final_sections.changed_final(doc, body.content)
            if changed:
                raise HTTPException(409, "Reopen final section before saving changes: " + ", ".join(changed))
        mtime = workspace.save_run_file(name, body.path, body.content, body.mtime)
    except workspace.Conflict as exc:
        raise _bad(exc, 409) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc
    return {"ok": True, "mtime": mtime}


class ExternalFileBody(BaseModel):
    path: str
    data: str  # base64


@app.post("/api/runs/{name}/external-data")
def import_external_file(name: str, body: ExternalFileBody) -> dict[str, Any]:
    try:
        path = workspace.import_external(name, body.path, body.data)
    except FileExistsError as exc:
        raise HTTPException(409, "A file with this name already exists. Rename the import first.") from exc
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc
    return {"path": path}


@app.delete("/api/runs/{name}/external-data")
def remove_external_file(name: str, path: str) -> dict[str, Any]:
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this project. Remove the file when its turn finishes.")
    try:
        trash = workspace.remove_external(name, path)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404 if isinstance(exc, FileNotFoundError) else 400) from exc
    return {"trash": trash}


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


@app.get("/api/runs/{name}/appearance")
def report_appearance(name: str, style: str = "meridian", doc: str | None = None) -> dict[str, Any]:
    try:
        return appearance.view(name, style, doc)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc


class AppearanceBody(BaseModel):
    style: str
    values: dict[str, Any]
    remember_default: bool = False
    doc: str | None = None


@app.put("/api/runs/{name}/appearance")
def save_report_appearance(name: str, body: AppearanceBody) -> dict[str, Any]:
    try:
        return appearance.save(name, body.style, body.values, body.remember_default, body.doc)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc


class TableCaptionBody(BaseModel):
    doc: str
    table: str
    title: str


@app.post("/api/runs/{name}/table-caption")
def add_table_caption(name: str, body: TableCaptionBody) -> dict[str, Any]:
    """The author's caption for an uncaptioned table, written into the document."""
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this run. Add the caption when its turn finishes.")
    try:
        return {"ok": True, "id": appearance.add_caption(name, body.doc, body.table, body.title)}
    except workspace.Conflict as exc:
        raise _bad(exc, 409) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc


@app.delete("/api/runs/{name}/appearance")
def reset_report_appearance(name: str) -> dict[str, bool]:
    try:
        appearance.reset(name)
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc
    return {"ok": True}


class RenderBody(BaseModel):
    doc: str | None = None
    style: str = "meridian"
    cite: bool = True
    formats: list[str] = []
    comments: bool = True


class LiveBody(BaseModel):
    doc: str | None = None
    style: str = "meridian"
    cite: bool = True
    content: str


def _rendered_view(name: str, body: RenderBody | LiveBody, meta: dict[str, Any]) -> dict[str, Any]:
    base = render.cache_dir(name, body.style, body.cite)

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
        "live": bool(meta.get("live")),
    }


@app.post("/api/runs/{name}/render")
async def render_run(name: str, body: RenderBody) -> dict[str, Any]:
    """HTML preview of the master in a style, by the workspace's export scripts."""
    try:
        meta = await asyncio.to_thread(render.preview, name, body.doc, body.style, body.cite)
    except (render.RenderError, FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc
    return _rendered_view(name, body, meta)


@app.post("/api/runs/{name}/render-live")
async def render_live(name: str, body: LiveBody) -> dict[str, Any]:
    """HTML of the editor's unsaved text, so a popped-out editor shows its changes here."""
    try:
        meta = await asyncio.to_thread(render.live, name, body.doc, body.style, body.cite, body.content)
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
    """Write HTML, PDF and/or Word into <run>/export/<style>/ and check nothing was lost."""
    if _run_busy(name):
        raise HTTPException(409, "An agent is working on this run. Export when its turn finishes.")
    formats = [f for f in body.formats if f in ("html", "pdf", "docx")] or ["html"]
    try:
        return await asyncio.to_thread(
            render.export, name, body.doc, body.style, body.cite, formats, body.comments
        )
    except (render.RenderError, FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc


def _doc(name: str, doc: str | None) -> str:
    folder = workspace.run_dir(name)
    found = doc or workspace.run_meta(folder).get("primary")
    if not found:
        raise FileNotFoundError("This run has no master document yet.")
    return str(found)


@app.get("/api/runs/{name}/comments")
def list_comments(name: str, doc: str | None = None) -> dict[str, Any]:
    try:
        target = _doc(name, doc)
        return {"doc": target, "comments": comments.listing(name, target)}
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc, 404 if isinstance(exc, FileNotFoundError) else 400) from exc


class CommentBody(BaseModel):
    doc: str | None = None
    text: str
    author: str = ""
    selection: dict[str, Any] | None = None
    element: dict[str, Any] | None = None
    highlight: bool = False
    color: str = "yellow"


@app.post("/api/runs/{name}/comments")
def add_comment(name: str, body: CommentBody) -> dict[str, Any]:
    try:
        return comments.create(
            name, _doc(name, body.doc), body.text, body.author, body.selection, body.element, body.highlight, body.color
        )
    except (FileNotFoundError, ValueError) as exc:
        raise _bad(exc) from exc


class CommentPatch(BaseModel):
    text: str | None = None
    resolved: bool | None = None
    color: str | None = None


@app.patch("/api/runs/{name}/comments/{cid}")
def edit_comment(name: str, cid: str, body: CommentPatch) -> dict[str, Any]:
    try:
        return comments.update(name, cid, body.text, body.resolved, body.color)
    except FileNotFoundError as exc:
        raise _bad(exc, 404) from exc
    except ValueError as exc:
        raise _bad(exc) from exc


@app.delete("/api/runs/{name}/comments/{cid}")
def remove_comment(name: str, cid: str) -> dict[str, bool]:
    try:
        comments.delete(name, cid)
    except FileNotFoundError as exc:
        raise _bad(exc, 404) from exc
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


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
