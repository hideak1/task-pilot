# Task Pilot Tmux Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Task Pilot's hooks+scanner architecture with a tmux-based orchestration model where pilot launches Claude Code sessions in tmux windows and uses a two-step swap-pane protocol to switch which session is visible on the right.

**Architecture:** Single tmux session `task-pilot` with one always-visible `main` window (left = pilot Textual app, right = currently selected Claude Code) and N hidden `_bg_<uuid>` windows holding the other sessions. SQLite stores persistent session metadata; runtime state (tokens, activity, status) is recomputed every 2 seconds from `~/.claude/projects/<slug>/<session>.jsonl`.

**Tech Stack:** Python 3.11+, Textual, tmux 3.0+, SQLite, psutil, Click. No Claude Code hooks. No `claude --print` calls.

**Spec:** `docs/superpowers/specs/2026-04-08-tmux-rewrite-design.md`

---

## Pre-Phase: Setup

- [ ] **Step 1: Confirm clean working tree**

```bash
cd /Users/liuhongxuan/project/task_management
git status
```

Expected: clean working tree on `main`, no uncommitted changes.

- [ ] **Step 2: Add psutil dependency**

Edit `pyproject.toml`, add to `dependencies`:
```toml
"psutil>=5.9",
```

- [ ] **Step 3: Install psutil**

```bash
uv pip install -e .
```

Expected: `psutil` installed.

- [ ] **Step 4: Verify baseline tests still pass**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 106 passed (the v0.1 test suite). This is the baseline; many tests will be deleted or rewritten in Phase 2+.

- [ ] **Step 5: Commit setup**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add psutil dependency for tmux rewrite"
```

---

## Phase 1: Tmux Control Layer + Launcher

**Goal:** `task-pilot ui` creates a tmux session named `task-pilot` with a horizontal split. Left pane shows a placeholder script, right pane shows a placeholder shell. Re-running attaches. `task-pilot kill` tears it down. Verifies tmux orchestration before any UI lands.

### Task 1.1: tmux command wrapper

**Files:**
- Create: `src/task_pilot/tmux.py`
- Create: `tests/test_tmux.py`

- [ ] **Step 1: Write the failing test (existence + smoke)**

```python
# tests/test_tmux.py
from unittest.mock import patch, MagicMock
import pytest
from task_pilot import tmux


def test_run_calls_subprocess():
    with patch("task_pilot.tmux.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = tmux.run(["list-sessions"])
        mock.assert_called_once()
        assert result.stdout == "ok\n"


def test_has_session_true():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="", stderr="")
        assert tmux.has_session("task-pilot") is True


def test_has_session_false():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=1, stdout="", stderr="no such session")
        assert tmux.has_session("task-pilot") is False


def test_list_windows_filters_format():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(
            returncode=0,
            stdout="main\n_bg_abc123\n_bg_def456\n",
            stderr="",
        )
        windows = tmux.list_windows("task-pilot")
        assert windows == ["main", "_bg_abc123", "_bg_def456"]


def test_window_exists_true():
    with patch("task_pilot.tmux.list_windows") as mock:
        mock.return_value = ["main", "_bg_abc"]
        assert tmux.window_exists("task-pilot", "main") is True


def test_window_exists_false():
    with patch("task_pilot.tmux.list_windows") as mock:
        mock.return_value = ["main"]
        assert tmux.window_exists("task-pilot", "_bg_xxx") is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_tmux.py -v
```
Expected: FAIL (`task_pilot.tmux` does not exist).

- [ ] **Step 3: Implement minimal `tmux.py`**

```python
# src/task_pilot/tmux.py
"""Thin wrapper around the tmux CLI.

All functions assume a tmux binary is available in PATH. The launcher
should run shutil.which("tmux") before calling anything here.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Iterable

logger = logging.getLogger(__name__)


def run(args: Iterable[str], check: bool = False) -> subprocess.CompletedProcess:
    """Run `tmux <args>` and return the CompletedProcess.

    With check=False (default), failures are returned to the caller; with
    check=True, raises CalledProcessError on non-zero exit.
    """
    cmd = ["tmux", *args]
    logger.debug("tmux %s", " ".join(args))
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def has_session(session: str) -> bool:
    """Return True iff a tmux session with the given name exists."""
    return run(["has-session", "-t", session]).returncode == 0


def list_windows(session: str) -> list[str]:
    """Return a list of window names for the given tmux session."""
    result = run(["list-windows", "-t", session, "-F", "#{window_name}"])
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.strip().splitlines() if line]


def window_exists(session: str, window: str) -> bool:
    """Return True iff a window with the given name exists in the session."""
    return window in list_windows(session)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_tmux.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Add window/pane management functions**

Append to `src/task_pilot/tmux.py`:

```python
def new_session(name: str, window_name: str = "main", width: int = 200, height: int = 50) -> None:
    """Create a new detached tmux session."""
    run(["new-session", "-d", "-s", name, "-n", window_name, "-x", str(width), "-y", str(height)], check=True)


def kill_session(name: str) -> None:
    """Kill an entire tmux session and all its windows."""
    run(["kill-session", "-t", name])


def split_window(target: str, percent: int = 70, horizontal: bool = True) -> None:
    """Split a window. -h means horizontal split (left/right), -v vertical (top/bottom)."""
    flag = "-h" if horizontal else "-v"
    run(["split-window", flag, "-t", target, "-l", f"{percent}%"], check=True)


def send_keys(target: str, text: str, enter: bool = True) -> None:
    """Send text to the target pane. If enter=True, also send the Enter key."""
    args = ["send-keys", "-t", target, text]
    if enter:
        args.append("Enter")
    run(args, check=True)


def new_window(session: str, name: str, cwd: str, command: str) -> None:
    """Create a new background window running the given command in cwd."""
    run(["new-window", "-d", "-t", session, "-n", name, "-c", cwd, command], check=True)


def kill_window(target: str) -> None:
    """Kill a single window. Other windows in the session are unaffected."""
    run(["kill-window", "-t", target])


def swap_pane(src: str, dst: str) -> None:
    """Swap two panes. Each child process stays alive in its new location."""
    run(["swap-pane", "-s", src, "-t", dst], check=True)


def set_option(session: str, option: str, value: str, global_opt: bool = False) -> None:
    """Set a tmux option on the given session."""
    args = ["set"]
    if global_opt:
        args.append("-g")
    args.extend(["-t", session, option, value])
    run(args, check=True)


def display_message(target: str, format_string: str) -> str:
    """Run `tmux display-message -p -t <target> <format>` and return the output."""
    result = run(["display-message", "-p", "-t", target, format_string])
    return result.stdout.strip() if result.returncode == 0 else ""
```

- [ ] **Step 6: Write tests for the new functions**

Append to `tests/test_tmux.py`:

```python
def test_new_session_calls_correct_args():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.new_session("task-pilot")
        args = mock.call_args[0][0]
        assert args[:3] == ["new-session", "-d", "-s"]
        assert "task-pilot" in args


def test_split_window_horizontal_70_percent():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.split_window("task-pilot:main", percent=70)
        args = mock.call_args[0][0]
        assert "-h" in args
        assert "70%" in args


def test_swap_pane_calls_correct_args():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.swap_pane("task-pilot:main.1", "task-pilot:_bg_abc.0")
        args = mock.call_args[0][0]
        assert args[0] == "swap-pane"
        assert "-s" in args
        assert "-t" in args


def test_kill_window_passes_target():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.kill_window("task-pilot:_bg_xyz")
        args = mock.call_args[0][0]
        assert args == ["kill-window", "-t", "task-pilot:_bg_xyz"]


def test_send_keys_with_enter():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.send_keys("task-pilot:main.0", "echo hi")
        args = mock.call_args[0][0]
        assert args == ["send-keys", "-t", "task-pilot:main.0", "echo hi", "Enter"]


def test_display_message_returns_stripped():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="/home/user\n", stderr="")
        result = tmux.display_message("task-pilot:_bg_x.0", "#{pane_current_path}")
        assert result == "/home/user"
```

- [ ] **Step 7: Run tests**

```bash
.venv/bin/pytest tests/test_tmux.py -v
```
Expected: 12 passed.

- [ ] **Step 8: Commit**

```bash
git add src/task_pilot/tmux.py tests/test_tmux.py
git commit -m "feat: tmux command wrapper for Phase 1"
```

### Task 1.2: Launcher with bootstrap and reattach

**Files:**
- Create: `src/task_pilot/launcher.py`
- Create: `tests/test_launcher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_launcher.py
import os
from unittest.mock import patch, MagicMock
import pytest
from task_pilot import launcher


def test_pre_flight_passes_when_tmux_and_claude_installed():
    with patch("task_pilot.launcher.shutil.which") as mock_which:
        mock_which.side_effect = lambda b: "/usr/bin/" + b
        # Should not raise
        launcher.pre_flight_checks()


def test_pre_flight_dies_when_tmux_missing():
    with patch("task_pilot.launcher.shutil.which") as mock_which:
        mock_which.side_effect = lambda b: None if b == "tmux" else "/usr/bin/" + b
        with pytest.raises(SystemExit):
            launcher.pre_flight_checks()


def test_pre_flight_dies_when_claude_missing():
    with patch("task_pilot.launcher.shutil.which") as mock_which:
        mock_which.side_effect = lambda b: None if b == "claude" else "/usr/bin/" + b
        with pytest.raises(SystemExit):
            launcher.pre_flight_checks()


def test_bootstrap_calls_tmux_in_correct_order():
    calls = []
    fakes = {
        "new_session": lambda *a, **kw: calls.append(("new_session", a, kw)),
        "set_option":  lambda *a, **kw: calls.append(("set_option", a, kw)),
        "split_window": lambda *a, **kw: calls.append(("split_window", a, kw)),
        "send_keys":   lambda *a, **kw: calls.append(("send_keys", a, kw)),
    }
    with patch.multiple("task_pilot.launcher.tmux", **fakes):
        launcher.bootstrap_tmux_session()
    op_names = [c[0] for c in calls]
    assert op_names[0] == "new_session"
    assert "split_window" in op_names
    assert "send_keys" in op_names
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_launcher.py -v
```
Expected: FAIL (`task_pilot.launcher` does not exist).

- [ ] **Step 3: Implement `launcher.py`**

```python
# src/task_pilot/launcher.py
"""Launcher: bootstrap or attach to the task-pilot tmux session."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from task_pilot import tmux

