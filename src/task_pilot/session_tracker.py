"""Session lifecycle: create, close, switch, reconcile.

This module is the only place that touches both the DB and tmux. The Textual
UI layer calls into SessionTracker; SessionTracker calls into db and tmux
modules. This keeps test mocking surgical.
"""

from __future__ import annotations

import sys
import time
import uuid
from typing import TYPE_CHECKING

from task_pilot.git_branch import current_branch
from task_pilot.models import Session, SessionState
from task_pilot.title_clean import clean_title
from task_pilot.transcript_reader import (
    extract_first_user_message,
    last_activity_timestamp,
    sum_tokens,
)
from task_pilot.transcript_resolver import resolve_by_cwd_and_time

if TYPE_CHECKING:
    from task_pilot.db import Database


class SessionTracker:
    def __init__(self, db: "Database", tmux, session_name: str = "task-pilot"):
        self.db = db
        self.tmux = tmux
        self.session_name = session_name
        self._state_cache: dict[str, SessionState] = {}

    def refresh_state(self, force: bool = False) -> dict[str, SessionState]:
        """Compute SessionState for every session in DB.

        force=True re-resolves git branches and transcript paths (used by manual `r`).
        """
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
                        title = clean_title(first)
                        self.db.update_session(s.id, title=title)
            else:
                # No transcript yet — initializing for the first 30 seconds,
                # then unknown (Claude Code may have failed to start or is hung)
                if time.time() - s.started_at > 30:
                    state.status = "unknown"
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
        # Keepalive wrapper: when claude exits, `cat` keeps the pane alive
        # by blocking on stdin forever. reconcile() detects ended sessions
        # by checking pane_current_command == "cat".
        # Note: `sleep infinity` doesn't exist on macOS, so we use `cat`.
        self.tmux.new_window(
            self.session_name, window, cwd,
            "claude; exec cat",
        )
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
        """Kill the tmux window and remove the DB record.

        If this session is currently visible in main.1, its pane is swapped
        back to its home window first so that killing it doesn't destroy
        the main window's right-pane slot.
        """
        s = self.db.get_session(session_id)
        if s is None:
            return
        current_id = self.db.get_current_session_id()
        if current_id == session_id:
            # Swap the visible pane back home before killing it
            self.tmux.swap_pane(
                f"{self.session_name}:main.1",
                f"{self.session_name}:{s.tmux_window}.0",
            )
            self.db.clear_current_session()
        target = f"{self.session_name}:{s.tmux_window}"
        self.tmux.kill_window(target)
        self.db.delete_session(session_id)
        self._state_cache.pop(session_id, None)

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
        """Sync DB with the live state of tmux windows.

        Handles three cases:
        1. DB has a session but its tmux window is gone → drop from DB.
        2. Claude exited but the keepalive wrapper kept the pane alive →
           detect via `pane_current_command == "sleep"`, then clean up.
        3. tmux has a _bg_* window with no DB record → adopt it.
        """
        try:
            tmux_windows = set(self.tmux.list_windows(self.session_name))
        except Exception:
            return  # tmux not running
        bg_windows = {w for w in tmux_windows if w.startswith("_bg_")}

        # Step 1: drop DB records whose tmux window is gone
        for s in self.db.list_sessions():
            if s.tmux_window not in bg_windows:
                self._remove_session(s.id)
                continue

            # Step 2: check if Claude exited (keepalive wrapper runs
            # `sleep infinity` after claude exits, so pane_current_command
            # changes from "claude" to "sleep").
            # Check the pane wherever it currently lives:
            current_id = self.db.get_current_session_id()
            if current_id == s.id:
                # This session is visible in main.1
                target = f"{self.session_name}:main.1"
            else:
                # This session is in its home _bg window
                target = f"{self.session_name}:{s.tmux_window}.0"

            pane_cmd = self.tmux.display_message(target, "#{pane_current_command}")
            # After claude exits, the keepalive wrapper runs `exec cat`,
            # so pane_current_command changes from "claude"/"node" to "cat".
            is_dead = pane_cmd in ("cat", "sleep", "") or (
                self.tmux.display_message(target, "#{pane_dead}") == "1"
            )

            if is_dead:
                # Kill the bg window (if it still exists)
                if s.tmux_window in bg_windows:
                    self.tmux.kill_window(f"{self.session_name}:{s.tmux_window}")
                self._remove_session(s.id)

        # Step 3: adopt orphan tmux windows that have no DB record
        existing_windows = {s.tmux_window for s in self.db.list_sessions()}
        for w in bg_windows - existing_windows:
            self._adopt_window(w)

    def _remove_session(self, session_id: str) -> None:
        """Remove a session from DB and clear current if it was the visible one."""
        current_id = self.db.get_current_session_id()
        self.db.delete_session(session_id)
        self._state_cache.pop(session_id, None)
        if current_id == session_id:
            self.db.clear_current_session()
            # If there are still other sessions, switch to the first one.
            # Otherwise restore the welcome banner in main.1.
            remaining = self.db.list_sessions()
            if remaining:
                self.switch_to(remaining[0].id)
            else:
                self._restore_welcome_pane()

    def _restore_welcome_pane(self) -> None:
        """Replace main.1 with a fresh welcome banner."""
        python_cmd = sys.executable
        try:
            # Kill the current (dead) main.1 and respawn it with welcome
            self.tmux.run([
                "respawn-pane", "-k",
                "-t", f"{self.session_name}:main.1",
                "sh", "-c", f"{python_cmd} -m task_pilot.welcome",
            ])
        except Exception:
            pass

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
