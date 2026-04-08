"""Phase 6 final end-to-end smoke test against REAL tmux."""

import os
import shutil
import subprocess
import time
import pytest

from task_pilot import tmux

TEST_SESSION = "task-pilot-final-e2e"


@pytest.fixture(autouse=True)
def cleanup():
    """Ensure test session is dead before and after."""
    if tmux.has_session(TEST_SESSION):
        tmux.kill_session(TEST_SESSION)
    yield
    if tmux.has_session(TEST_SESSION):
        tmux.kill_session(TEST_SESSION)


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_full_session_lifecycle_in_real_tmux(tmp_path):
    """Create session -> switch -> switch back -> close -- all in real tmux."""
    tmux.new_session(TEST_SESSION)
    tmux.split_window(f"{TEST_SESSION}:main", percent=70)

    from task_pilot.db import Database
    from task_pilot.models import Session
    from task_pilot.session_tracker import SessionTracker

    db = Database(tmp_path / "e2e.db")
    tracker = SessionTracker(db, tmux=tmux, session_name=TEST_SESSION)

    # Create A
    db.insert_session(Session(
        id="A", tmux_window="_bg_A", cwd=str(tmp_path),
        git_branch=None, started_at=time.time(), title="Session A",
    ))
    tmux.new_window(TEST_SESSION, "_bg_A", str(tmp_path),
                    "sh -c 'echo A_TOKEN; sleep 60'")

    # Create B
    db.insert_session(Session(
        id="B", tmux_window="_bg_B", cwd=str(tmp_path),
        git_branch=None, started_at=time.time(), title="Session B",
    ))
    tmux.new_window(TEST_SESSION, "_bg_B", str(tmp_path),
                    "sh -c 'echo B_TOKEN; sleep 60'")

    time.sleep(0.5)

    # Switch to A
    tracker.switch_to("A")
    cap = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:main.1"])
    assert "A_TOKEN" in cap.stdout
    assert db.get_current_session_id() == "A"

    # Switch to B (two-step swap)
    tracker.switch_to("B")
    cap = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:main.1"])
    assert "B_TOKEN" in cap.stdout
    cap_a_home = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:_bg_A.0"])
    assert "A_TOKEN" in cap_a_home.stdout

    # Switch back to A
    tracker.switch_to("A")
    cap = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:main.1"])
    assert "A_TOKEN" in cap.stdout
    cap_b_home = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:_bg_B.0"])
    assert "B_TOKEN" in cap_b_home.stdout

    # Close A while it's visible.
    tracker.close_session("A")
    assert db.get_session("A") is None
    assert "_bg_A" not in tmux.list_windows(TEST_SESSION)

    # B is still alive
    assert db.get_session("B") is not None
    assert "_bg_B" in tmux.list_windows(TEST_SESSION)


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_reconcile_after_pilot_restart(tmp_path):
    """Simulate pilot crash + restart: reconcile should adopt orphan windows."""
    tmux.new_session(TEST_SESSION)

    from task_pilot.db import Database
    from task_pilot.session_tracker import SessionTracker

    tmux.new_window(TEST_SESSION, "_bg_orphan-uuid", str(tmp_path),
                    "sleep 60")
    time.sleep(0.3)

    db = Database(tmp_path / "after_crash.db")
    tracker = SessionTracker(db, tmux=tmux, session_name=TEST_SESSION)
    tracker.reconcile()

    s = db.get_session("orphan-uuid")
    assert s is not None
    assert s.tmux_window == "_bg_orphan-uuid"