SESSION_NAME = "task-pilot"
PLACEHOLDER_LEFT = "echo 'pilot placeholder — Phase 1'"
PLACEHOLDER_RIGHT = "echo 'right pane placeholder — Phase 1'"


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def pre_flight_checks() -> None:
    """Verify required external binaries are present, exit otherwise."""
    if not shutil.which("tmux"):
        die("tmux is not installed. Install via your package manager.")
    if not shutil.which("claude"):
        die("claude CLI not found in PATH. Install Claude Code first.")


def get_outer_tmux_session() -> str | None:
    """If we're inside tmux, return the outer session name; else None."""
    if not os.environ.get("TMUX"):
        return None
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


def bootstrap_tmux_session() -> None:
    """Create the task-pilot tmux session from scratch."""
    tmux.new_session(SESSION_NAME, window_name="main", width=200, height=50)
    tmux.set_option(SESSION_NAME, "mouse", "on")
    tmux.set_option(SESSION_NAME, "status", "off", global_opt=True)
    # Disable mouse-wheel copy-mode trap
    tmux.run(["set-option", "-t", SESSION_NAME, "-g", "@disable-copy-mode-on-wheel", "on"])
    tmux.split_window(f"{SESSION_NAME}:main", percent=70, horizontal=True)
    # Phase 1 placeholders
    tmux.send_keys(f"{SESSION_NAME}:main.0", PLACEHOLDER_LEFT)
    tmux.send_keys(f"{SESSION_NAME}:main.1", PLACEHOLDER_RIGHT)


def main() -> None:
    """Entry point: ensure pilot's tmux session is running and attach to it."""
    pre_flight_checks()

    outer = get_outer_tmux_session()

    if outer == SESSION_NAME:
        # Developer mode — already inside our session, run the textual app
        # (Phase 1: just print, Phase 3+ will run textual)
        print("Already inside task-pilot session. Phase 1 placeholder.")
        return

    if outer is not None:
        # Inside some other tmux session
        if tmux.has_session(SESSION_NAME):
            print(f"You are inside tmux session '{outer}'.")
            print(f"To switch:  tmux switch-client -t {SESSION_NAME}")
            print(f"Or detach (Ctrl-b d), then re-run task-pilot ui")
        else:
            print(f"You are inside tmux session '{outer}'.")
            print(f"Detach first (Ctrl-b d), then run task-pilot ui")
        sys.exit(1)

    # Not in tmux at all
    if not tmux.has_session(SESSION_NAME):
        bootstrap_tmux_session()
    os.execvp("tmux", ["tmux", "attach", "-t", SESSION_NAME])


def cmd_kill() -> None:
    """`task-pilot kill` — tear down the entire tmux session."""
    if tmux.has_session(SESSION_NAME):
        tmux.kill_session(SESSION_NAME)
        print(f"Killed tmux session '{SESSION_NAME}'.")
    else:
        print(f"No tmux session named '{SESSION_NAME}'.")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_launcher.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/task_pilot/launcher.py tests/test_launcher.py
git commit -m "feat: launcher with pre-flight checks and tmux bootstrap"
```

### Task 1.3: Wire CLI to launcher

**Files:**
- Modify: `src/task_pilot/cli.py`

- [ ] **Step 1: Replace cli.py with the Phase 1 version**

```python
# src/task_pilot/cli.py
"""Task Pilot CLI entry point."""

import click

from task_pilot import launcher


@click.group()
def main():
    """Task Pilot — Claude Code session dispatcher panel."""
    pass


@main.command()
def ui():
    """Bootstrap or attach to the task-pilot tmux session."""
    launcher.main()


@main.command()
def kill():
    """Kill the task-pilot tmux session and everything inside it."""
    launcher.cmd_kill()
```

- [ ] **Step 2: Verify it imports**

```bash
.venv/bin/python -c "from task_pilot.cli import main; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Manual smoke test**

```bash
# In a real terminal (NOT inside another tmux):
uv run task-pilot ui
```
Expected: tmux opens, left pane shows `pilot placeholder — Phase 1`, right pane shows `right pane placeholder — Phase 1`. Press `Ctrl-b d` to detach.

```bash
uv run task-pilot ui     # second run — should attach to existing session
uv run task-pilot kill   # tear it down
```

- [ ] **Step 4: Commit**

```bash
git add src/task_pilot/cli.py
git commit -m "feat: wire cli to launcher (Phase 1 ui + kill commands)"
```

### Task 1.4: Phase 1 cleanup of obsolete code

**Files:**
- Delete: `src/task_pilot/hooks.py`
- Delete: `src/task_pilot/scanner.py`
- Delete: `src/task_pilot/screens/detail_screen.py`
- Delete: `src/task_pilot/screens/list_screen.py`
- Delete: `src/task_pilot/widgets/action_steps.py`
- Delete: `src/task_pilot/widgets/timeline.py`
- Delete: `src/task_pilot/widgets/header_bar.py`
- Delete: `src/task_pilot/widgets/task_row.py`
- Delete: `src/task_pilot/app.py`
- Delete: `src/task_pilot/summarizer.py` (gone for good — title extraction lives in transcript_reader.py)
- Delete: corresponding `tests/test_*.py` files

- [ ] **Step 1: Delete v0.1 source files**

```bash
rm src/task_pilot/hooks.py
rm src/task_pilot/scanner.py
rm src/task_pilot/screens/detail_screen.py
rm src/task_pilot/screens/list_screen.py
rm src/task_pilot/widgets/action_steps.py
rm src/task_pilot/widgets/timeline.py
rm src/task_pilot/widgets/header_bar.py
rm src/task_pilot/widgets/task_row.py
rm src/task_pilot/app.py
```

- [ ] **Step 2: Delete v0.1 test files**

