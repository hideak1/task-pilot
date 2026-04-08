"""3-line row widget for the session list."""

from __future__ import annotations

import os
import time
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from task_pilot.models import Session, SessionState

STATUS_ICONS = {
    "initializing": "[#8b8fa3]…[/]",
    "working":      "[#69db7c]●[/]",
    "idle":         "[#ffd43b]◐[/]",
    "unknown":      "[#ff6b6b]?[/]",
}


def format_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


def format_tokens(n: int) -> str:
    if n >= 1000:
        if n % 1000 == 0:
            return f"{n // 1000}k tok"
        return f"{n / 1000:.1f}k tok"
    return f"{n} tok"


def abbrev_home(path: str) -> str:
    home = os.environ.get("HOME", "")
    if home and path.startswith(home):
        return "~" + path[len(home):]
    return path


class SessionRow(Widget, can_focus=True):
    """A 3-line row showing one session."""

    class Selected(Message):
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    DEFAULT_CSS = """
    SessionRow {
        height: 4;
        padding: 0 1;
        background: #111318;
        border-bottom: solid #181b22;
    }
    SessionRow.selected {
        background: #181b22;
        border-left: thick #74c0fc;
    }
    SessionRow .row-title {
        color: #e2e4e9;
    }
    SessionRow .row-meta {
        color: #555869;
    }
    """

    def __init__(self, session: Session, state: SessionState, selected: bool = False) -> None:
        super().__init__()
        self.session_data = session
        self.session_state = state
        if selected:
            self.add_class("selected")

    def compose(self) -> ComposeResult:
        title = self.session_data.title or "New session"
        if len(title) > 32:
            title = title[:29] + "..."
        icon = STATUS_ICONS.get(self.session_state.status, "?")
        line1 = f"{title}    {icon}"

        cwd = abbrev_home(self.session_data.cwd)
        if self.session_data.git_branch:
            line2 = f"{cwd} · {self.session_data.git_branch}"
        else:
            line2 = cwd

        elapsed = format_elapsed(time.time() - self.session_data.started_at)
        tokens = format_tokens(self.session_state.token_count)
        line3 = f"{elapsed} · {tokens}"

        yield Static(line1, classes="row-title")
        yield Static(line2, classes="row-meta")
        yield Static(line3, classes="row-meta")

    def on_click(self) -> None:
        self.post_message(self.Selected(self.session_data.id))
