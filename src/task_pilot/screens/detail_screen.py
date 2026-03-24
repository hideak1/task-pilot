import subprocess
import sys

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from task_pilot.db import Database
from task_pilot.models import Task
from task_pilot.widgets.action_steps import ActionStepRow, ActionSteps
from task_pilot.widgets.timeline import Timeline


STATUS_BADGES = {
    "action_required": "[#ff6b6b on #1a0f0f] 需要操作 [/]",
    "working": "[#69db7c on #0f1a10] 运行中 [/]",
    "done": "[#555869 on #111318] 已完成 [/]",
    "pending": "[#8b8fa3 on #111318] 等待中 [/]",
}


class DetailScreen(Screen):
    """Detail view for a single task."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("c", "resume_session", "Resume"),
        ("d", "mark_done", "Done"),
    ]

    DEFAULT_CSS = """
    DetailScreen {
        background: #0c0e12;
    }
    DetailScreen .breadcrumb {
        height: 1;
        padding: 0 2;
        color: #555869;
        margin-top: 1;
    }
    DetailScreen .detail-title {
        height: auto;
        padding: 0 2;
        color: #e2e4e9;
        text-style: bold;
        margin-top: 1;
    }
    DetailScreen .badge-row {
        height: 1;
        padding: 0 2;
        margin-bottom: 1;
    }
    DetailScreen .summary-card {
        background: #111318;
        border: solid #181b22;
        margin: 1 2;
        padding: 1 2;
    }
    DetailScreen .summary-title {
        color: #8b8fa3;
        text-style: bold;
        margin-bottom: 1;
    }
    DetailScreen .summary-text {
        color: #e2e4e9;
    }
    DetailScreen .no-summary {
        color: #555869;
        text-style: italic;
    }
    """

    def __init__(self, db: Database, task_id: str) -> None:
        super().__init__()
        self._db = db
        self._task_id = task_id

    def compose(self) -> ComposeResult:
        task = self._db.get_task(self._task_id)
        if not task:
            yield Static("Task not found", classes="breadcrumb")
            yield Footer()
            return

        yield Static(f"Tasks › {task.id[:8]}", classes="breadcrumb")
        yield Static(task.title, classes="detail-title")

        badge = STATUS_BADGES.get(task.status, "")
        session_count = len(task.sessions)
        yield Static(f"{badge}  [#555869]{session_count} session(s)[/]", classes="badge-row")

        with ScrollableContainer():
            # Summary card
            with Vertical(classes="summary-card"):
                yield Static("摘要", classes="summary-title")
                if task.summary:
                    yield Static(task.summary, classes="summary-text")
                else:
                    yield Static("No summary available", classes="no-summary")

            # Action steps
            if task.action_items:
                yield ActionSteps(task.action_items)

            # Timeline
            if task.timeline:
                yield Timeline(task.timeline)

        yield Footer()

    def on_action_step_row_toggled(self, event: ActionStepRow.Toggled) -> None:
        self._db.toggle_action_item(event.item_id)
        self.app.pop_screen()
        self.app.push_screen(DetailScreen(self._db, self._task_id))

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_resume_session(self) -> None:
        task = self._db.get_task(self._task_id)
        if not task or not task.sessions:
            self.notify("No sessions to resume", severity="warning")
            return
        session = task.sessions[0]  # Most recent
        try:
            subprocess.Popen(
                ["claude", "--resume", session.session_id],
                start_new_session=True,
            )
            self.notify(f"Resuming session {session.session_id[:8]}...")
        except FileNotFoundError:
            self.notify("claude CLI not found", severity="error")

    def action_mark_done(self) -> None:
        self._db.mark_task_done(self._task_id)
        self.app.pop_screen()
