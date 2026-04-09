"""Main left-panel screen showing the session list."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Static

from task_pilot.db import Database
from task_pilot.models import Session, SessionState
from task_pilot.session_tracker import SessionTracker
from task_pilot.widgets.session_row import SessionRow

REFRESH_INTERVAL_SECONDS = 2.0
RECONCILE_INTERVAL_TICKS = 5  # reconcile every N refresh ticks (= 10s)


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
    ListScreen {
        background: #0c0e12;
    }

    /* ── Header ── */
    ListScreen #header {
        dock: top;
        height: 3;
        background: #111318;
        border-bottom: solid #1a1d24;
        padding: 1 2;
    }
    ListScreen .header-logo {
        color: #74c0fc;
        text-style: bold;
        width: auto;
    }
    ListScreen .header-stats {
        color: #555869;
        width: 1fr;
        text-align: right;
    }

    /* ── Rows container ── */
    ListScreen #rows {
        padding: 1 0;
    }

    /* ── Empty state ── */
    ListScreen #empty-box {
        width: 100%;
        height: 100%;
        align: center middle;
    }
    ListScreen .empty-logo {
        color: #74c0fc;
        text-style: bold;
        text-align: center;
    }
    ListScreen .empty-title {
        color: #e2e4e9;
        text-style: bold;
        text-align: center;
        margin-top: 1;
    }
    ListScreen .empty-hint {
        color: #8b8fa3;
        text-align: center;
        margin-top: 1;
    }

    /* ── Bottom bar ── */
    ListScreen #bottom-bar {
        dock: bottom;
        height: 1;
        background: #111318;
        padding: 0 2;
        color: #555869;
        border-top: solid #1a1d24;
    }
    """

    def __init__(self, db: Database, tracker: SessionTracker) -> None:
        super().__init__()
        self.db = db
        self.tracker = tracker
        self._selected_index = 0
        self._states: dict[str, SessionState] = {}
        self._search_query: str = ""
        self._tick_count = 0
        self._last_snapshot: str = ""  # fingerprint of last rendered state

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static("[bold #74c0fc]Task Pilot[/]", classes="header-logo")
            yield Static("", classes="header-stats", id="stats")
        with ScrollableContainer(id="rows"):
            yield Static("Loading...")
        yield Static(
            "[#ffd43b]n[/]:new  "
            "[#ffd43b]x[/]:close  "
            "[#ffd43b]/[/]:search  "
            "[#ffd43b]:q[/]:quit",
            id="bottom-bar",
        )

    async def on_mount(self) -> None:
        await self.refresh_data(force=True)
        self.set_interval(REFRESH_INTERVAL_SECONDS, self.refresh_data)

    async def refresh_data(self, force: bool = False) -> None:
        # Reconcile less often (subprocess-heavy: tmux list-windows + display-message)
        self._tick_count += 1
        if force or self._tick_count % RECONCILE_INTERVAL_TICKS == 0:
            self.tracker.reconcile()

        self._states = self.tracker.refresh_state(force=force)

        # Only re-render if the data actually changed (prevents flicker)
        snapshot = self._build_snapshot()
        if snapshot != self._last_snapshot:
            self._last_snapshot = snapshot
            await self._render_rows()

    def _build_snapshot(self) -> str:
        """Build a fingerprint of the current display state.

        If this string is the same as last time, skip the re-render.
        """
        sessions = self._filtered_sessions()
        parts = [str(self._selected_index), self._search_query]
        for s in sessions:
            st = self._states.get(s.id)
            parts.append(
                f"{s.id}:{s.title}:{s.git_branch}:"
                f"{st.token_count if st else 0}:{st.status if st else '?'}"
            )
        return "|".join(parts)

    def _filtered_sessions(self) -> list[Session]:
        sessions = self.db.list_sessions()
        if not self._search_query:
            return sessions
        q = self._search_query.lower()
        return [
            s for s in sessions
            if q in (s.title or "").lower() or q in s.cwd.lower()
        ]

    def _update_header_stats(self, sessions: list) -> None:
        """Update the header stats counter."""
        try:
            stats_widget = self.query_one("#stats", Static)
            working = sum(1 for s in sessions if self._states.get(s.id) and self._states[s.id].status == "working")
            idle = sum(1 for s in sessions if self._states.get(s.id) and self._states[s.id].status == "idle")
            total = len(sessions)
            parts = []
            if working:
                parts.append(f"[#69db7c]{working} working[/]")
            if idle:
                parts.append(f"[#ffd43b]{idle} idle[/]")
            if total and not working and not idle:
                parts.append(f"[#8b8fa3]{total} session{'s' if total != 1 else ''}[/]")
            elif total:
                parts.append(f"[#555869]{total} total[/]")
            stats_widget.update("  ".join(parts) if parts else "")
        except Exception:
            pass

    async def _render_rows(self) -> None:
        container = self.query_one("#rows", ScrollableContainer)
        await container.remove_children()
        all_sessions = self.db.list_sessions()
        self._update_header_stats(all_sessions)
        sessions = self._filtered_sessions()
        if not sessions:
            empty_box = Vertical(id="empty-box")
            await container.mount(empty_box)
            await empty_box.mount(Static(
                "┌─┐\n"
                "│ │\n"
                "└─┘",
                classes="empty-logo",
            ))
            await empty_box.mount(Static("Task Pilot", classes="empty-title"))
            await empty_box.mount(Static(
                "No sessions yet",
                classes="empty-hint",
            ))
            await empty_box.mount(Static(
                "[#ffd43b bold]n[/] new   "
                "[#ffd43b bold]/[/] search   "
                "[#ffd43b bold]:q[/] quit",
                classes="empty-hint",
            ))
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
        current = self.db.get_current_session_id()
        if current == target.id:
            # Already showing this session — just move focus to the right pane
            self.tracker._focus_right()
            return
        self.tracker.switch_to(target.id)
        title = target.title or "session"
        self.notify(f"Switched to {title}", timeout=2)

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