```bash
rm tests/test_hooks.py
rm tests/test_scanner.py
rm tests/test_summarizer.py
rm tests/test_integration_cli.py
rm tests/test_e2e.py
rm tests/test_tui.py
rm tests/test_cli.py
```

(`test_models.py` and `test_db.py` will be rewritten in Phase 2; leave for now but they will fail.)

- [ ] **Step 3: Empty out models.py and db.py**

These will be rewritten in Phase 2. For now, replace their contents so the package still imports:

```python
# src/task_pilot/models.py
"""Placeholder; rewritten in Phase 2."""
```

```python
# src/task_pilot/db.py
"""Placeholder; rewritten in Phase 2."""
```

- [ ] **Step 4: Delete the old test_models.py and test_db.py contents**

```bash
rm tests/test_models.py
rm tests/test_db.py
```

- [ ] **Step 5: Run remaining tests**

```bash
.venv/bin/pytest tests/ -v
```
Expected: only `test_tmux.py` (12) and `test_launcher.py` (4) run, all pass. 16 total.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: delete v0.1 hooks/scanner/screens to make way for tmux rewrite"
```

### Task 1.5: Manual end-to-end Phase 1 verification

- [ ] **Step 1: From a non-tmux terminal, run pilot**

```bash
uv run task-pilot ui
```

Expected:
- A new tmux session opens
- Left pane (~30%) shows `pilot placeholder — Phase 1`
- Right pane (~70%) shows `right pane placeholder — Phase 1`
- Status bar at the bottom is hidden
- Mouse mode is enabled (clicking different panes moves focus)

- [ ] **Step 2: Detach with `Ctrl-b d`, then re-run**

```bash
uv run task-pilot ui
```

Expected: attaches back to the same tmux session, both placeholders still visible.

- [ ] **Step 3: From inside the task-pilot tmux session, run pilot again**

In a tmux pane inside `task-pilot`:
```bash
uv run task-pilot ui
```

Expected: prints `Already inside task-pilot session. Phase 1 placeholder.` and exits. No nested tmux.

- [ ] **Step 4: Detach and from another (non-task-pilot) tmux session, try to run**

```bash
tmux new-session -s some-other
# inside the new session:
uv run task-pilot ui
```

Expected: prints actionable guidance about `tmux switch-client -t task-pilot` or detaching, exits 1.

- [ ] **Step 5: Kill from outside**

```bash
# detach from any tmux session first
uv run task-pilot kill
```

Expected: prints `Killed tmux session 'task-pilot'.`

- [ ] **Step 6: Phase 1 done — tag commit**

```bash
git tag phase-1-complete
```

---

## Phase 2: Data Layer + Session Tracker

**Goal:** Persistent storage for sessions, runtime state computation from transcripts, and reconciliation logic. All pure Python, no UI.

### Task 2.1: Models (Session + SessionState dataclasses)

**Files:**
- Modify: `src/task_pilot/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from pathlib import Path
import time
from task_pilot.models import Session, SessionState


def test_session_creation():
    s = Session(
        id="abc123",
        tmux_window="_bg_abc123",
        cwd="/tmp/proj",
        git_branch="main",
        started_at=time.time(),
        title=None,
    )
    assert s.id == "abc123"
    assert s.git_branch == "main"


def test_session_optional_fields_default_to_none():
    s = Session(
        id="x",
        tmux_window="_bg_x",
        cwd="/tmp",
        git_branch=None,
        started_at=0.0,
        title=None,
    )
    assert s.title is None
    assert s.git_branch is None


def test_session_state_defaults():
    state = SessionState(session_id="abc")
    assert state.is_alive is True
    assert state.token_count == 0
    assert state.status == "initializing"
    assert state.transcript_path is None


def test_session_state_with_values():
    state = SessionState(
        session_id="abc",
        is_alive=True,
        last_activity=12345.0,
        token_count=4500,
        claude_session_id="claude-uuid",
        transcript_path=Path("/tmp/x.jsonl"),
        status="working",
    )
    assert state.token_count == 4500
    assert state.status == "working"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_models.py -v
```
Expected: FAIL (Session/SessionState not defined).

- [ ] **Step 3: Implement `models.py`**

```python
# src/task_pilot/models.py
"""Dataclasses for Task Pilot's session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Session:
    """Persistent state — exactly one row in the `sessions` table."""
    id: str
    tmux_window: str
    cwd: str
    git_branch: str | None
    started_at: float
    title: str | None


@dataclass
class SessionState:
    """Runtime state — owned by SessionTracker, never persisted."""
    session_id: str
    is_alive: bool = True
    last_activity: float = 0.0
    token_count: int = 0
    claude_session_id: str | None = None
    transcript_path: Path | None = None
    status: str = "initializing"  # initializing | working | idle | unknown
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_models.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/task_pilot/models.py tests/test_models.py
git commit -m "feat: Session and SessionState dataclasses"
```

### Task 2.2: SQLite Database layer

**Files:**
- Modify: `src/task_pilot/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py
import os
import tempfile
import time
import pytest
from task_pilot.db import Database
from task_pilot.models import Session


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path)


def test_insert_and_get_session():
    db = make_db()
    s = Session(
        id="abc", tmux_window="_bg_abc", cwd="/tmp",
        git_branch="main", started_at=time.time(), title="hello",
    )
    db.insert_session(s)
    got = db.get_session("abc")
    assert got is not None
    assert got.id == "abc"
    assert got.title == "hello"


def test_get_session_returns_none_when_missing():
    db = make_db()
    assert db.get_session("nope") is None


def test_list_sessions_returns_all():
    db = make_db()
    for i in range(3):
        db.insert_session(Session(
            id=f"s{i}", tmux_window=f"_bg_s{i}", cwd="/tmp",
            git_branch=None, started_at=time.time() + i, title=None,
        ))
    sessions = db.list_sessions()
    assert len(sessions) == 3
    assert {s.id for s in sessions} == {"s0", "s1", "s2"}


def test_delete_session():
    db = make_db()
    db.insert_session(Session(
        id="x", tmux_window="_bg_x", cwd="/tmp",
        git_branch=None, started_at=0.0, title=None,
    ))
    db.delete_session("x")
    assert db.get_session("x") is None


def test_update_title_and_branch():
    db = make_db()
    db.insert_session(Session(
        id="x", tmux_window="_bg_x", cwd="/tmp",
        git_branch=None, started_at=0.0, title=None,
    ))
    db.update_session("x", title="New title", git_branch="main")
    s = db.get_session("x")
    assert s.title == "New title"
    assert s.git_branch == "main"


def test_pilot_state_set_and_get():
    db = make_db()
    db.set_state("current_session_id", "abc")
    assert db.get_state("current_session_id") == "abc"


def test_pilot_state_returns_none_when_unset():
    db = make_db()
    assert db.get_state("anything") is None


def test_clear_state():
    db = make_db()
    db.set_state("k", "v")
    db.clear_state("k")
    assert db.get_state("k") is None


def test_current_session_helpers():
    db = make_db()
    db.set_current_session_id("abc")
    assert db.get_current_session_id() == "abc"
    db.clear_current_session()
    assert db.get_current_session_id() is None


def test_cwd_default_is_root():
    db = make_db()
    db.insert_session(Session(
        id="x", tmux_window="_bg_x", cwd="/",
        git_branch=None, started_at=0.0, title=None,
    ))
    assert db.get_session("x").cwd == "/"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_db.py -v
```
Expected: FAIL (Database class not defined).

- [ ] **Step 3: Implement `db.py`**

```python
# src/task_pilot/db.py
"""SQLite persistence for Task Pilot."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from task_pilot.models import Session

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    tmux_window     TEXT NOT NULL UNIQUE,
    cwd             TEXT NOT NULL DEFAULT '/',
    git_branch      TEXT,
    started_at      REAL NOT NULL,
    title           TEXT
);

