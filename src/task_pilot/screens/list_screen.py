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
        ("n", "new_session", "New"),
        ("x", "close_session", "Close"),
        ("enter", "switch_to_selected", "Switch"),
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

    def action_new_session(self) -> None:
        from task_pilot.widgets.new_session_dialog import NewSessionDialog

        def handle(cwd: str | None) -> None:
            if cwd:
                from task_pilot.git_branch import current_branch
                s = self.tracker.create_session(
                    cwd=cwd, git_branch=current_branch(cwd)
                )
                self.tracker.switch_to(s.id)
                self.run_worker(self.refresh_data(), exclusive=False)

        self.app.push_screen(NewSessionDialog(), handle)

    def action_close_session(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        target = sessions[self._selected_index]
        # TODO confirmation dialog in 5.3 — for now just close
        self.tracker.close_session(target.id)
        self.run_worker(self.refresh_data(), exclusive=False)

    def action_switch_to_selected(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        target = sessions[self._selected_index]
        self.tracker.switch_to(target.id)
