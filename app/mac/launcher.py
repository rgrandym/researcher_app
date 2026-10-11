"""Start the Research app: one backend, opened as a Chrome app window.

    python3 app/mac/launcher.py            # the Chrome version (any system with Chrome)
    python3 app/mac/launcher.py --browser  # a tab in the default browser instead
    python3 app/mac/launcher.py --serve    # what Research.app runs: start the backend (or
                                           # keep the running one), print its URL, exit
    python3 app/mac/launcher.py --window-pid  # the open app window's Chrome pid, or nothing
    python3 app/mac/launcher.py --raise       # bring the open window to the front; prints
                                              # "raised", or nothing when no window is open

1. A backend from this app already running (port file in app/data/) gets a new window;
   no second backend starts.
2. Otherwise uvicorn starts on 127.0.0.1 on a free port with a fresh token, and the
   window opens once /api/health answers. The window is Chrome in app mode with its own
   profile in app/data/chrome/, so it has no tabs or address bar and leaves your usual
   Chrome profile alone. Without Chrome it opens in the default browser.
3. The backend counts open windows. When none has been open for 20 seconds, the
   launcher stops the backend, unless a turn is running: then it asks whether to stop
   it or leave it running in the background.

With --serve, the Mac app (main.swift) shows the window itself and stops the backend when
it quits; the backend still stops itself once no window is connected (RESEARCH_EXIT_WHEN_IDLE).
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
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
IDLE_S = 20


def find_chrome() -> Path:
    """Chrome (or Chromium) on macOS, Linux or Windows; a path that does not exist if none."""
    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if sys.platform == "darwin":
        return mac
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for base in (
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ):
        exe = Path(base or "-") / "Google" / "Chrome" / "Application" / "chrome.exe"
        if exe.exists():
            return exe
    return mac


CHROME = find_chrome()


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
    # RESEARCH_EXIT_WHEN_IDLE: the backend stops itself once no window has been connected
    # for 30 s and no turn runs, so closing the app closes it even without this launcher.
    env = {**os.environ, "RESEARCH_APP_TOKEN": token, "RESEARCH_EXIT_WHEN_IDLE": "1"}
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
        "launcher": os.getpid(),  # the launcher watching it; a later launch may stop it
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


def reset_zoom() -> None:
    """Clear the browser zoom kept for the app's address in its Chrome profile. The app sizes
    itself to the window (index.css); a zoom set on one screen, carried to another, shrinks
    the room the layout has and squeezes it. Only while no app window runs, since Chrome
    rewrites its preferences when it quits."""
    if window_chrome_pid():
        return
    prefs = DATA / "chrome" / "Default" / "Preferences"
    try:
        data = json.loads(prefs.read_text())
        levels = data.get("partition", {}).get("per_host_zoom_levels", {})
        changed = False
        for hosts in levels.values():
            for host in ("127.0.0.1", "localhost"):
                changed |= hosts.pop(host, None) is not None
        if changed:
            prefs.write_text(json.dumps(data))
    except (OSError, ValueError, AttributeError):
        pass


def open_window(url: str, browser: bool) -> subprocess.Popen[bytes] | None:
    """A Chrome app window on its own profile; the default browser when Chrome is absent."""
    if CHROME.exists() and not browser:
        reset_zoom()
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
            # The backend restarts itself in place to load new code (POST /api/restart):
            # give it time to come back before treating it as gone.
            for _ in range(15):
                time.sleep(1)
                health = _health(port)
                if health is not None:
                    break
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


def window_pid() -> str:
    """The pid of the Chrome process showing the app, when a window is open: the Dock app
    brings that window to the front instead of opening another. Empty when none is open."""
    info = running_backend()
    if info is None or int(str((_health(int(str(info["port"]))) or {}).get("clients", 0))) < 1:
        return ""
    return window_chrome_pid()


def window_chrome_pid() -> str:
    """The pid of the Chrome browser process running on the app's own profile, or empty."""
    ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    marker = f"user-data-dir={DATA / 'chrome'}"
    for line in ps.splitlines():
        pid, _, command = line.strip().partition(" ")
        # The browser process itself; its helpers carry a --type= flag.
        if marker in command and "--type=" not in command and command.startswith(str(CHROME)):
            return pid
    return ""


def raise_window() -> str:
    """Bring the open app window in front of other apps, as a Dock click does for any app
    (the Dock app un-minimises it first). Raised twice: now, and once more just after,
    because the Dock activates Research itself after the click and could take the front
    back. Activation only: nothing here can open a window."""
    pid = window_pid()
    if not pid:
        return ""
    script = str(APP / "mac" / "raise.js")
    subprocess.run(["osascript", "-l", "JavaScript", script, pid], capture_output=True, timeout=10)
    subprocess.Popen(
        ["/bin/sh", "-c", f'sleep 0.4; osascript -l JavaScript "{script}" {pid}'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return "raised"


def stop_previous(info: dict[str, object]) -> None:
    """Stop an idle backend left from an earlier launch, and the launcher watching it."""
    me = os.getpid()
    ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    for line in ps.splitlines():
        pid, _, command = line.strip().partition(" ")
        if "mac/launcher.py" in command and "--" not in command.split("launcher.py", 1)[1] and int(pid) != me:
            with contextlib.suppress(OSError):
                os.kill(int(pid), signal.SIGTERM)
    stop_backend(info)
    for _ in range(20):
        if not _alive(int(str(info["pid"]))):
            break
        time.sleep(0.25)


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
    if "--window-pid" in sys.argv:
        print(window_pid())
        return
    if "--raise" in sys.argv:
        print(raise_window())
        return
    if "--serve" in sys.argv:
        # The Mac app's window attaches to a running backend (perhaps one kept running for a
        # turn when the app last quit), or to a new one.
        info = running_backend() or start_backend()
        print(f"http://127.0.0.1:{info['port']}/?token={info['token']}")
        # start.sh's pid file names this process; once it exits the pid may be reused.
        with contextlib.suppress(OSError, ValueError):
            if int((DATA / "start.pid").read_text().strip()) == os.getpid():
                (DATA / "start.pid").unlink()
        return
    existing = running_backend()
    if existing:
        if raise_window():
            return  # a window is open: bring it forward, never open a second one
        # No window: the app was closed and this backend outlived it. Never reuse it: stop it
        # and its launcher (whose clean-up would otherwise close the new window), and start
        # a backend with the current code.
        stop_previous(existing)
    info = start_backend()
    url = f"http://127.0.0.1:{info['port']}/?token={info['token']}"
    chrome = open_window(url, "--browser" in sys.argv)
    try:
        watch(info, chrome)
    except KeyboardInterrupt:
        stop_backend(info)


if __name__ == "__main__":
    main()