CREATE TABLE IF NOT EXISTS pilot_state (
    key             TEXT PRIMARY KEY,
    value           TEXT
);
"""


class Database:
    def __init__(self, db_path: str | Path):
        self.path = str(db_path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ── sessions ─────────────────────────────────────────────

    def insert_session(self, s: Session) -> None:
        self.conn.execute(
            """INSERT INTO sessions
               (id, tmux_window, cwd, git_branch, started_at, title)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (s.id, s.tmux_window, s.cwd, s.git_branch, s.started_at, s.title),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(self) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY started_at"
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.conn.commit()
        if self.get_current_session_id() == session_id:
            self.clear_current_session()

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        git_branch: str | None = None,
    ) -> None:
        # Build dynamic update for whichever fields were provided
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if git_branch is not None:
            updates.append("git_branch = ?")
            params.append(git_branch)
        if not updates:
            return
        params.append(session_id)
        self.conn.execute(
            f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        self.conn.commit()

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            tmux_window=row["tmux_window"],
            cwd=row["cwd"],
            git_branch=row["git_branch"],
            started_at=row["started_at"],
            title=row["title"],
        )

    # ── pilot_state ──────────────────────────────────────────

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO pilot_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM pilot_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def clear_state(self, key: str) -> None:
        self.conn.execute("DELETE FROM pilot_state WHERE key = ?", (key,))
        self.conn.commit()

    # convenience helpers
    def set_current_session_id(self, session_id: str) -> None:
        self.set_state("current_session_id", session_id)

    def get_current_session_id(self) -> str | None:
        return self.get_state("current_session_id")

    def clear_current_session(self) -> None:
        self.clear_state("current_session_id")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_db.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/task_pilot/db.py tests/test_db.py
git commit -m "feat: SQLite database layer for sessions and pilot_state"
```

### Task 2.3: Transcript reader

**Files:**
- Create: `src/task_pilot/transcript_reader.py`
- Create: `tests/test_transcript_reader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transcript_reader.py
import json
from pathlib import Path
from task_pilot.transcript_reader import (
    sum_tokens,
    last_activity_timestamp,
    extract_first_user_message,
)


def make_jsonl(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "session.jsonl"
    with path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def test_sum_tokens_basic(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user", "message": {"content": "hi"}},
        {"type": "assistant", "message": {
            "usage": {"input_tokens": 10, "output_tokens": 20,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        }},
        {"type": "assistant", "message": {
            "usage": {"input_tokens": 5, "output_tokens": 7,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        }},
    ])
    assert sum_tokens(path) == 10 + 20 + 5 + 7


def test_sum_tokens_handles_missing_usage(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "assistant", "message": {"content": "no usage field"}},
    ])
    assert sum_tokens(path) == 0


def test_sum_tokens_returns_zero_for_missing_file(tmp_path):
    assert sum_tokens(tmp_path / "missing.jsonl") == 0


def test_last_activity_timestamp(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user", "timestamp": "2026-04-08T12:00:00Z"},
        {"type": "assistant", "timestamp": "2026-04-08T12:01:00Z"},
    ])
    ts = last_activity_timestamp(path)
    assert ts > 0


def test_last_activity_timestamp_falls_back_to_file_mtime(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user"},  # no timestamp field
    ])
    ts = last_activity_timestamp(path)
    assert ts > 0  # uses mtime


def test_extract_first_user_message(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user", "message": {"content": "Build a REST API"}},
        {"type": "assistant", "message": {"content": "OK"}},
    ])
    assert extract_first_user_message(path) == "Build a REST API"


def test_extract_first_user_message_handles_list_content(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "hi there"}]}},
    ])
    assert extract_first_user_message(path) == "hi there"


def test_extract_first_user_message_returns_none_when_no_user(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "assistant", "message": {"content": "hi"}},
    ])
    assert extract_first_user_message(path) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_transcript_reader.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `transcript_reader.py`**

```python
# src/task_pilot/transcript_reader.py
"""Read Claude Code transcript .jsonl files for tokens, activity, and titles."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def _iter_records(path: Path):
    """Yield parsed JSON records from a .jsonl file. Skip malformed lines."""
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def sum_tokens(path: Path) -> int:
    """Sum input + output + cache tokens across all assistant messages.

    Note: this approximates Claude's billing — exact counts depend on the
    Anthropic API's accounting which we cannot reproduce without recomputation.
    """
    total = 0
    for record in _iter_records(path):
        if record.get("type") != "assistant":
            continue
        message = record.get("message") or {}
        usage = message.get("usage") or {}
        total += usage.get("input_tokens", 0) or 0
        total += usage.get("output_tokens", 0) or 0
        total += usage.get("cache_creation_input_tokens", 0) or 0
        total += usage.get("cache_read_input_tokens", 0) or 0
    return total


def last_activity_timestamp(path: Path) -> float:
    """Return Unix timestamp of the last message, or file mtime as fallback."""
    last_ts = 0.0
    for record in _iter_records(path):
        ts_str = record.get("timestamp")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            last_ts = dt.timestamp()
        except (ValueError, TypeError):
            continue
    if last_ts > 0:
        return last_ts
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _get_text_content(message: dict) -> str:
    """Extract text from a message that may have string or list-of-blocks content."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def extract_first_user_message(path: Path) -> str | None:
    """Return the text of the first user message, or None if not found."""
    for record in _iter_records(path):
        if record.get("type") not in ("user", "human"):
            continue
        text = _get_text_content(record.get("message") or {})
        if text:
            return text
    return None
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_transcript_reader.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/task_pilot/transcript_reader.py tests/test_transcript_reader.py
git commit -m "feat: transcript reader for tokens, activity, and titles"
```

### Task 2.4: Session tracker (lifecycle + reconciliation)

**Files:**
- Create: `src/task_pilot/session_tracker.py`
- Create: `tests/test_session_tracker.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_session_tracker.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_session_tracker.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `session_tracker.py`**

```python
# src/task_pilot/session_tracker.py
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
        if current_id and current_id != target_id:
            current = self.db.get_session(current_id)
            if current:
                self.tmux.swap_pane(
                    f"{self.session_name}:main.1",
                    f"{self.session_name}:{current.tmux_window}.0",
                )
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
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_session_tracker.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/task_pilot/session_tracker.py tests/test_session_tracker.py
git commit -m "feat: session tracker with two-step swap and reconciliation"
```

### Task 2.5: Phase 2 verification

- [ ] **Step 1: Run all Phase 1+2 tests together**

```bash
.venv/bin/pytest tests/ -v
```
Expected: 40 passed (12 tmux + 4 launcher + 4 models + 10 db + 8 transcript_reader + 6 session_tracker).

- [ ] **Step 2: Tag**

```bash
git tag phase-2-complete
```

---

## Phase 3: Static Left Panel TUI

**Goal:** A Textual application that loads sessions from the DB and renders the 3-line row layout. Selection works with arrow keys and mouse. No live data refresh, no tmux interaction yet — that comes in Phases 4 and 5.

### Task 3.1: Session row widget

**Files:**
- Create: `src/task_pilot/widgets/__init__.py` (if missing)
- Create: `src/task_pilot/widgets/session_row.py`
- Create: `tests/test_session_row.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_row.py
import time
from task_pilot.models import Session, SessionState
from task_pilot.widgets.session_row import SessionRow, format_elapsed, format_tokens, abbrev_home


def test_format_elapsed_seconds():
    assert format_elapsed(45) == "45s"


def test_format_elapsed_minutes():
    assert format_elapsed(23 * 60) == "23m"


def test_format_elapsed_hours():
    assert format_elapsed(2 * 3600 + 15 * 60) == "2h 15m"


def test_format_tokens_thousands():
    assert format_tokens(45000) == "45k tok"
    assert format_tokens(999) == "999 tok"
    assert format_tokens(1500) == "1.5k tok"


