"""Card-style session row widget for the left panel."""

from __future__ import annotations

import os
import time

from textual.app import ComposeResult
from textual.containers import Horizontal
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

STATUS_LABELS = {
    "initializing": "[#8b8fa3]starting[/]",
    "working":      "[#69db7c]working[/]",
    "idle":         "[#ffd43b]idle[/]",
    "unknown":      "[#ff6b6b]unknown[/]",
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
            return f"{n // 1000}k"
        return f"{n / 1000:.1f}k"
    return str(n)


def abbrev_home(path: str) -> str:
    home = os.environ.get("HOME", "")
    if home and path.startswith(home):
        return "~" + path[len(home):]
    return path


class SessionRow(Widget, can_focus=True):
    """A card-style row showing one session with status, title, cwd, branch, time, tokens."""

    class Selected(Message):
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    DEFAULT_CSS = """
    SessionRow {
        height: 5;
        margin: 0 1 1 1;
        padding: 1 2;
        background: #111318;
        border: solid #1a1d24;
        border-left: blank;
    }
    SessionRow:hover {
        background: #161921;
    }
    SessionRow.selected {
        background: #161921;
        border-left: thick #74c0fc;
    }
    SessionRow .row-line1 {
        height: 1;
    }
    SessionRow .row-title {
        color: #e2e4e9;
        width: 1fr;
    }
    SessionRow .row-status {
        width: auto;
    }
    SessionRow .row-meta {
        color: #555869;
        height: 1;
    }
    SessionRow .row-stats {
        height: 1;
    }
    SessionRow .row-elapsed {
        color: #8b8fa3;
        width: auto;
    }
    SessionRow .row-sep {
        color: #333;
        width: auto;
    }
    SessionRow .row-tokens {
        color: #8b8fa3;
        width: auto;
    }
    """

    def __init__(self, session: Session, state: SessionState, selected: bool = False) -> None:
        super().__init__()
        self.session_data = session
        self.session_state = state
        if selected:
            self.add_class("selected")

    def compose(self) -> ComposeResult:
        s = self.session_data
        st = self.session_state

        # Line 1: title + status icon
        title = s.title or "New session"
        if len(title) > 40:
            title = title[:37] + "..."
        icon = STATUS_ICONS.get(st.status, "?")
        status_label = STATUS_LABELS.get(st.status, "")

        with Horizontal(classes="row-line1"):
            yield Static(f"[bold]{title}[/]", classes="row-title")
            yield Static(f"{icon} {status_label}", classes="row-status")

        # Line 2: cwd + branch
        cwd = abbrev_home(s.cwd)
        if s.git_branch:
            meta = f"[#555869]{cwd}[/] [#74c0fc]({s.git_branch})[/]"
        else:
            meta = f"[#555869]{cwd}[/]"
        yield Static(meta, classes="row-meta")

        # Line 3: elapsed + tokens
        elapsed = format_elapsed(time.time() - s.started_at)
        tokens = format_tokens(st.token_count)
        with Horizontal(classes="row-stats"):
            yield Static(f"[#8b8fa3]{elapsed}[/]", classes="row-elapsed")
            yield Static("[#333] · [/]", classes="row-sep")
            yield Static(f"[#8b8fa3]{tokens} tok[/]", classes="row-tokens")

    def on_click(self) -> None:
        self.post_message(self.Selected(self.session_data.id))
