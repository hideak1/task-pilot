"""Real tmux integration tests for Phase 1.

These tests actually invoke tmux and create real sessions. They are
isolated by using a unique session name per test and tearing down in
finally blocks. Skipped if tmux is not installed.
"""

import shutil
import subprocess
import time
import pytest

from task_pilot import tmux

TEST_SESSION = "task-pilot-phase1-integration-test"


@pytest.fixture(autouse=True)
def cleanup():
    """Ensure test session is killed before and after each test."""
    if tmux.has_session(TEST_SESSION):
        tmux.kill_session(TEST_SESSION)
    yield
    if tmux.has_session(TEST_SESSION):
        tmux.kill_session(TEST_SESSION)


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_create_and_kill_session():
    tmux.new_session(TEST_SESSION)
    assert tmux.has_session(TEST_SESSION)
    tmux.kill_session(TEST_SESSION)
    assert not tmux.has_session(TEST_SESSION)


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_split_window_creates_two_panes():
    tmux.new_session(TEST_SESSION)
    tmux.split_window(f"{TEST_SESSION}:main", percent=70, horizontal=True)
    # List panes
    result = tmux.run(["list-panes", "-t", f"{TEST_SESSION}:main", "-F", "#{pane_index}"])
    panes = result.stdout.strip().split("\n")
    assert len(panes) == 2


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_new_window_creates_separate_window():
    tmux.new_session(TEST_SESSION)
    tmux.new_window(TEST_SESSION, "_bg_test", "/tmp", "sleep 60")
    windows = tmux.list_windows(TEST_SESSION)
    assert "main" in windows
    assert "_bg_test" in windows


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_swap_pane_two_step_protocol_preserves_invariant():
    """Verify the two-step swap protocol keeps each session's pane in its home _bg window when not visible."""
    tmux.new_session(TEST_SESSION)
    # Initial main has 1 pane (left). Add right pane as placeholder.
    tmux.split_window(f"{TEST_SESSION}:main", percent=70, horizontal=True)

    # Create _bg_A and _bg_B with marker commands
    tmux.new_window(TEST_SESSION, "_bg_A", "/tmp", "sh -c 'echo A_MARKER; sleep 60'")
    tmux.new_window(TEST_SESSION, "_bg_B", "/tmp", "sh -c 'echo B_MARKER; sleep 60'")
    time.sleep(0.5)  # let commands run

    # Bring A into main.1 (single swap, since nothing was in main.1 before from a session)
    tmux.swap_pane(f"{TEST_SESSION}:main.1", f"{TEST_SESSION}:_bg_A.0")

    # Capture main.1 — should show A_MARKER
    cap = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:main.1"])
    assert "A_MARKER" in cap.stdout

    # Two-step swap to switch from A to B:
    # Step 1: return A to its home _bg_A
    tmux.swap_pane(f"{TEST_SESSION}:main.1", f"{TEST_SESSION}:_bg_A.0")
    # Step 2: bring B into main.1
    tmux.swap_pane(f"{TEST_SESSION}:main.1", f"{TEST_SESSION}:_bg_B.0")

    # Now main.1 should show B_MARKER, and _bg_A.0 should show A_MARKER
    cap_main = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:main.1"])
    assert "B_MARKER" in cap_main.stdout

    cap_a = tmux.run(["capture-pane", "-p", "-t", f"{TEST_SESSION}:_bg_A.0"])
    assert "A_MARKER" in cap_a.stdout


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_kill_window_does_not_kill_session():
    tmux.new_session(TEST_SESSION)
    tmux.new_window(TEST_SESSION, "_bg_doomed", "/tmp", "sleep 60")
    assert "_bg_doomed" in tmux.list_windows(TEST_SESSION)
    tmux.kill_window(f"{TEST_SESSION}:_bg_doomed")
    time.sleep(0.2)
    windows = tmux.list_windows(TEST_SESSION)
    assert "_bg_doomed" not in windows
    assert tmux.has_session(TEST_SESSION)  # session still alive


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_display_message_returns_pane_path():
    tmux.new_session(TEST_SESSION)
    tmux.new_window(TEST_SESSION, "_bg_x", "/tmp", "sleep 60")
    cwd = tmux.display_message(f"{TEST_SESSION}:_bg_x.0", "#{pane_current_path}")
    # macOS resolves /tmp -> /private/tmp, so accept either
    assert cwd in ("/tmp", "/private/tmp")
