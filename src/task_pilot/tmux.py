"""Thin wrapper around the tmux CLI.

All functions assume a tmux binary is available in PATH. The launcher
should run shutil.which("tmux") before calling anything here.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Iterable

logger = logging.getLogger(__name__)


def run(args: Iterable[str], check: bool = False) -> subprocess.CompletedProcess:
    """Run `tmux <args>` and return the CompletedProcess.

    With check=False (default), failures are returned to the caller; with
    check=True, raises CalledProcessError on non-zero exit.
    """
    cmd = ["tmux", *args]
    logger.debug("tmux %s", " ".join(args))
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def has_session(session: str) -> bool:
    """Return True iff a tmux session with the given name exists."""
    return run(["has-session", "-t", session]).returncode == 0


def list_windows(session: str) -> list[str]:
    """Return a list of window names for the given tmux session."""
    result = run(["list-windows", "-t", session, "-F", "#{window_name}"])
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.strip().splitlines() if line]


def window_exists(session: str, window: str) -> bool:
    """Return True iff a window with the given name exists in the session."""
    return window in list_windows(session)


def new_session(name: str, window_name: str = "main", width: int = 200, height: int = 50) -> None:
    """Create a new detached tmux session."""
    run(["new-session", "-d", "-s", name, "-n", window_name, "-x", str(width), "-y", str(height)], check=True)


def kill_session(name: str) -> None:
    """Kill an entire tmux session and all its windows."""
    run(["kill-session", "-t", name])


def split_window(target: str, percent: int = 70, horizontal: bool = True) -> None:
    """Split a window. -h means horizontal split (left/right), -v vertical (top/bottom)."""
    flag = "-h" if horizontal else "-v"
    run(["split-window", flag, "-t", target, "-l", f"{percent}%"], check=True)


def send_keys(target: str, text: str, enter: bool = True) -> None:
    """Send text to the target pane. If enter=True, also send the Enter key."""
    args = ["send-keys", "-t", target, text]
    if enter:
        args.append("Enter")
    run(args, check=True)


def new_window(session: str, name: str, cwd: str, command: str) -> None:
    """Create a new background window running the given command in cwd."""
    run(["new-window", "-d", "-t", session, "-n", name, "-c", cwd, command], check=True)


def kill_window(target: str) -> None:
    """Kill a single window. Other windows in the session are unaffected."""
    run(["kill-window", "-t", target])


def swap_pane(src: str, dst: str) -> None:
    """Swap two panes. Each child process stays alive in its new location."""
    run(["swap-pane", "-s", src, "-t", dst], check=True)


def set_option(session: str, option: str, value: str, global_opt: bool = False) -> None:
    """Set a tmux option on the given session."""
    args = ["set"]
    if global_opt:
        args.append("-g")
    args.extend(["-t", session, option, value])
    run(args, check=True)


def display_message(target: str, format_string: str) -> str:
    """Run `tmux display-message -p -t <target> <format>` and return the output."""
    result = run(["display-message", "-p", "-t", target, format_string])
    return result.stdout.strip() if result.returncode == 0 else ""


def unbind_key(table: str, key: str) -> None:
    """Unbind a key in the given key table (`root`, `prefix`, etc.)."""
    run(["unbind-key", "-T", table, key], check=True)
