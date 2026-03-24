from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class HeaderBar(Widget):
    """Top header bar showing logo and task stats."""

    action_count: reactive[int] = reactive(0)
    working_count: reactive[int] = reactive(0)
    done_count: reactive[int] = reactive(0)

    DEFAULT_CSS = """
    HeaderBar {
        dock: top;
        height: 3;
        background: #111318;
        border-bottom: solid #181b22;
        padding: 0 2;
        layout: horizontal;
    }
    HeaderBar #logo {
        width: auto;
        color: #74c0fc;
        text-style: bold;
        padding: 1 0;
    }
    HeaderBar #spacer {
        width: 1fr;
    }
    HeaderBar #stats {
        width: auto;
        color: #8b8fa3;
        padding: 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Task Pilot", id="logo")
        yield Static("", id="spacer")
        yield Static(self._stats_text(), id="stats")

    def _stats_text(self) -> str:
        parts = []
        if self.action_count > 0:
            parts.append(f"[#ff6b6b]{self.action_count} 待处理[/]")
        if self.working_count > 0:
            parts.append(f"[#69db7c]{self.working_count} 运行中[/]")
        parts.append(f"[#555869]{self.done_count} 完成[/]")
        return " | ".join(parts)

    def watch_action_count(self) -> None:
        self._update_stats()

    def watch_working_count(self) -> None:
        self._update_stats()

    def watch_done_count(self) -> None:
        self._update_stats()

    def _update_stats(self) -> None:
        try:
            stats = self.query_one("#stats", Static)
            stats.update(self._stats_text())
        except Exception:
            pass

    def update_counts(self, action: int, working: int, done: int) -> None:
        self.action_count = action
        self.working_count = working
        self.done_count = done
