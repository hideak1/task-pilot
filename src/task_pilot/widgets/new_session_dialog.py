"""Modal dialog for creating a new session."""

from __future__ import annotations

import json
import os
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static


HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"
MAX_RECENT = 10


class _DirItem(ListItem):
    """ListItem that stores its directory path as a plain attribute.

    Reading back the text via label.renderable is fragile across Textual
    versions (the attribute was removed/renamed), so we store the path
    explicitly instead.
    """

    def __init__(self, path: str) -> None:
        super().__init__(Label(path))
        self.path = path


def recent_directories() -> list[str]:
    """Read ~/.claude/history.jsonl and return up to MAX_RECENT unique projects."""
    if not HISTORY_FILE.exists():
        return []
    seen = []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in reversed(f.readlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    proj = entry.get("project")
                    if proj and proj not in seen:
                        seen.append(proj)
                        if len(seen) >= MAX_RECENT:
                            break
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return seen


def complete_path(value: str) -> str:
    """Tab-complete a partial path."""
    expanded = os.path.expanduser(value or "")
    p = Path(expanded)
    if p.is_dir() and not value.endswith("/"):
        return value + "/"
    parent = p.parent
    prefix = p.name
    if not parent.exists():
        return value
    matches = [c.name for c in parent.iterdir() if c.is_dir() and c.name.startswith(prefix)]
    if len(matches) == 1:
        return str(parent / matches[0]) + "/"
    if matches:
        common = os.path.commonprefix(matches)
        if len(common) > len(prefix):
            return str(parent / common)
    return value


class NewSessionDialog(ModalScreen[str | None]):
    """Returns the selected directory path, or None if cancelled."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    NewSessionDialog {
        align: center middle;
    }
    NewSessionDialog #panel {
        width: 60;
        height: 20;
        background: #181b22;
        border: solid #74c0fc;
        padding: 1 2;
    }
    NewSessionDialog Label.title {
        text-style: bold;
        margin-bottom: 1;
    }
    NewSessionDialog #path {
        background: #111318;
        color: #e2e4e9;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="panel"):
            yield Label("New Session", classes="title")
            yield Label("Recent directories:")
            items = [_DirItem(d) for d in recent_directories()]
            yield ListView(*items, id="recent")
            yield Label("Or type a path:")
            yield Input(placeholder="/path/to/project", id="path")
            yield Label("Enter: create   Esc: cancel", classes="hint")

    def on_mount(self) -> None:
        # Focus the path input by default so the user can immediately type
        self.query_one("#path", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        path = os.path.expanduser(event.value.strip())
        if path and Path(path).exists():
            self.dismiss(path)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, _DirItem):
            self.dismiss(item.path)

    def on_key(self, event) -> None:
        if event.key == "tab":
            inp = self.query_one("#path", Input)
            if inp.has_focus:
                inp.value = complete_path(inp.value)
                event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)
