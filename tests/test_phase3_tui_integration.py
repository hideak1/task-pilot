"""Extended TUI integration tests for Phase 3.

Verifies the static list screen renders all combinations of session
state (titles, missing branches, long titles, various status icons).
"""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_reconcile():
    with patch("task_pilot.session_tracker.SessionTracker.reconcile"):
        yield

from task_pilot.db import Database
from task_pilot.models import Session, SessionState
from task_pilot.textual_app import TaskPilotTextualApp
from task_pilot.widgets.session_row import (
    SessionRow,
    format_elapsed,
    format_tokens,
    abbrev_home,
    STATUS_ICONS,
)


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path), path


# ── format helpers exhaustive ──────────────────────────────

def test_format_elapsed_zero():
    assert format_elapsed(0) == "0s"

def test_format_elapsed_just_under_minute():
    assert format_elapsed(59) == "59s"

def test_format_elapsed_just_one_minute():
    assert format_elapsed(60) == "1m"

def test_format_elapsed_just_under_hour():
    assert format_elapsed(3599) == "59m"

def test_format_elapsed_exactly_one_hour():
    assert format_elapsed(3600) == "1h 0m"

def test_format_tokens_zero():
    assert format_tokens(0) == "0 tok"

def test_format_tokens_999():
    assert format_tokens(999) == "999 tok"

def test_format_tokens_1000_exact():
    assert format_tokens(1000) == "1k tok"

def test_format_tokens_1234():
    assert format_tokens(1234) == "1.2k tok"

def test_format_tokens_45000():
    assert format_tokens(45000) == "45k tok"


def test_abbrev_home_no_match(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/foo")
    assert abbrev_home("/etc/hosts") == "/etc/hosts"

def test_abbrev_home_unset(monkeypatch):
    monkeypatch.delenv("HOME", raising=False)
    assert abbrev_home("/some/path") == "/some/path"


def test_status_icons_all_present():
    """Spec requires four status icons: initializing, working, idle, unknown."""
    for status in ("initializing", "working", "idle", "unknown"):
        assert status in STATUS_ICONS


# ── Empty DB UI ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_db_shows_hint():
    db, path = make_db()
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        from textual.widgets import Static
        statics = list(app.screen.query(Static))
        text = " ".join(str(s.render()) for s in statics)
        assert "No sessions" in text or "n to create" in text


# ── Three sessions in different states ─────────────────────

@pytest.mark.asyncio
async def test_three_sessions_render():
    db, path = make_db()
    db.insert_session(Session(
        id="t1", tmux_window="_bg_t1", cwd="/Users/foo/api",
        git_branch="main", started_at=time.time() - 7200, title="Build REST API",
    ))
    db.insert_session(Session(
        id="t2", tmux_window="_bg_t2", cwd="/Users/foo/web",
        git_branch="fix/auth", started_at=time.time() - 1500, title="Fix login bug",
    ))
    db.insert_session(Session(
        id="t3", tmux_window="_bg_t3", cwd="/tmp/scratch",
        git_branch=None, started_at=time.time() - 60, title=None,
    ))
    db.close()

    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        rows = list(app.screen.query(SessionRow))
        assert len(rows) == 3


@pytest.mark.asyncio
async def test_arrow_keys_move_selection():
    db, path = make_db()
    for i in range(3):
        db.insert_session(Session(
            id=f"s{i}", tmux_window=f"_bg_s{i}", cwd="/tmp",
            git_branch=None, started_at=time.time() - i * 60, title=f"Session {i}",
        ))
    db.close()

    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        # Initial selection is index 0
        rows = list(app.screen.query(SessionRow))
        assert rows[0].has_class("selected")
        # Press 'j' (down)
        await pilot.press("j")
        rows = list(app.screen.query(SessionRow))
        assert rows[1].has_class("selected")
        assert not rows[0].has_class("selected")
        # Press 'k' (up)
        await pilot.press("k")
        rows = list(app.screen.query(SessionRow))
        assert rows[0].has_class("selected")


@pytest.mark.asyncio
async def test_long_title_truncated():
    db, path = make_db()
    long_title = "X" * 100
    db.insert_session(Session(
        id="long", tmux_window="_bg_long", cwd="/tmp",
        git_branch=None, started_at=time.time(), title=long_title,
    ))
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        from textual.widgets import Static
        statics = list(app.screen.query(Static))
        # Find a static whose render text contains the truncation
        any_truncated = any("..." in str(s.render()) for s in statics)
        assert any_truncated
