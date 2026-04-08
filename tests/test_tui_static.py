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
