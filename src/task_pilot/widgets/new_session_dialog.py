"""Modal dialog for creating a new session."""

from __future__ import annotations

import json
import os
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static


HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"
MAX_RECENT = 10


class _DirItem(ListItem):
    """ListItem that stores its directory path as a plain attribute."""

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
        Binding("up", "focus_list", "Up", show=False),
        Binding("down", "focus_list", "Down", show=False),
    ]

    DEFAULT_CSS = """
    NewSessionDialog {
        align: center middle;
    }
    NewSessionDialog #panel {
        width: 60;
        height: 22;
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
    NewSessionDialog #recent {
        height: auto;
        max-height: 10;
    }
    NewSessionDialog .hint {
        color: #555869;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        dirs = recent_directories()
        with Vertical(id="panel"):
            yield Label("New Session", classes="title")
            if dirs:
                yield Label("[#8b8fa3]Recent directories (arrow keys to select):[/]")
                yield ListView(*[_DirItem(d) for d in dirs], id="recent")
            yield Label("[#8b8fa3]Type a path (Tab to complete, Enter to create):[/]")
            yield Input(placeholder="/path/to/project", id="path")
            yield Label(
                "[#ffd43b]Enter[/] create  "
                "[#ffd43b]Tab[/] complete  "
                "[#ffd43b]Esc[/] cancel",
                classes="hint",
            )

    def on_mount(self) -> None:
        # Focus the list first if there are recent dirs, so arrow keys work
        try:
            lv = self.query_one("#recent", ListView)
            if len(lv.children) > 0:
                lv.focus()
            else:
                self.query_one("#path", Input).focus()
        except Exception:
            self.query_one("#path", Input).focus()

    def action_focus_list(self) -> None:
        """Move focus to the recent dirs list (from the input)."""
        try:
            lv = self.query_one("#recent", ListView)
            lv.focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        path = os.path.expanduser(event.value.strip())
        if not path:
            return
        p = Path(path)
        # Auto-create the directory if it doesn't exist
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.notify(f"Cannot create: {path}", severity="error")
                return
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
                return
            # Tab from list → focus input
            inp.focus()
            event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)
