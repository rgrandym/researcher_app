"""Start the Research app: one backend, opened as a Chrome app window.

    python3 app/mac/launcher.py            # what Research.app runs
    python3 app/mac/launcher.py --browser  # a tab in the default browser instead

1. A backend from this app already running (port file in app/data/) gets a new window;
   no second backend starts.
2. Otherwise uvicorn starts on 127.0.0.1 on a free port with a fresh token, and the
   window opens once /api/health answers. The window is Chrome in app mode with its own
   profile in app/data/chrome/, so it has no tabs or address bar and leaves your usual
   Chrome profile alone. Without Chrome it opens in the default browser.
3. The backend counts open windows. When none has been open for 20 seconds, the
   launcher stops the backend, unless a turn is running: then it asks whether to stop
   it or leave it running in the background.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
DATA = APP / "data"
PORT_FILE = DATA / "app.json"
LOG = DATA / "backend.log"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
IDLE_S = 20


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _health(port: int) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as res:
            data = json.loads(res.read())
            return data if isinstance(data, dict) and data.get("app") == "research" else None
    except (OSError, ValueError):
        return None


def running_backend() -> dict[str, object] | None:
    try:
        info = json.loads(PORT_FILE.read_text())
    except (OSError, ValueError):
        return None
    if _alive(int(info.get("pid", 0))) and _health(int(info.get("port", 0))):
        return dict(info)
    PORT_FILE.unlink(missing_ok=True)
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_backend() -> dict[str, object]:
    DATA.mkdir(parents=True, exist_ok=True)
    port, token = free_port(), secrets.token_urlsafe(24)
    env = {**os.environ, "RESEARCH_APP_TOKEN": token}
    log = LOG.open("a")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=APP,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # survives the launcher when the author keeps it running
    )
    info: dict[str, object] = {
        "port": port,
        "pid": proc.pid,
        "token": token,
        "started": time.time(),
    }
    for _ in range(120):
        if proc.poll() is not None:
            sys.exit(f"The backend exited at start. See {LOG}.")
        if _health(port):
            PORT_FILE.write_text(json.dumps(info))
            PORT_FILE.chmod(0o600)
            return info
        time.sleep(0.25)
    proc.kill()
    sys.exit(f"The backend did not answer within 30 s. See {LOG}.")


def stop_backend(info: dict[str, object]) -> None:
    try:
        os.killpg(int(str(info["pid"])), signal.SIGTERM)
    except OSError:
        pass
    PORT_FILE.unlink(missing_ok=True)


def open_window(url: str, browser: bool) -> subprocess.Popen[bytes] | None:
    """A Chrome app window on its own profile; the default browser when Chrome is absent."""
    if CHROME.exists() and not browser:
        return subprocess.Popen(
            [
                str(CHROME),
                f"--app={url}",
                f"--user-data-dir={DATA / 'chrome'}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1400,900",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    webbrowser.open(url)
    return None


def ask_keep_running() -> bool:
    script = (
        'display dialog "A turn is still running. Keep it running in the background, or stop it?" '
        'buttons {"Stop it", "Keep running"} default button "Keep running" with title "Research"'
    )
    out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return "Keep running" in out.stdout


def watch(info: dict[str, object], chrome: subprocess.Popen[bytes] | None) -> None:
    """Stop the backend once no window has been connected for IDLE_S seconds."""
    port = int(str(info["port"]))
    seen, idle_since = False, None
    while True:
        time.sleep(2)
        health = _health(port)
        if health is None:
            return  # the backend went away by itself
        if int(str(health.get("clients", 0))) > 0:
            seen, idle_since = True, None
            continue
        if not seen:
            continue
        idle_since = idle_since or time.time()
        if time.time() - idle_since < IDLE_S:
            continue
        if health.get("running") and ask_keep_running():
            break
        stop_backend(info)
        break
    if chrome and chrome.poll() is None:
        chrome.terminate()  # Chrome keeps running after its last window closes on macOS
    subprocess.run(["pkill", "-f", f"user-data-dir={DATA / 'chrome'}"], capture_output=True)


def status() -> str:
    """ "turn" while an agent turn runs, "up" while the app runs, "down" otherwise. The
    Dock app polls this to know when to quit, and to ask before stopping a turn."""
    try:
        starting = _alive(int((DATA / "start.pid").read_text().strip() or 0))
    except (OSError, ValueError):
        starting = False
    info = running_backend()
    if info is None:
        return "up" if starting else "down"
    health = _health(int(str(info["port"]))) or {}
    return "turn" if health.get("running") else "up"


def stop_all() -> None:
    """Stop the backend, the launcher watching it, and the app's Chrome window."""
    info = running_backend()
    if info:
        stop_backend(info)
    try:
        os.kill(int((DATA / "start.pid").read_text().strip()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    subprocess.run(["pkill", "-f", f"user-data-dir={DATA / 'chrome'}"], capture_output=True)


def main() -> None:
    if "--status" in sys.argv:
        print(status())
        return
    if "--stop" in sys.argv:
        stop_all()
        return
    existing = running_backend()
    info = existing or start_backend()
    url = f"http://127.0.0.1:{info['port']}/?token={info['token']}"
    chrome = open_window(url, "--browser" in sys.argv)
    if existing:
        return  # the launcher that started this backend is already watching it
    try:
        watch(info, chrome)
    except KeyboardInterrupt:
        stop_backend(info)


if __name__ == "__main__":
    main()
