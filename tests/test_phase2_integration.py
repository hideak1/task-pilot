"""Phase 2 integration: SessionTracker against real tmux + real DB + real files."""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from task_pilot import tmux
from task_pilot.db import Database
from task_pilot.models import Session
from task_pilot.session_tracker import SessionTracker
from task_pilot.transcript_reader import sum_tokens, last_activity_timestamp, extract_first_user_message

TEST_SESSION = "task-pilot-phase2-it"


@pytest.fixture
def real_tmux():
    if tmux.has_session(TEST_SESSION):
        tmux.kill_session(TEST_SESSION)
    tmux.new_session(TEST_SESSION)
    tmux.split_window(f"{TEST_SESSION}:main", percent=70, horizontal=True)
    yield
    if tmux.has_session(TEST_SESSION):
        tmux.kill_session(TEST_SESSION)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "phase2.db"
    return Database(db_path)


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_create_session_creates_real_tmux_window(db, real_tmux, tmp_path):
    tracker = SessionTracker(db, tmux=tmux, session_name=TEST_SESSION)
    s = tracker.create_session(cwd=str(tmp_path))
    # Verify DB
    assert db.get_session(s.id) is not None
    # Verify tmux window exists
    windows = tmux.list_windows(TEST_SESSION)
    assert s.tmux_window in windows
    # Cleanup
    tracker.close_session(s.id)


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_close_session_removes_window_and_db_record(db, real_tmux, tmp_path):
    tracker = SessionTracker(db, tmux=tmux, session_name=TEST_SESSION)
    s = tracker.create_session(cwd=str(tmp_path))
    sid = s.id
    tracker.close_session(sid)
    # DB record gone
    assert db.get_session(sid) is None
    # tmux window gone
    windows = tmux.list_windows(TEST_SESSION)
    assert s.tmux_window not in windows


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_two_step_swap_against_real_tmux(db, real_tmux, tmp_path):
    """The CRITICAL test: switch_to between two real sessions in real tmux,
    verifying that each session's pane returns to its home _bg window when not visible."""
    tracker = SessionTracker(db, tmux=tmux, session_name=TEST_SESSION)

    # Create two sessions running marker shells (NOT claude — claude isn't installed in test)
    # We'll simulate by inserting DB records and creating windows manually with markers
    s1 = Session(id="s1", tmux_window="_bg_s1", cwd=str(tmp_path),
                 git_branch=None, started_at=time.time(), title=None)
    s2 = Session(id="s2", tmux_window="_bg_s2", cwd=str(tmp_path),
                 git_branch=None, started_at=time.time(), title=None)
    db.insert_session(s1)
    db.insert_session(s2)
    tmux.new_window(TEST_SESSION, "_bg_s1", str(tmp_path), "sh -c 'echo S1_MARKER; sleep 60'")
    tmux.new_window(TEST_SESSION, "_bg_s2", str(tmp_path), "sh -c 'echo S2_MARKER; sleep 60'")
    time.sleep(0.5)

    # Switch to s1 (no current → single swap)
    tracker.switch_to("s1")
    cap = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:main.1"])
    assert "S1_MARKER" in cap.stdout
    assert db.get_current_session_id() == "s1"

    # Switch to s2 (current=s1 → two-step swap)
    tracker.switch_to("s2")
    cap = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:main.1"])
    assert "S2_MARKER" in cap.stdout
    assert db.get_current_session_id() == "s2"

    # Verify s1's pane is back home in _bg_s1
    cap = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:_bg_s1.0"])
    assert "S1_MARKER" in cap.stdout

    # Switch back to s1 — verify two-step swap goes the other direction
    tracker.switch_to("s1")
    cap = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:main.1"])
    assert "S1_MARKER" in cap.stdout

    # Verify s2's pane is now back in _bg_s2
    cap = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:_bg_s2.0"])
    assert "S2_MARKER" in cap.stdout


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_reconcile_drops_ghost_records(db, real_tmux):
    """DB has a session whose tmux window doesn't exist → drop from DB."""
    tracker = SessionTracker(db, tmux=tmux, session_name=TEST_SESSION)
    db.insert_session(Session(
        id="ghost", tmux_window="_bg_ghost", cwd="/tmp",
        git_branch=None, started_at=0.0, title=None,
    ))
    # ghost window does NOT exist in tmux
    tracker.reconcile()
    assert db.get_session("ghost") is None


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_reconcile_adopts_orphan_windows(db, real_tmux, tmp_path):
    """tmux has a _bg window with no DB record → adopt it."""
    tracker = SessionTracker(db, tmux=tmux, session_name=TEST_SESSION)
    tmux.new_window(TEST_SESSION, "_bg_orphan123", str(tmp_path), "sleep 60")
    time.sleep(0.3)
    tracker.reconcile()
    s = db.get_session("orphan123")
    assert s is not None
    assert s.cwd == str(tmp_path) or s.cwd == str(Path(tmp_path).resolve())


def test_transcript_reader_real_jsonl(tmp_path):
    """Verify transcript_reader handles a realistic Claude Code .jsonl file."""
    transcript = tmp_path / "session.jsonl"
    entries = [
        {"type": "user", "message": {"content": "Build me a REST API"},
         "timestamp": "2026-04-08T10:00:00Z"},
        {"type": "assistant", "message": {
            "content": "Sure!",
            "usage": {"input_tokens": 100, "output_tokens": 50,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        }, "timestamp": "2026-04-08T10:00:05Z"},
        {"type": "assistant", "message": {
            "content": "Done",
            "usage": {"input_tokens": 200, "output_tokens": 80,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        }, "timestamp": "2026-04-08T10:00:30Z"},
    ]
    with transcript.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    assert sum_tokens(transcript) == 100 + 50 + 200 + 80
    assert last_activity_timestamp(transcript) > 0
    assert extract_first_user_message(transcript) == "Build me a REST API"


def test_db_persistence_across_connections(tmp_path):
    """Insert a session, close DB, reopen, verify session is still there."""
    db_path = tmp_path / "persist.db"
    db1 = Database(db_path)
    db1.insert_session(Session(
        id="persist", tmux_window="_bg_persist", cwd="/tmp",
        git_branch="main", started_at=12345.0, title="Persistent",
    ))
    db1.set_current_session_id("persist")
    db1.close()

    db2 = Database(db_path)
    s = db2.get_session("persist")
    assert s is not None
    assert s.title == "Persistent"
    assert db2.get_current_session_id() == "persist"
