"""Session lifecycle: create, close, switch, reconcile.

This module is the only place that touches both the DB and tmux. The Textual
UI layer calls into SessionTracker; SessionTracker calls into db and tmux
modules. This keeps test mocking surgical.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from task_pilot.models import Session

if TYPE_CHECKING:
    from task_pilot.db import Database


class SessionTracker:
    def __init__(self, db: "Database", tmux, session_name: str = "task-pilot"):
        self.db = db
        self.tmux = tmux
        self.session_name = session_name
        from task_pilot.models import SessionState
        self._state_cache: dict[str, SessionState] = {}

    def refresh_state(self, force: bool = False) -> dict[str, "SessionState"]:
        """Compute SessionState for every session in DB.

        force=True re-resolves git branches and transcript paths (used by manual `r`).
        """
        from task_pilot.git_branch import current_branch
        from task_pilot.transcript_reader import sum_tokens, last_activity_timestamp, extract_first_user_message
        from task_pilot.transcript_resolver import resolve_by_cwd_and_time, resolve_by_pid
        from task_pilot.models import SessionState
        import time

        result: dict[str, SessionState] = {}
        for s in self.db.list_sessions():
            state = self._state_cache.get(s.id) or SessionState(session_id=s.id)

            # Resolve transcript path if not cached or forced
            if state.transcript_path is None or force:
                state.transcript_path = resolve_by_cwd_and_time(
                    s.cwd, s.started_at,
                )

            if state.transcript_path and state.transcript_path.exists():
                state.token_count = sum_tokens(state.transcript_path)
                state.last_activity = last_activity_timestamp(state.transcript_path)

                # Status
                if state.last_activity == 0:
                    state.status = "initializing"
                elif time.time() - state.last_activity < 30:
                    state.status = "working"
                else:
                    state.status = "idle"

                # Title from first user message (only if not set yet)
                if not s.title:
                    first = extract_first_user_message(state.transcript_path)
                    if first:
                        from task_pilot.title_clean import clean_title
                        title = clean_title(first)
                        self.db.update_session(s.id, title=title)
            else:
                state.status = "initializing"

            # Git branch (cached unless forced)
            if force or s.git_branch is None:
                branch = current_branch(s.cwd)
                if branch and branch != s.git_branch:
                    self.db.update_session(s.id, git_branch=branch)

            self._state_cache[s.id] = state
            result[s.id] = state
        return result

    # ── lifecycle ────────────────────────────────────────────

    def create_session(self, cwd: str, git_branch: str | None = None) -> Session:
        """Create a new Claude Code session in a fresh _bg_<uuid> window."""
        sid = uuid.uuid4().hex[:12]
        window = f"_bg_{sid}"
        self.tmux.new_window(self.session_name, window, cwd, "claude")
        s = Session(
            id=sid,
            tmux_window=window,
            cwd=cwd,
            git_branch=git_branch,
            started_at=time.time(),
            title=None,
        )
        self.db.insert_session(s)
        return s

    def close_session(self, session_id: str) -> None:
        """Kill the tmux window and remove the DB record."""
        s = self.db.get_session(session_id)
        if s is None:
            return
        target = f"{self.session_name}:{s.tmux_window}"
        self.tmux.kill_window(target)
        self.db.delete_session(session_id)

    def switch_to(self, target_id: str) -> None:
        """Two-step swap: return current home, then bring target into main.1."""
        target = self.db.get_session(target_id)
        if target is None:
            return
        current_id = self.db.get_current_session_id()
        # No-op if target is already visible — otherwise the second swap below
        # would swap main.1's (visible target) pane OUT to an empty _bg window.
        if current_id == target_id:
            return
        if current_id:
            current = self.db.get_session(current_id)
            if current:
                # Step 1: return current's pane home to its _bg window
                self.tmux.swap_pane(
                    f"{self.session_name}:main.1",
                    f"{self.session_name}:{current.tmux_window}.0",
                )
        # Step 2: bring target's pane from its home into main.1
        self.tmux.swap_pane(
            f"{self.session_name}:main.1",
            f"{self.session_name}:{target.tmux_window}.0",
        )
        self.db.set_current_session_id(target_id)

    # ── reconciliation ───────────────────────────────────────

    def reconcile(self) -> None:
        """Sync DB with the live state of tmux windows."""
        # Step 0: ensure main window exists (Phase 6 will recreate if missing)
        # For now we assume main exists if we got this far.

        try:
            tmux_windows = set(self.tmux.list_windows(self.session_name))
        except Exception:
            return  # tmux not running
        bg_windows = {w for w in tmux_windows if w.startswith("_bg_")}

        # Step 1: drop DB records whose tmux window is gone
        for s in self.db.list_sessions():
            if s.tmux_window not in bg_windows:
                self.db.delete_session(s.id)

        # Step 2: adopt orphan tmux windows that have no DB record
        existing_windows = {s.tmux_window for s in self.db.list_sessions()}
        for w in bg_windows - existing_windows:
            self._adopt_window(w)

    def _adopt_window(self, window: str) -> None:
        adopted_id = window[len("_bg_"):]
        target = f"{self.session_name}:{window}.0"
        cwd = self.tmux.display_message(target, "#{pane_current_path}") or "/"
        try:
            started_at = float(self.tmux.display_message(target, "#{window_activity}"))
        except (ValueError, TypeError):
            started_at = time.time()
        self.db.insert_session(Session(
            id=adopted_id,
            tmux_window=window,
            cwd=cwd,
            git_branch=None,
            started_at=started_at,
            title=None,
        ))
