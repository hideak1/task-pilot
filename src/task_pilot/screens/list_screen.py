"""Main left-panel screen showing the session list."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.screen import Screen
from textual.widgets import Footer, Static

from task_pilot.db import Database
from task_pilot.models import Session, SessionState
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
        ("colon,shift+semicolon", "open_command", "Command"),
        ("slash", "open_search", "Search"),
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
        self._search_query: str = ""

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

    def _filtered_sessions(self) -> list[Session]:
        sessions = self.db.list_sessions()
        if not self._search_query:
            return sessions
        q = self._search_query.lower()
        return [
            s for s in sessions
            if q in (s.title or "").lower() or q in s.cwd.lower()
        ]

    async def _render_rows(self) -> None:
        container = self.query_one("#rows", ScrollableContainer)
        await container.remove_children()
        sessions = self._filtered_sessions()
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
        sessions = self._filtered_sessions()
        if not sessions:
            return
        self._selected_index = max(0, self._selected_index - 1)
        await self._render_rows()

    async def action_move_down(self) -> None:
        sessions = self._filtered_sessions()
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
                from pathlib import Path as _P
                if not _P(cwd).is_dir():
                    self.notify(f"E: not a directory: {cwd}", severity="error")
                    return
                try:
                    from task_pilot.git_branch import current_branch
                    s = self.tracker.create_session(
                        cwd=cwd, git_branch=current_branch(cwd)
                    )
                    self.tracker.switch_to(s.id)
                except Exception as e:  # noqa: BLE001
                    self.notify(f"E: create failed: {e}", severity="error")
                    return
                self.run_worker(self.refresh_data(), exclusive=False)

        self.app.push_screen(NewSessionDialog(), handle)

    def action_close_session(self) -> None:
        sessions = self._filtered_sessions()
        if not sessions:
            return
        if self._selected_index >= len(sessions):
            self._selected_index = len(sessions) - 1
        target = sessions[self._selected_index]
        from task_pilot.widgets.confirm_dialog import ConfirmDialog

        def on_confirm(yes: bool | None) -> None:
            if yes:
                self.tracker.close_session(target.id)
                self.run_worker(self.refresh_data(), exclusive=False)

        title = target.title or "this session"
        self.app.push_screen(
            ConfirmDialog(f'Close "{title}"? This kills the Claude Code process.'),
            on_confirm,
        )

    def action_switch_to_selected(self) -> None:
        sessions = self._filtered_sessions()
        if not sessions:
            return
        if self._selected_index >= len(sessions):
            self._selected_index = len(sessions) - 1
        target = sessions[self._selected_index]
        self.tracker.switch_to(target.id)

    def action_open_command(self) -> None:
        from task_pilot.widgets.command_bar import CommandBar

        def handle(cmd: str | None) -> None:
            if cmd is None:
                return
            if cmd in ("q", "q!", "quit"):
                self._quit_pilot()
            else:
                self.notify(f"E: not a command: {cmd}", severity="error")

        self.app.push_screen(CommandBar(), handle)

    def _quit_pilot(self) -> None:
        """Kill the tmux session and exit pilot.

        Order matters: we must NOT kill the tmux session before app.exit()
        because pilot itself runs inside that session — killing it first
        would terminate pilot mid-execution. Instead, fire a detached
        subprocess that waits briefly then runs `tmux kill-session`,
        and immediately call app.exit() so pilot's pane shuts down cleanly
        before tmux tears everything down.
        """
        import subprocess
        subprocess.Popen(
            ["sh", "-c", "sleep 0.3 && tmux kill-session -t task-pilot"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.app.exit()

    def action_open_search(self) -> None:
        from task_pilot.widgets.search_bar import SearchBar

        def on_change(query: str) -> None:
            self._search_query = query
            self.run_worker(self._render_rows(), exclusive=False)

        def on_close() -> None:
            self._search_query = ""
            self.run_worker(self._render_rows(), exclusive=False)

        self.app.push_screen(SearchBar(on_change, on_close))
