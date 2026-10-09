"""API keys in the macOS Keychain, through the `security` tool that ships with macOS.

Keys never touch `app/data/` or the repository. Each connection stores one generic
password under the service name below, with the connection id as the account.
"""

from __future__ import annotations

import subprocess

SERVICE = "Research app"


def get(account: str) -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def put(account: str, secret: str) -> None:
    # -U updates an existing item. The secret goes in argv, which other local processes
    # of this user can see for the instant the command runs; `security` offers no stdin.
    out = subprocess.run(
        ["security", "add-generic-password", "-s", SERVICE, "-a", account, "-w", secret, "-U"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "Keychain refused the key")


def delete(account: str) -> None:
    subprocess.run(
        ["security", "delete-generic-password", "-s", SERVICE, "-a", account],
        capture_output=True,
        text=True,
        timeout=10,
    )


def has(account: str) -> bool:
    return get(account) is not None
