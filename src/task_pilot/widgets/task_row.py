from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from task_pilot.models import Task


STATUS_ICONS = {
    "action_required": "[#ff6b6b]●[/]",
    "working": "[#69db7c]◉[/]",
    "done": "[#555869]✓[/]",
    "pending": "[#8b8fa3]○[/]",
}

STATUS_LABELS = {
    "action_required": "[#ff6b6b]需要操作[/]",
    "working": "[#69db7c]运行中[/]",
    "done": "[#555869]已完成[/]",
    "pending": "[#8b8fa3]等待中[/]",
}


def _format_time(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    now = datetime.now()
    diff = now - dt
    if diff.total_seconds() < 60:
        return "刚刚"
    if diff.total_seconds() < 3600:
        return f"{int(diff.total_seconds() / 60)}分钟前"
    if diff.total_seconds() < 86400:
        return f"{int(diff.total_seconds() / 3600)}小时前"
    return dt.strftime("%m-%d %H:%M")


class TaskRow(Widget, can_focus=True):
    """A single task row in the list view."""

    class Selected(Message):
        """Emitted when a task row is selected."""
        def __init__(self, task_id: str) -> None:
            self.task_id = task_id
            super().__init__()

    DEFAULT_CSS = """
    TaskRow {
        height: 3;
        padding: 0 2;
        background: #111318;
        border-bottom: solid #181b22;
    }
    TaskRow:hover {
        background: #181b22;
    }
    TaskRow:focus {
        background: #181b22;
        border-left: thick #74c0fc;
    }
    TaskRow Horizontal {
        height: 100%;
        align-vertical: middle;
    }
    TaskRow .icon {
        width: 4;
        min-width: 4;
        padding: 1 0;
    }
    TaskRow .title {
        width: 1fr;
        color: #e2e4e9;
        padding: 1 0;
    }
    TaskRow .meta {
        width: auto;
        color: #555869;
        padding: 1 0;
    }
    """

    def __init__(self, task: Task) -> None:
        super().__init__()
        self.task_data = task

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(STATUS_ICONS.get(self.task_data.status, "○"), classes="icon")
            title_text = self.task_data.title
            if len(title_text) > 60:
                title_text = title_text[:57] + "..."
            yield Static(title_text, classes="title")
            yield Static(_format_time(self.task_data.updated_at), classes="meta")

    def on_click(self) -> None:
        self.post_message(self.Selected(self.task_data.id))

    def key_enter(self) -> None:
        self.post_message(self.Selected(self.task_data.id))
