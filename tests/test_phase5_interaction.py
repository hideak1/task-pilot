"""Phase 5 interaction tests using Textual's pilot."""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from task_pilot.db import Database
from task_pilot.models import Session
from task_pilot.textual_app import TaskPilotTextualApp


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path), path


def seed_three(db):
    """Seed three sessions in different states."""
    for i, (title, branch) in enumerate([
        ("Build API", "main"),
        ("Fix bug", "fix/auth"),
        ("Refactor", None),
    ]):
        db.insert_session(Session(
            id=f"s{i}", tmux_window=f"_bg_s{i}",
            cwd=f"/tmp/proj{i}", git_branch=branch,
            started_at=time.time() - (i + 1) * 60,
            title=title,
        ))


@pytest.fixture(autouse=True)
def mock_reconcile():
    """Prevent SessionTracker.reconcile from wiping seeded DB."""
    with patch("task_pilot.session_tracker.SessionTracker.reconcile"):
        yield


# ── New session dialog ──────────────────────────────────────

@pytest.mark.asyncio
async def test_n_opens_new_session_dialog():
    db, path = make_db()
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        await pilot.press("n")
        from task_pilot.widgets.new_session_dialog import NewSessionDialog
        assert any(isinstance(s, NewSessionDialog) for s in app.screen_stack)


# ── Close confirmation ─────────────────────────────────────

@pytest.mark.asyncio
async def test_x_opens_confirm_dialog():
    db, path = make_db()
    seed_three(db)
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        await pilot.press("x")
        from task_pilot.widgets.confirm_dialog import ConfirmDialog
        assert any(isinstance(s, ConfirmDialog) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_x_does_not_crash_on_empty_db():
    db, path = make_db()
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        await pilot.press("x")


# ── Command bar :q ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_colon_opens_command_bar():
    db, path = make_db()
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        await pilot.press("colon")
        from task_pilot.widgets.command_bar import CommandBar
        assert any(isinstance(s, CommandBar) for s in app.screen_stack)


# ── Search bar / ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_slash_opens_search_bar():
    db, path = make_db()
    seed_three(db)
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        await pilot.press("slash")
        from task_pilot.widgets.search_bar import SearchBar
        assert any(isinstance(s, SearchBar) for s in app.screen_stack)


# ── Selection navigation ───────────────────────────────────

@pytest.mark.asyncio
async def test_jk_navigation():
    db, path = make_db()
    seed_three(db)
    db.close()
    app = TaskPilotTextualApp(db_path=Path(path))
    async with app.run_test() as pilot:
        from task_pilot.widgets.session_row import SessionRow
        rows = list(app.screen.query(SessionRow))
        assert rows[0].has_class("selected")
        await pilot.press("j")
        rows = list(app.screen.query(SessionRow))
        assert rows[1].has_class("selected")
        await pilot.press("j")
        rows = list(app.screen.query(SessionRow))
        assert rows[2].has_class("selected")
        await pilot.press("j")
        rows = list(app.screen.query(SessionRow))
        assert rows[2].has_class("selected")
        await pilot.press("k")
        rows = list(app.screen.query(SessionRow))
        assert rows[1].has_class("selected")


# ── Path completion (unit) ─────────────────────────────────

def test_complete_path_no_dir(tmp_path, monkeypatch):
    from task_pilot.widgets.new_session_dialog import complete_path
    monkeypatch.setenv("HOME", str(tmp_path))
    assert complete_path("/nonexistent/xyz") == "/nonexistent/xyz"


def test_recent_directories_handles_missing_history():
    from task_pilot.widgets.new_session_dialog import recent_directories
    result = recent_directories()
    assert isinstance(result, list)