def test_abbrev_home(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/foo")
    assert abbrev_home("/Users/foo/project") == "~/project"
    assert abbrev_home("/tmp/x") == "/tmp/x"


def test_session_row_can_be_constructed():
    s = Session(
        id="abc", tmux_window="_bg_abc", cwd="/tmp",
        git_branch="main", started_at=time.time() - 60, title="Test session",
    )
    state = SessionState(session_id="abc", token_count=1234, status="working")
    row = SessionRow(session=s, state=state, selected=False)
    assert row.session_data is s
    assert row.session_state is state
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_session_row.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `session_row.py`**

```python
# src/task_pilot/widgets/session_row.py
"""3-line row widget for the session list."""

from __future__ import annotations

import os
import time
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from task_pilot.models import Session, SessionState

STATUS_ICONS = {
    "initializing": "[#8b8fa3]…[/]",
    "working":      "[#69db7c]●[/]",
    "idle":         "[#ffd43b]◐[/]",
    "unknown":      "[#ff6b6b]?[/]",
}


def format_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


def format_tokens(n: int) -> str:
    if n >= 1000:
        if n % 1000 == 0:
            return f"{n // 1000}k tok"
        return f"{n / 1000:.1f}k tok"
    return f"{n} tok"


def abbrev_home(path: str) -> str:
    home = os.environ.get("HOME", "")
    if home and path.startswith(home):
        return "~" + path[len(home):]
    return path


class SessionRow(Widget, can_focus=True):
    """A 3-line row showing one session."""

    class Selected(Message):
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    DEFAULT_CSS = """
    SessionRow {
        height: 4;
        padding: 0 1;
        background: #111318;
        border-bottom: solid #181b22;
    }
    SessionRow.selected {
        background: #181b22;
        border-left: thick #74c0fc;
    }
    SessionRow .row-title {
        color: #e2e4e9;
    }
    SessionRow .row-meta {
        color: #555869;
    }
    """

    def __init__(self, session: Session, state: SessionState, selected: bool = False) -> None:
        super().__init__()
        self.session_data = session
        self.session_state = state
        if selected:
            self.add_class("selected")

    def compose(self) -> ComposeResult:
        title = self.session_data.title or "New session"
        if len(title) > 32:
            title = title[:29] + "..."
        icon = STATUS_ICONS.get(self.session_state.status, "?")
        line1 = f"{title}    {icon}"

        cwd = abbrev_home(self.session_data.cwd)
        if self.session_data.git_branch:
            line2 = f"{cwd} · {self.session_data.git_branch}"
        else:
            line2 = cwd

        elapsed = format_elapsed(time.time() - self.session_data.started_at)
        tokens = format_tokens(self.session_state.token_count)
        line3 = f"{elapsed} · {tokens}"

        yield Static(line1, classes="row-title")
        yield Static(line2, classes="row-meta")
        yield Static(line3, classes="row-meta")

    def on_click(self) -> None:
        self.post_message(self.Selected(self.session_data.id))
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_session_row.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/task_pilot/widgets/__init__.py src/task_pilot/widgets/session_row.py tests/test_session_row.py
git commit -m "feat: SessionRow widget with 3-line layout"
```

### Task 3.2: List screen

**Files:**
- Create: `src/task_pilot/screens/__init__.py` (if missing)
- Create: `src/task_pilot/screens/list_screen.py`

- [ ] **Step 1: Implement `list_screen.py`**

```python
# src/task_pilot/screens/list_screen.py
"""Main left-panel screen showing the session list."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.screen import Screen
from textual.widgets import Footer, Static

from task_pilot.db import Database
from task_pilot.models import SessionState
from task_pilot.widgets.session_row import SessionRow


class ListScreen(Screen):
    """Renders the session list with arrow-key selection."""

    BINDINGS = [
        ("up,k", "move_up", "Up"),
        ("down,j", "move_down", "Down"),
    ]

    DEFAULT_CSS = """
    ListScreen {
        background: #0c0e12;
    }
    ListScreen #empty {
        color: #555869;
        padding: 2 2;
        text-style: italic;
    }
    """

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self._selected_index = 0

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="rows"):
            yield Static("Loading...", id="empty")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        container = self.query_one("#rows", ScrollableContainer)
        container.remove_children()
        sessions = self.db.list_sessions()
        if not sessions:
            container.mount(Static("No sessions. Press n to create one.", id="empty"))
            return

        for i, s in enumerate(sessions):
            state = SessionState(session_id=s.id)  # placeholder; Phase 4 fills it
            row = SessionRow(session=s, state=state, selected=(i == self._selected_index))
            container.mount(row)

    def action_move_up(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        self._selected_index = max(0, self._selected_index - 1)
        self.refresh_list()

    def action_move_down(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        self._selected_index = min(len(sessions) - 1, self._selected_index + 1)
        self.refresh_list()
```

- [ ] **Step 2: Commit (no test yet — Phase 3.4 covers it)**

```bash
git add src/task_pilot/screens/__init__.py src/task_pilot/screens/list_screen.py
git commit -m "feat: list screen scaffold"
```

### Task 3.3: Textual app entry point

**Files:**
- Create: `src/task_pilot/textual_app.py`

- [ ] **Step 1: Implement**

```python
# src/task_pilot/textual_app.py
"""Textual app that runs inside the left tmux pane."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from task_pilot.config import DB_PATH, TASK_PILOT_DIR
from task_pilot.db import Database
from task_pilot.screens.list_screen import ListScreen


class TaskPilotTextualApp(App):
    TITLE = "Task Pilot"

    def __init__(self, db_path: Path | None = None):
        super().__init__()
        self._db_path = db_path or DB_PATH

    def on_mount(self) -> None:
        TASK_PILOT_DIR.mkdir(parents=True, exist_ok=True)
        self.db = Database(self._db_path)
        self.push_screen(ListScreen(self.db))


def main() -> None:
    app = TaskPilotTextualApp()
    app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual smoke test (seed DB, run app outside tmux)**

```bash
.venv/bin/python -c "
from task_pilot.db import Database
from task_pilot.models import Session
from task_pilot.config import DB_PATH, TASK_PILOT_DIR
import time

TASK_PILOT_DIR.mkdir(parents=True, exist_ok=True)
db = Database(DB_PATH)
db.insert_session(Session(
    id='demo1', tmux_window='_bg_demo1', cwd='/Users/liuhongxuan/project',
    git_branch='main', started_at=time.time() - 600, title='Demo session 1',
))
db.insert_session(Session(
    id='demo2', tmux_window='_bg_demo2', cwd='/tmp/scratch',
    git_branch=None, started_at=time.time() - 60, title=None,
))
print('seeded')
"
.venv/bin/python -m task_pilot.textual_app
```

Expected: a Textual UI shows two rows. Press `j`/`k` to move selection. Press `Ctrl+C` to quit.

- [ ] **Step 3: Clean up the demo DB**

```bash
rm ~/.task-pilot/tasks.db
```

- [ ] **Step 4: Commit**

```bash
git add src/task_pilot/textual_app.py
git commit -m "feat: textual app entry point with list screen"
```

### Task 3.4: TUI integration test

**Files:**
- Create: `tests/test_tui_static.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_tui_static.py
import os
import tempfile
import time
from pathlib import Path
import pytest
from task_pilot.db import Database
from task_pilot.models import Session
from task_pilot.textual_app import TaskPilotTextualApp


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path), path


def seed(db):
    db.insert_session(Session(
        id="a", tmux_window="_bg_a", cwd="/tmp/proj",
        git_branch="main", started_at=time.time() - 100, title="Alpha",
    ))
    db.insert_session(Session(
        id="b", tmux_window="_bg_b", cwd="/tmp/scratch",
        git_branch=None, started_at=time.time() - 30, title=None,
    ))


@pytest.mark.asyncio
async def test_app_launches_with_two_seeded_sessions():
    db, path = make_db()
    seed(db)
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        # ListScreen mounted
        from task_pilot.screens.list_screen import ListScreen
        screens = [s for s in app.screen_stack if isinstance(s, ListScreen)]
        assert len(screens) == 1
        # Two SessionRow widgets
        from task_pilot.widgets.session_row import SessionRow
        rows = list(app.screen.query(SessionRow))
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_app_launches_with_empty_db():
    db, path = make_db()
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        from textual.widgets import Static
        empties = [s for s in app.screen.query(Static) if "No sessions" in str(s.render())]
        assert len(empties) >= 1
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/test_tui_static.py -v
```
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_tui_static.py
git commit -m "test: TUI smoke tests for static list screen"
```

### Task 3.5: Phase 3 verification

