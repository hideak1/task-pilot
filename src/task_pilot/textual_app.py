"""Textual app that runs inside the left tmux pane."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from task_pilot import tmux
from task_pilot.config import DB_PATH, TASK_PILOT_DIR
from task_pilot.db import Database
from task_pilot.screens.list_screen import ListScreen
from task_pilot.session_tracker import SessionTracker


class TaskPilotTextualApp(App):
    TITLE = "Task Pilot"

    def __init__(self, db_path: Path | None = None):
        super().__init__()
        self._db_path = db_path or DB_PATH

    def on_mount(self) -> None:
        TASK_PILOT_DIR.mkdir(parents=True, exist_ok=True)
        self.db = Database(self._db_path)
        self.tracker = SessionTracker(self.db, tmux=tmux)
        self.push_screen(ListScreen(self.db, self.tracker))


def main() -> None:
    app = TaskPilotTextualApp()
    app.run()


if __name__ == "__main__":
    main()
