"""Integration test: full session lifecycle via hook handler functions."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from task_pilot.db import Database
from task_pilot import hooks
from task_pilot.hooks import (
    handle_heartbeat,
    handle_session_end,
    handle_session_start,
    handle_stop,
)


@pytest.fixture(autouse=True)
def _clear_heartbeat_throttle():
    """Clear heartbeat throttle cache before each test."""
    hooks._last_heartbeat.clear()

@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Create a temporary database for each test."""
    db_path = tmp_path / "test_lifecycle.db"
    database = Database(db_path)
    yield database
    database.close()


class TestFullLifecycle:
    """Simulate: session-start -> heartbeat -> stop -> session-start -> session-end.

    Expected status transitions: pending -> working -> action_required -> working -> done.
    """

    def test_full_lifecycle(self, db: Database) -> None:
        session_id = "sess-integration-001"
        project_dir = "/tmp/my-project"
        pid = 12345

        # --- Step 1: session-start creates task with status "working" ---
        task_id = handle_session_start(db, session_id, project_dir, pid)
        assert task_id is not None

        task = db.get_task(task_id)
        assert task is not None
        assert task.status == "working"
        assert task.title == "my-project"

        # Session should be active
        session = db.get_session(session_id)
        assert session is not None
        assert session.is_active is True
        assert session.pid == pid
        assert session.cwd == project_dir

        # --- Step 2: heartbeat keeps status "working" ---
        hb_task_id = handle_heartbeat(db, session_id)
        assert hb_task_id == task_id

        task = db.get_task(task_id)
        assert task.status == "working"

        # --- Step 3: stop changes status to "action_required" ---
        stop_task_id = handle_stop(db, session_id)
        assert stop_task_id == task_id

        task = db.get_task(task_id)
        assert task.status == "action_required"

        # --- Step 4: session-start again (resume) changes status back to "working" ---
        resume_task_id = handle_session_start(db, session_id, project_dir, pid)
        assert resume_task_id == task_id  # same task reused

        task = db.get_task(task_id)
        assert task.status == "working"

        # Session should still be active
        session = db.get_session(session_id)
        assert session.is_active is True

        # --- Step 5: session-end marks task "done" and session inactive ---
        end_task_id = handle_session_end(db, session_id)
        assert end_task_id == task_id

        task = db.get_task(task_id)
        assert task.status == "done"
        assert task.completed_at is not None

        session = db.get_session(session_id)
        assert session.is_active is False
        assert session.ended_at is not None

    def test_timeline_events_recorded(self, db: Database) -> None:
        """Every lifecycle step should produce a timeline event."""
        session_id = "sess-timeline-001"
        project_dir = "/tmp/timeline-project"
        pid = 99999

        task_id = handle_session_start(db, session_id, project_dir, pid)
        handle_heartbeat(db, session_id)  # heartbeat does NOT add timeline event
        handle_stop(db, session_id)
        handle_session_start(db, session_id, project_dir, pid)
        handle_session_end(db, session_id)

        task = db.get_task(task_id)
        event_types = [e.event_type for e in task.timeline]

        # session_start (x2), blocked (stop), session_end
        assert event_types == [
            "session_start",
            "blocked",
            "session_start",
            "session_end",
        ]

    def test_session_active_inactive_states(self, db: Database) -> None:
        """Session should be active after start, inactive after end."""
        session_id = "sess-active-001"
        project_dir = "/tmp/active-project"
        pid = 11111

        handle_session_start(db, session_id, project_dir, pid)

        session = db.get_session(session_id)
        assert session.is_active is True

        handle_session_end(db, session_id)

        session = db.get_session(session_id)
        assert session.is_active is False

    def test_unknown_session_handlers_return_none(self, db: Database) -> None:
        """Handlers should return None for unknown sessions."""
        assert handle_heartbeat(db, "nonexistent") is None
        assert handle_stop(db, "nonexistent") is None
        assert handle_session_end(db, "nonexistent") is None
