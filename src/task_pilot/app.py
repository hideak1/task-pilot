from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer

from task_pilot.config import CLAUDE_HOME, DB_PATH, TASK_PILOT_DIR
from task_pilot.db import Database


class TaskPilotApp(App):
    """Task Pilot - Claude Code session dispatcher panel."""

    CSS_PATH = "styles/app.tcss"
    TITLE = "Task Pilot"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, db_path: Path | None = None, claude_home: Path | None = None):
        super().__init__()
        self._db_path = db_path or DB_PATH
        self._claude_home = claude_home or CLAUDE_HOME

    @property
    def db(self) -> Database:
        if not hasattr(self, "_db"):
            TASK_PILOT_DIR.mkdir(parents=True, exist_ok=True)
            self._db = Database(self._db_path)
        return self._db

    def compose(self) -> ComposeResult:
        from task_pilot.screens.list_screen import ListScreen

        yield ListScreen(self.db)
        yield Footer()

    def on_mount(self) -> None:
        self._run_scan()

    def _run_scan(self) -> None:
        try:
            from task_pilot.scanner import ClaudeScanner

            scanner = ClaudeScanner(claude_home=self._claude_home, db=self.db)
            scanner.scan()
        except Exception:
            pass

    def action_refresh(self) -> None:
        from task_pilot.screens.list_screen import ListScreen

        list_screen = self.query_one(ListScreen)
        list_screen.refresh_tasks()

    def action_full_scan(self) -> None:
        """Manual full scan (Shift+R)."""
        self._run_scan()
        self.action_refresh()