- [ ] **Step 1: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```
Expected: 48 passed (Phase 2 totals + 6 session_row + 2 tui_static).

- [ ] **Step 2: Tag**

```bash
git tag phase-3-complete
```

---

## Phase 4: Live Data Refresh

**Goal:** The list refreshes every 2 seconds. Token counts come from transcripts. Status (working/idle) is computed from `last_activity`. Git branches are cached and refreshed only on `r`. Titles are extracted from transcripts. Pilot reconciles with tmux on every refresh.

### Task 4.1: Git branch helper

**Files:**
- Create: `src/task_pilot/git_branch.py`
- Create: `tests/test_git_branch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_git_branch.py
import subprocess
import tempfile
from pathlib import Path
from task_pilot.git_branch import current_branch


def test_returns_none_for_non_git_dir(tmp_path):
    assert current_branch(str(tmp_path)) is None


def test_returns_branch_for_git_repo(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    branch = current_branch(str(tmp_path))
    assert branch == "main"
```

- [ ] **Step 2: Implement**

```python
# src/task_pilot/git_branch.py
"""Get the current git branch for a directory, or None."""

from __future__ import annotations

import subprocess


def current_branch(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            return None
        branch = result.stdout.strip()
        return branch if branch and branch != "HEAD" else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/test_git_branch.py -v
```
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add src/task_pilot/git_branch.py tests/test_git_branch.py
git commit -m "feat: git branch helper"
```

### Task 4.2: Transcript path resolver

**Files:**
- Create: `src/task_pilot/transcript_resolver.py`
- Create: `tests/test_transcript_resolver.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_transcript_resolver.py
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from task_pilot.transcript_resolver import (
    cwd_to_slug,
    resolve_by_cwd_and_time,
)


def test_cwd_to_slug():
    assert cwd_to_slug("/Users/foo/proj") == "-Users-foo-proj"
    assert cwd_to_slug("/tmp/x") == "-tmp-x"


def test_resolve_by_cwd_and_time(tmp_path):
    # Set up fake claude home
    claude_home = tmp_path / ".claude"
    proj_dir = claude_home / "projects" / "-tmp-myproj"
    proj_dir.mkdir(parents=True)
    transcript = proj_dir / "session-uuid-123.jsonl"
    transcript.write_text("{}\n")

    found = resolve_by_cwd_and_time(
        cwd="/tmp/myproj",
        started_at=transcript.stat().st_ctime - 10,
        claude_home=claude_home,
    )
    assert found == transcript


def test_resolve_by_cwd_returns_none_when_no_dir(tmp_path):
    claude_home = tmp_path / ".claude"
    found = resolve_by_cwd_and_time("/tmp/nope", 0, claude_home)
    assert found is None
```

- [ ] **Step 2: Implement**

```python
# src/task_pilot/transcript_resolver.py
"""Resolve a session's transcript .jsonl path."""

from __future__ import annotations

from pathlib import Path

import psutil


def cwd_to_slug(cwd: str) -> str:
    """Claude Code stores transcripts under projects/<slug>/."""
    return cwd.replace("/", "-")


def resolve_by_pid(shell_pid: int) -> str | None:
    """Walk children of shell_pid to find a `claude` process; return its claude session id."""
    try:
        proc = psutil.Process(shell_pid)
        for child in proc.children(recursive=True):
            try:
                name = child.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if name == "claude" or (child.cmdline() and child.cmdline()[0].endswith("claude")):
                return _claude_session_id_for_pid(child.pid)
    except psutil.NoSuchProcess:
        return None
    return None


def _claude_session_id_for_pid(pid: int) -> str | None:
    import json
    sessions_dir = Path.home() / ".claude" / "sessions"
    if not sessions_dir.exists():
        return None
    for f in sessions_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("pid") == pid:
            return data.get("sessionId")
    return None


def resolve_by_cwd_and_time(
    cwd: str, started_at: float, claude_home: Path | None = None
) -> Path | None:
    """Find the .jsonl in projects/<slug>/ whose ctime is after started_at - 2s."""
    if claude_home is None:
        claude_home = Path.home() / ".claude"
    proj_dir = claude_home / "projects" / cwd_to_slug(cwd)
    if not proj_dir.exists():
        return None
    candidates = []
    for f in proj_dir.glob("*.jsonl"):
        try:
            ct = f.stat().st_ctime
        except OSError:
            continue
        if ct >= started_at - 2:
            candidates.append((ct, f))
    if not candidates:
        return None
    return min(candidates, key=lambda x: abs(x[0] - started_at))[1]
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/test_transcript_resolver.py -v
```
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add src/task_pilot/transcript_resolver.py tests/test_transcript_resolver.py
git commit -m "feat: transcript path resolver (psutil + cwd fallback)"
```

### Task 4.3: Refresh loop in SessionTracker

**Files:**
- Modify: `src/task_pilot/session_tracker.py`
- Modify: `tests/test_session_tracker.py`

- [ ] **Step 1: Add refresh logic to SessionTracker**

Append a method to `SessionTracker`:

```python
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
```

Update `__init__` to add `_state_cache`:

```python
    def __init__(self, db: "Database", tmux, session_name: str = "task-pilot"):
        self.db = db
        self.tmux = tmux
        self.session_name = session_name
        self._state_cache: dict[str, "SessionState"] = {}
```

- [ ] **Step 2: Create the title cleaning helper**

```python
# src/task_pilot/title_clean.py
"""Clean a raw user message into a short title."""

import re


def clean_title(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw).strip()
    for line in text.splitlines():
        line = line.strip()
        if line:
            text = line
            break
    if len(text) > 60:
        text = text[:57] + "..."
    return text
```

- [ ] **Step 3: Add a test for refresh_state**

Append to `tests/test_session_tracker.py`:

```python
def test_refresh_state_returns_dict_for_all_sessions(tmp_path):
    db = make_db()
    db.insert_session(Session(
        id="x", tmux_window="_bg_x", cwd=str(tmp_path),
        git_branch=None, started_at=time.time(), title=None,
    ))
    fake_tmux = MagicMock()
    tracker = SessionTracker(db, tmux=fake_tmux, session_name="task-pilot")
    states = tracker.refresh_state()
    assert "x" in states
    assert states["x"].status in ("initializing", "working", "idle", "unknown")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_session_tracker.py -v
```
Expected: 7 passed (6 original + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/task_pilot/session_tracker.py src/task_pilot/title_clean.py tests/test_session_tracker.py
git commit -m "feat: refresh_state computes runtime SessionState from transcripts"
```

### Task 4.4: Wire refresh into ListScreen

**Files:**
- Modify: `src/task_pilot/screens/list_screen.py`
- Modify: `src/task_pilot/textual_app.py`

- [ ] **Step 1: Update ListScreen to use SessionTracker**

```python
# src/task_pilot/screens/list_screen.py
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
            yield Static("Loading...", id="empty")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_data()
        self.set_interval(REFRESH_INTERVAL_SECONDS, self.refresh_data)

    def refresh_data(self, force: bool = False) -> None:
        self.tracker.reconcile()
        self._states = self.tracker.refresh_state(force=force)
        self._render()

    def _render(self) -> None:
        container = self.query_one("#rows", ScrollableContainer)
        container.remove_children()
        sessions = self.db.list_sessions()
        if not sessions:
            container.mount(Static("No sessions. Press n to create one.", id="empty"))
            return
        # Clamp selection
        if self._selected_index >= len(sessions):
            self._selected_index = max(0, len(sessions) - 1)
        for i, s in enumerate(sessions):
            state = self._states.get(s.id, SessionState(session_id=s.id))
            row = SessionRow(session=s, state=state, selected=(i == self._selected_index))
            container.mount(row)

    def action_move_up(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        self._selected_index = max(0, self._selected_index - 1)
        self._render()

    def action_move_down(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        self._selected_index = min(len(sessions) - 1, self._selected_index + 1)
        self._render()

    def action_force_refresh(self) -> None:
        self.refresh_data(force=True)
```

- [ ] **Step 2: Update textual_app.py to construct the tracker**

```python
# src/task_pilot/textual_app.py
from __future__ import annotations

from pathlib import Path

from textual.app import App

from task_pilot import tmux
from task_pilot.config import DB_PATH, TASK_PILOT_DIR
from task_pilot.db import Database
from task_pilot.screens.list_screen import ListScreen
from task_pilot.session_tracker import SessionTracker


class TaskPilotTextualApp(App):
    TITLE = "Task Pilot"

    def __init__(self, db_path: Path | None = None):
        super().__init__()
        self._db_path = db_path or DB_PATH

    def on_mount(self) -> None:
        TASK_PILOT_DIR.mkdir(parents=True, exist_ok=True)
        self.db = Database(self._db_path)
        self.tracker = SessionTracker(self.db, tmux=tmux)
        self.push_screen(ListScreen(self.db, self.tracker))


def main() -> None:
    app = TaskPilotTextualApp()
    app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Update test_tui_static.py for the new constructor**

```python
# tests/test_tui_static.py - update the test signatures
from unittest.mock import MagicMock

# Inside each test, replace `TaskPilotTextualApp(db_path=Path(path))` with:
# (no change needed; the app constructs its own tracker)
```

The tests should still work since the app constructs its own tracker. If `tmux.list_windows` fails inside the test, mock it:

```python
# tests/test_tui_static.py
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import pytest
from task_pilot.db import Database
from task_pilot.models import Session
from task_pilot.textual_app import TaskPilotTextualApp


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path), path


def seed(db):
    db.insert_session(Session(
        id="a", tmux_window="_bg_a", cwd="/tmp/proj",
        git_branch="main", started_at=time.time() - 100, title="Alpha",
    ))
    db.insert_session(Session(
        id="b", tmux_window="_bg_b", cwd="/tmp/scratch",
        git_branch=None, started_at=time.time() - 30, title=None,
    ))


@pytest.mark.asyncio
async def test_app_launches_with_two_seeded_sessions():
    db, path = make_db()
    seed(db)
    db.close()
    with patch("task_pilot.session_tracker.SessionTracker.reconcile"):
        app = TaskPilotTextualApp(db_path=Path(path))
        async with app.run_test() as pilot:
            from task_pilot.widgets.session_row import SessionRow
            rows = list(app.screen.query(SessionRow))
            assert len(rows) == 2


@pytest.mark.asyncio
async def test_app_launches_with_empty_db():
    db, path = make_db()
    db.close()
    with patch("task_pilot.session_tracker.SessionTracker.reconcile"):
        app = TaskPilotTextualApp(db_path=Path(path))
        async with app.run_test() as pilot:
            from textual.widgets import Static
            empties = [s for s in app.screen.query(Static) if "No sessions" in str(s.render())]
            assert len(empties) >= 1
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/ -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/task_pilot/screens/list_screen.py src/task_pilot/textual_app.py tests/test_tui_static.py
git commit -m "feat: wire live refresh loop into ListScreen"
```

### Task 4.5: Phase 4 verification

- [ ] **Step 1: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```
Expected: ~55 passed.

- [ ] **Step 2: Tag**

```bash
git tag phase-4-complete
```

---

## Phase 5: Interaction (new session, close, switch, command bar)

**Goal:** All user interactions work — `n` opens the new-session dialog, `Enter` switches sessions via two-step swap, `x` closes a session with confirmation, `:q` quits everything, `/` filters the list.

### Task 5.1: New session dialog

**Files:**
- Create: `src/task_pilot/widgets/new_session_dialog.py`
- Create: `tests/test_new_session_dialog.py`

- [ ] **Step 1: Implement the dialog**

```python
# src/task_pilot/widgets/new_session_dialog.py
"""Modal dialog for creating a new session."""

from __future__ import annotations

import json
import os
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static


HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"
MAX_RECENT = 10


def recent_directories() -> list[str]:
    """Read ~/.claude/history.jsonl and return up to MAX_RECENT unique projects."""
    if not HISTORY_FILE.exists():
        return []
    seen = []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in reversed(f.readlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    proj = entry.get("project")
                    if proj and proj not in seen:
                        seen.append(proj)
                        if len(seen) >= MAX_RECENT:
                            break
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return seen


def complete_path(value: str) -> str:
    """Tab-complete a partial path."""
    expanded = os.path.expanduser(value or "")
    p = Path(expanded)
    if p.is_dir() and not value.endswith("/"):
        return value + "/"
    parent = p.parent
    prefix = p.name
    if not parent.exists():
        return value
    matches = [c.name for c in parent.iterdir() if c.is_dir() and c.name.startswith(prefix)]
    if len(matches) == 1:
        return str(parent / matches[0]) + "/"
    if matches:
        common = os.path.commonprefix(matches)
        if len(common) > len(prefix):
            return str(parent / common)
    return value


class NewSessionDialog(ModalScreen[str | None]):
    """Returns the selected directory path, or None if cancelled."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    NewSessionDialog {
        align: center middle;
    }
    NewSessionDialog #panel {
        width: 60;
        height: 20;
        background: #181b22;
        border: solid #74c0fc;
        padding: 1 2;
    }
    NewSessionDialog Label.title {
        text-style: bold;
        margin-bottom: 1;
    }
    NewSessionDialog #path {
        background: #111318;
        color: #e2e4e9;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="panel"):
            yield Label("New Session", classes="title")
            yield Label("Recent directories:")
            items = [ListItem(Label(d), id=f"d_{i}") for i, d in enumerate(recent_directories())]
            yield ListView(*items, id="recent")
            yield Label("Or type a path:")
            yield Input(placeholder="/path/to/project", id="path")
            yield Label("Enter: create   Esc: cancel", classes="hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        path = os.path.expanduser(event.value.strip())
        if path and Path(path).exists():
            self.dismiss(path)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        label = event.item.query_one(Label)
        self.dismiss(str(label.renderable))

    def on_key(self, event) -> None:
        if event.key == "tab":
            inp = self.query_one("#path", Input)
            if inp.has_focus:
                inp.value = complete_path(inp.value)
                event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 2: Write tests**

```python
# tests/test_new_session_dialog.py
import os
import tempfile
from pathlib import Path
from task_pilot.widgets.new_session_dialog import complete_path, recent_directories


def test_complete_path_single_match(tmp_path, monkeypatch):
    (tmp_path / "alpha").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    result = complete_path(str(tmp_path / "alp"))
    assert result.endswith("alpha/")


def test_complete_path_multiple_match(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alphabet").mkdir()
    result = complete_path(str(tmp_path / "alp"))
    assert result.endswith("alpha")  # common prefix
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/test_new_session_dialog.py -v
```
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add src/task_pilot/widgets/new_session_dialog.py tests/test_new_session_dialog.py
git commit -m "feat: new session dialog with recent dirs and tab completion"
```

### Task 5.2: Wire `n` key + create + switch

- [ ] **Step 1: Add bindings to ListScreen**

Update `list_screen.py` BINDINGS:

```python
    BINDINGS = [
        ("up,k", "move_up", "Up"),
        ("down,j", "move_down", "Down"),
        ("r", "force_refresh", "Refresh"),
        ("n", "new_session", "New"),
        ("x", "close_session", "Close"),
        ("enter", "switch_to_selected", "Switch"),
    ]
```

Add the action methods:

```python
    def action_new_session(self) -> None:
        from task_pilot.widgets.new_session_dialog import NewSessionDialog

        def handle(cwd: str | None) -> None:
            if cwd:
                from task_pilot.git_branch import current_branch
                s = self.tracker.create_session(cwd=cwd, git_branch=current_branch(cwd))
                self.tracker.switch_to(s.id)
                self.refresh_data()

        self.app.push_screen(NewSessionDialog(), handle)

    def action_close_session(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        target = sessions[self._selected_index]
        # TODO confirmation dialog in 5.3 — for now just close
        self.tracker.close_session(target.id)
        self.refresh_data()

    def action_switch_to_selected(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        target = sessions[self._selected_index]
        self.tracker.switch_to(target.id)
```

- [ ] **Step 2: Commit**

```bash
git add src/task_pilot/screens/list_screen.py
git commit -m "feat: wire n/x/Enter to session lifecycle"
```

### Task 5.3: Close confirmation dialog

**Files:**
- Create: `src/task_pilot/widgets/confirm_dialog.py`

- [ ] **Step 1: Implement**

```python
# src/task_pilot/widgets/confirm_dialog.py
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        ("y", "yes", "Yes"),
        ("n,escape", "no", "No"),
    ]

    DEFAULT_CSS = """
    ConfirmDialog { align: center middle; }
    ConfirmDialog #box {
        background: #181b22;
        border: solid #ff6b6b;
        padding: 1 2;
        width: 60;
        height: 8;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(self.message)
            yield Label("[y] Yes   [n] No")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)
```

- [ ] **Step 2: Wire into ListScreen.action_close_session**

```python
    def action_close_session(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            return
        target = sessions[self._selected_index]
        from task_pilot.widgets.confirm_dialog import ConfirmDialog

        def on_confirm(yes: bool) -> None:
            if yes:
                self.tracker.close_session(target.id)
                self.refresh_data()

        title = target.title or "this session"
        self.app.push_screen(
            ConfirmDialog(f'Close "{title}"? This kills the Claude Code process.'),
            on_confirm,
        )
```

- [ ] **Step 3: Commit**

```bash
git add src/task_pilot/widgets/confirm_dialog.py src/task_pilot/screens/list_screen.py
git commit -m "feat: close confirmation dialog"
```

### Task 5.4: `:q` command bar

- [ ] **Step 1: Add command bar widget to ListScreen**

Add to `list_screen.py`:

```python
    BINDINGS = [
        # ... existing ...
        ("colon", "open_command", "Command"),
    ]

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
        from task_pilot import tmux as tmux_mod
        tmux_mod.kill_session("task-pilot")
        self.app.exit()
```

- [ ] **Step 2: Implement CommandBar**

```python
# src/task_pilot/widgets/command_bar.py
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input


class CommandBar(ModalScreen[str | None]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    CommandBar {
        align: center bottom;
    }
    CommandBar #cmd {
        width: 100%;
        background: #181b22;
        color: #e2e4e9;
    }
    """

    def compose(self) -> ComposeResult:
        yield Input(placeholder=":", id="cmd")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 3: Commit**

```bash
git add src/task_pilot/widgets/command_bar.py src/task_pilot/screens/list_screen.py
git commit -m "feat: :q command bar for full pilot quit"
```

### Task 5.5: Search filter

- [ ] **Step 1: Add `/` binding to ListScreen**

```python
    BINDINGS = [
        # existing ...
        ("slash", "open_search", "Search"),
    ]

    def __init__(self, db, tracker):
        # existing ...
        self._search_query = ""

    def action_open_search(self) -> None:
        # Show a small input at the bottom; on each keystroke, re-filter
        from task_pilot.widgets.search_bar import SearchBar

        def on_change(query: str) -> None:
            self._search_query = query
            self._render()

        def on_close() -> None:
            self._search_query = ""
            self._render()

        self.app.push_screen(SearchBar(on_change, on_close))

    def _filtered_sessions(self):
        sessions = self.db.list_sessions()
        if not self._search_query:
            return sessions
        q = self._search_query.lower()
        return [s for s in sessions if q in (s.title or "").lower() or q in s.cwd.lower()]
```

Update `_render` to use `_filtered_sessions()` instead of `self.db.list_sessions()`.

- [ ] **Step 2: Implement SearchBar**

```python
# src/task_pilot/widgets/search_bar.py
from typing import Callable
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input


class SearchBar(ModalScreen[None]):
    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    DEFAULT_CSS = """
    SearchBar { align: center bottom; }
    SearchBar #q {
        width: 100%;
        background: #181b22;
        border: solid #74c0fc;
    }
    """

    def __init__(self, on_change: Callable[[str], None], on_close: Callable[[], None]) -> None:
        super().__init__()
        self._on_change = on_change
        self._on_close = on_close

    def compose(self) -> ComposeResult:
        yield Input(placeholder="search...", id="q")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._on_change(event.value)

    def action_close(self) -> None:
        self._on_close()
        self.dismiss(None)
```

- [ ] **Step 3: Commit**

```bash
git add src/task_pilot/widgets/search_bar.py src/task_pilot/screens/list_screen.py
git commit -m "feat: search bar with live filtering"
```

### Task 5.6: Manual end-to-end Phase 5 verification

- [ ] **Step 1: Run pilot**

```bash
uv run task-pilot ui
```

- [ ] **Step 2: In pilot's left pane, press `n`**

Expected: dialog opens, can choose recent dir or type one.

- [ ] **Step 3: Create a session, verify it shows on the right**

Expected: a real Claude Code session opens in the right pane.

- [ ] **Step 4: Create a second session, switch between them with arrow keys + Enter**

Expected: right pane swaps without killing either Claude Code process.

- [ ] **Step 5: Search with `/`**

Expected: rows filter by substring.

- [ ] **Step 6: Close one with `x`, confirm with `y`**

Expected: that Claude Code is killed; the row disappears.

- [ ] **Step 7: Quit with `:q` Enter**

Expected: tmux session and all remaining Claude Code sessions are killed.

- [ ] **Step 8: Tag**

```bash
git tag phase-5-complete
```

---

## Phase 6: Polish

**Goal:** Error handling, watchdog, README rewrite, full QA pass.

### Task 6.1: Watchdog wrapper for the Textual app

**Files:**
- Modify: `src/task_pilot/textual_app.py`

- [ ] **Step 1: Add `--watchdog` flag**

```python
# src/task_pilot/textual_app.py
def main() -> None:
    import sys
    import time

    if "--watchdog" not in sys.argv:
        app = TaskPilotTextualApp()
        app.run()
        return

    # Watchdog mode: restart on crash, give up after 3 crashes in 60s
    crashes = []
    while True:
        try:
            app = TaskPilotTextualApp()
            app.run()
            return  # clean exit
        except Exception as e:
            now = time.time()
            crashes = [c for c in crashes if now - c < 60] + [now]
            if len(crashes) >= 3:
                print(f"Pilot crashed 3 times in 60s; giving up. Last error: {e}")
                return
            print(f"Pilot crashed: {e}; restarting in 1s...")
            time.sleep(1)
```

- [ ] **Step 2: Update launcher.bootstrap to pass --watchdog**

In `launcher.py`, change the placeholder send_keys to:

```python
    tmux.send_keys(f"{SESSION_NAME}:main.0",
                   "exec python -m task_pilot.textual_app --watchdog")
```

Remove `PLACEHOLDER_LEFT` and `PLACEHOLDER_RIGHT`. The right pane stays as a default shell with a banner:

```python
    tmux.send_keys(f"{SESSION_NAME}:main.1",
                   "echo 'Press n in the left pane to create a new Claude Code session'")
```

- [ ] **Step 3: Commit**

```bash
git add src/task_pilot/textual_app.py src/task_pilot/launcher.py
git commit -m "feat: watchdog wrapper for the Textual app"
```

### Task 6.2: README rewrite

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `README.ja.md`

- [ ] **Step 1: Rewrite English README**

Replace the entire content of `README.md` with the v0.2 version (full text in spec; key sections: tmux architecture, requirements, usage, keybindings, platform notes). Use the spec as the source of truth.

- [ ] **Step 2: Translate to Chinese**

- [ ] **Step 3: Translate to Japanese**

- [ ] **Step 4: Commit**

```bash
git add README.md README.zh-CN.md README.ja.md
git commit -m "docs: rewrite READMEs for tmux-based v0.2 architecture"
```

### Task 6.3: Final QA pass

- [ ] **Step 1: Run the entire test suite**

```bash
.venv/bin/pytest tests/ -v --tb=short
```

Expected: all green.

- [ ] **Step 2: Dispatch QA agent**

Use the Agent tool to run a `general-purpose` agent that:
- Verifies each Phase's manual checks still pass
- Runs the test suite
- Tries `task-pilot ui`, `task-pilot kill`, `:q`, `n`, `x`, `/`, `r`
- Reports any regressions

- [ ] **Step 3: Tag**

```bash
git tag v0.2.0
```

- [ ] **Step 4: Push everything**

```bash
git push --tags
git push
```

---

## Done

The rewrite is complete. Removed: hooks, scanner, summarizer-AI-loop, action items, timeline screen. Added: tmux orchestration, two-step swap protocol, live token counting, command bar.
