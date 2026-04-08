"""Main left-panel screen showing the session list."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.screen import Screen
from textual.widgets import Footer, Static

from task_pilot.db import Database
from task_pilot.models import SessionState
from task_pilot.widgets.session_row import SessionRow


class ListScreen(Screen):
    """Renders the session list with arrow-key selection."""

    BINDINGS = [
        ("up,k", "move_up", "Up"),
        ("down,j", "move_down", "Down"),
    ]

    DEFAULT_CSS = """
    ListScreen {
        background: #0c0e12;
    }
    ListScreen #empty {
        color: #555869;
        padding: 2 2;
        text-style: italic;
    }
    """

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self._selected_index = 0

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="rows"):
            yield Static("Loading...")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        container = self.query_one("#rows", ScrollableContainer)
        container.remove_children()
        sessions = self.db.list_sessions()
        if not sessions:
            container.mount(Static("No sessions. Press n to create one.", id="empty"))
            return

        for i, s in enumerate(sessions):
            state = SessionState(session_id=s.id)  # placeholder; Phase 4 fills it
            row = SessionRow(session=s, state=state, selected=(i == self._selected_index))
            container.mount(row)

    def action_move_up(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        self._selected_index = max(0, self._selected_index - 1)
        self.refresh_list()

    def action_move_down(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        self._selected_index = min(len(sessions) - 1, self._selected_index + 1)
        self.refresh_list()
