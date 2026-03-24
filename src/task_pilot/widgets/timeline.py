from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static

from task_pilot.models import TimelineEvent


DOT_COLORS = {
    "session_start": "#69db7c",
    "session_end": "#555869",
    "blocked": "#ffd43b",
    "code_done": "#69db7c",
    "resumed": "#74c0fc",
}


def _format_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


class TimelineEntry(Widget):
    """A single timeline entry with dot, time, and description."""

    DEFAULT_CSS = """
    TimelineEntry {
        height: 2;
        padding: 0 1;
        layout: horizontal;
    }
    TimelineEntry .tl-time {
        width: 8;
        min-width: 8;
        color: #555869;
        padding: 0 0;
    }
    TimelineEntry .tl-dot {
        width: 3;
        min-width: 3;
        padding: 0 0;
    }
    TimelineEntry .tl-desc {
        width: 1fr;
        color: #8b8fa3;
    }
    """

    def __init__(self, event: TimelineEvent) -> None:
        super().__init__()
        self.event = event

    def compose(self) -> ComposeResult:
        time_str = _format_timestamp(self.event.timestamp)
        yield Static(time_str, classes="tl-time")
        color = DOT_COLORS.get(self.event.event_type, "#8b8fa3")
        yield Static(f"[{color}]●[/]", classes="tl-dot")
        yield Static(self.event.description, classes="tl-desc")


class Timeline(Widget):
    """Timeline card showing key events."""

    DEFAULT_CSS = """
    Timeline {
        background: #111318;
        border: solid #181b22;
        margin: 1 2;
        padding: 1 1;
    }
    Timeline .card-title {
        color: #74c0fc;
        text-style: bold;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, events: list[TimelineEvent]) -> None:
        super().__init__()
        self.events = events

    def compose(self) -> ComposeResult:
        yield Static(f"时间线 ({len(self.events)})", classes="card-title")
        for event in self.events:
            yield TimelineEntry(event)
