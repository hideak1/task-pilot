import os
import tempfile
import time
from unittest.mock import patch, MagicMock
import pytest
from task_pilot.db import Database
from task_pilot.models import Session
from task_pilot.session_tracker import SessionTracker


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path)


def test_create_session_inserts_to_db_and_creates_window():
    db = make_db()
    fake_tmux = MagicMock()
    tracker = SessionTracker(db, tmux=fake_tmux, session_name="task-pilot")

    s = tracker.create_session(cwd="/tmp/proj")
    assert s.cwd == "/tmp/proj"
    assert db.get_session(s.id) is not None
    fake_tmux.new_window.assert_called_once()


def test_close_session_kills_window_and_deletes_from_db():
    db = make_db()
    fake_tmux = MagicMock()
    tracker = SessionTracker(db, tmux=fake_tmux, session_name="task-pilot")

    s = tracker.create_session(cwd="/tmp")
    tracker.close_session(s.id)
    assert db.get_session(s.id) is None
    fake_tmux.kill_window.assert_called()


def test_reconcile_removes_orphaned_db_records():
    db = make_db()
    db.insert_session(Session(
        id="ghost", tmux_window="_bg_ghost", cwd="/tmp",
        git_branch=None, started_at=0.0, title=None,
    ))
    fake_tmux = MagicMock()
    fake_tmux.list_windows.return_value = ["main"]  # ghost window doesn't exist
    fake_tmux.window_exists.return_value = True
    tracker = SessionTracker(db, tmux=fake_tmux, session_name="task-pilot")

    tracker.reconcile()
    assert db.get_session("ghost") is None


def test_reconcile_adopts_orphaned_tmux_windows():
    db = make_db()
    fake_tmux = MagicMock()
    fake_tmux.list_windows.return_value = ["main", "_bg_unknownuuid"]
    fake_tmux.window_exists.return_value = True
    fake_tmux.display_message.side_effect = lambda target, fmt: {
        "#{pane_current_path}": "/home/user/proj",
        "#{window_activity}": "1700000000",
    }.get(fmt, "")
    tracker = SessionTracker(db, tmux=fake_tmux, session_name="task-pilot")

    tracker.reconcile()
    s = db.get_session("unknownuuid")
    assert s is not None
    assert s.cwd == "/home/user/proj"


def test_switch_to_two_step_swap():
    db = make_db()
    db.insert_session(Session(
        id="A", tmux_window="_bg_A", cwd="/tmp",
        git_branch=None, started_at=0.0, title=None,
    ))
    db.insert_session(Session(
        id="B", tmux_window="_bg_B", cwd="/tmp",
        git_branch=None, started_at=0.0, title=None,
    ))
    db.set_current_session_id("A")
    fake_tmux = MagicMock()
    tracker = SessionTracker(db, tmux=fake_tmux, session_name="task-pilot")

    tracker.switch_to("B")
    # Two swap_pane calls: A back home, then B into main.1
    assert fake_tmux.swap_pane.call_count == 2
    assert db.get_current_session_id() == "B"


def test_switch_to_skips_step1_when_no_current():
    db = make_db()
    db.insert_session(Session(
        id="B", tmux_window="_bg_B", cwd="/tmp",
        git_branch=None, started_at=0.0, title=None,
    ))
    fake_tmux = MagicMock()
    tracker = SessionTracker(db, tmux=fake_tmux, session_name="task-pilot")

    tracker.switch_to("B")
    assert fake_tmux.swap_pane.call_count == 1
