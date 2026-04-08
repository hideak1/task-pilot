"""Main left-panel screen showing the session list."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.screen import Screen
from textual.widgets import Footer, Static

from task_pilot.db import Database
from task_pilot.models import SessionState
from task_pilot.session_tracker import SessionTracker
from task_pilot.widgets.session_row import SessionRow

REFRESH_INTERVAL_SECONDS = 2.0


class ListScreen(Screen):
    BINDINGS = [
        ("up,k", "move_up", "Up"),
        ("down,j", "move_down", "Down"),
        ("r", "force_refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    ListScreen { background: #0c0e12; }
    ListScreen #empty {
        color: #555869;
        padding: 2 2;
        text-style: italic;
    }
    """

    def __init__(self, db: Database, tracker: SessionTracker) -> None:
        super().__init__()
        self.db = db
        self.tracker = tracker
        self._selected_index = 0
        self._states: dict[str, SessionState] = {}

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="rows"):
            yield Static("Loading...")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_data()
        self.set_interval(REFRESH_INTERVAL_SECONDS, self.refresh_data)

    async def refresh_data(self, force: bool = False) -> None:
        self.tracker.reconcile()
        self._states = self.tracker.refresh_state(force=force)
        await self._render_rows()

    async def _render_rows(self) -> None:
        container = self.query_one("#rows", ScrollableContainer)
        await container.remove_children()
        sessions = self.db.list_sessions()
        if not sessions:
            await container.mount(Static("No sessions. Press n to create one."))
            return
        # Clamp selection
        if self._selected_index >= len(sessions):
            self._selected_index = max(0, len(sessions) - 1)
        for i, s in enumerate(sessions):
            state = self._states.get(s.id, SessionState(session_id=s.id))
            row = SessionRow(session=s, state=state, selected=(i == self._selected_index))
            await container.mount(row)

    async def action_move_up(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        self._selected_index = max(0, self._selected_index - 1)
        await self._render_rows()

    async def action_move_down(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        self._selected_index = min(len(sessions) - 1, self._selected_index + 1)
        await self._render_rows()

    async def action_force_refresh(self) -> None:
        await self.refresh_data(force=True)
