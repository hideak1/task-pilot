"""Launcher: bootstrap or attach to the task-pilot tmux session."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from task_pilot import tmux

SESSION_NAME = "task-pilot"
PLACEHOLDER_RIGHT = "echo 'Press n in the left pane to create a new Claude Code session'"


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def pre_flight_checks() -> None:
    """Verify required external binaries are present, exit otherwise."""
    if not shutil.which("tmux"):
        die("tmux is not installed. Install via your package manager.")
    if not shutil.which("claude"):
        die("claude CLI not found in PATH. Install Claude Code first.")


def get_outer_tmux_session() -> str | None:
    """If we're inside tmux, return the outer session name; else None."""
    if not os.environ.get("TMUX"):
        return None
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


def bootstrap_tmux_session() -> None:
    """Create the task-pilot tmux session from scratch."""
    tmux.new_session(SESSION_NAME, window_name="main", width=200, height=50)
    tmux.set_option(SESSION_NAME, "mouse", "on")
    tmux.set_option(SESSION_NAME, "status", "off", global_opt=True)
    # Disable mouse-wheel copy-mode trap (spec lines 452-461)
    tmux.unbind_key("root", "WheelUpPane")
    tmux.unbind_key("root", "WheelDownPane")
    tmux.split_window(f"{SESSION_NAME}:main", percent=70, horizontal=True)
    tmux.send_keys(f"{SESSION_NAME}:main.0",
                   "exec python -m task_pilot.textual_app --watchdog")
    tmux.send_keys(f"{SESSION_NAME}:main.1", PLACEHOLDER_RIGHT)


def main() -> None:
    """Entry point: ensure pilot's tmux session is running and attach to it."""
    pre_flight_checks()

    outer = get_outer_tmux_session()

    if outer == SESSION_NAME:
        print("Already inside task-pilot session. Phase 1 placeholder.")
        return

    if outer is not None:
        if tmux.has_session(SESSION_NAME):
            print(f"You are inside tmux session '{outer}'.")
            print(f"To switch:  tmux switch-client -t {SESSION_NAME}")
            print(f"Or detach (Ctrl-b d), then re-run task-pilot ui")
        else:
            print(f"You are inside tmux session '{outer}'.")
            print(f"Detach first (Ctrl-b d), then run task-pilot ui")
        sys.exit(1)

    if not tmux.has_session(SESSION_NAME):
        bootstrap_tmux_session()
    os.execvp("tmux", ["tmux", "attach", "-t", SESSION_NAME])


def cmd_kill() -> None:
    """`task-pilot kill` — tear down the entire tmux session."""
    if tmux.has_session(SESSION_NAME):
        tmux.kill_session(SESSION_NAME)
        print(f"Killed tmux session '{SESSION_NAME}'.")
    else:
        print(f"No tmux session named '{SESSION_NAME}'.")
