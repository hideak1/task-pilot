"""Comprehensive TUI tests for Task Pilot using Textual's async test support."""

import os
import tempfile
import time
from pathlib import Path

import pytest

from task_pilot.app import TaskPilotApp
from task_pilot.db import Database
from task_pilot.screens.detail_screen import DetailScreen
from task_pilot.screens.list_screen import ListScreen
from task_pilot.widgets.action_steps import ActionStepRow, ActionSteps
from task_pilot.widgets.header_bar import HeaderBar
from task_pilot.widgets.task_row import TaskRow
from task_pilot.widgets.timeline import Timeline, TimelineEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db() -> tuple[Database, str]:
    """Create a temporary database and return (db, path)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    return db, path


def _seed(db: Database) -> None:
    """Seed the database with representative test data."""
    db.upsert_task("t1", title="Fix login bug", status="action_required", summary="Login page throws 500 on bad credentials")
    db.add_action_item("t1", "Run migration", command="python manage.py migrate")
    db.add_action_item("t1", "Test on staging")

    db.upsert_task("t2", title="Build REST API", status="working", summary="Implementing CRUD endpoints")
    db.upsert_session("s1", task_id="t2", started_at=time.time())
    db.add_timeline_event("t2", session_id="s1", event_type="session_start", description="Session started")

    db.upsert_task("t3", title="Update README", status="done", summary="Added setup instructions")


def _make_app(db_path: str) -> TaskPilotApp:
    # Use empty temp dir as claude_home to prevent scanning real ~/.claude/
    import tempfile
    empty_claude_home = tempfile.mkdtemp()
    return TaskPilotApp(db_path=db_path, claude_home=Path(empty_claude_home))


def _get_text(widget) -> str:
    """Extract display text from a Static widget via its render() output."""
    return str(widget.render())


# ---------------------------------------------------------------------------
# 1. App launches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_launches():
    """App launches, shows header, shows empty state hint, exits cleanly."""
    db, path = _make_db()
    app = _make_app(path)
    async with app.run_test() as pilot:
        # Header bar should be present
        header = app.query_one(HeaderBar)
        assert header is not None

        # No tasks seeded -> empty hint should be visible
        hints = app.query(".empty-hint")
        assert len(hints) == 1
        assert "No tasks yet" in _get_text(hints.first())

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 2. List screen shows tasks in correct sections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_screen_shows_tasks():
    """Seed DB with tasks in different statuses, verify they appear."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test() as pilot:
        # There should be TaskRow widgets for each seeded task
        rows = app.query(TaskRow)
        assert len(rows) == 3

        # Check that each task title is represented
        titles = {r.task_data.title for r in rows}
        assert titles == {"Fix login bug", "Build REST API", "Update README"}

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 3. Section labels appear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_screen_section_labels():
    """Verify section labels for the three categories appear."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test() as pilot:
        section_labels = app.query(".section-label")
        label_texts = [_get_text(lbl) for lbl in section_labels]
        combined = " ".join(label_texts)

        assert "需要你操作" in combined
        assert "Claude 工作中" in combined
        assert "已完成" in combined

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 4. Header bar shows stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_header_bar_shows_stats():
    """Verify header shows correct counts after seeding."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test() as pilot:
        header = app.query_one(HeaderBar)

        assert header.action_count == 1
        assert header.working_count == 1
        assert header.done_count == 1

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 5. Task row shows status icon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_row_shows_status_icon():
    """Verify correct status icons for each status."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test() as pilot:
        rows = app.query(TaskRow)
        status_to_task = {r.task_data.status: r for r in rows}

        # Each task row has a .icon Static child with the right marker
        for status, expected_fragment in [
            ("action_required", "\u25cf"),   # ●
            ("working", "\u25c9"),            # ◉
            ("done", "\u2713"),               # ✓
        ]:
            row = status_to_task[status]
            icon_widget = row.query_one(".icon")
            icon_text = _get_text(icon_widget)
            assert expected_fragment in icon_text, f"Expected {expected_fragment!r} in icon for status {status}, got {icon_text!r}"

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 6. Navigate to detail screen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigate_to_detail():
    """Click on a task row, verify DetailScreen is pushed."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test(size=(120, 40)) as pilot:
        # Focus the first TaskRow and press enter
        first_row = app.query(TaskRow).first()
        first_row.focus()
        await pilot.press("enter")

        # DetailScreen should now be on the screen stack
        assert isinstance(app.screen, DetailScreen)

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 7. Detail screen shows task info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_screen_shows_task_info():
    """Verify detail screen shows title, summary, status badge."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test(size=(120, 40)) as pilot:
        # Navigate to task t1
        app.push_screen(DetailScreen(db, "t1"))
        await pilot.pause()

        # Title
        title_widget = app.screen.query_one(".detail-title")
        assert "Fix login bug" in _get_text(title_widget)

        # Badge row contains status badge
        badge_widget = app.screen.query_one(".badge-row")
        badge_text = _get_text(badge_widget)
        assert "需要操作" in badge_text

        # Summary
        summary_text_widgets = app.screen.query(".summary-text")
        assert len(summary_text_widgets) > 0
        assert "Login page throws 500" in _get_text(summary_text_widgets.first())

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 8. Detail screen shows action steps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_screen_shows_action_steps():
    """Verify action steps appear with correct text."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(DetailScreen(db, "t1"))
        await pilot.pause()

        # ActionSteps widget should exist
        action_steps = app.screen.query_one(ActionSteps)
        assert action_steps is not None

        # Two ActionStepRow children
        step_rows = app.screen.query(ActionStepRow)
        assert len(step_rows) == 2

        # Check descriptions by looking at .step-text content
        step_texts = [_get_text(w.query_one(".step-text")) for w in step_rows]
        combined = " ".join(step_texts)
        assert "Run migration" in combined
        assert "Test on staging" in combined

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 9. Detail screen shows timeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_screen_shows_timeline():
    """Verify timeline events appear."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(DetailScreen(db, "t2"))
        await pilot.pause()

        timeline = app.screen.query_one(Timeline)
        assert timeline is not None

        entries = app.screen.query(TimelineEntry)
        assert len(entries) == 1

        desc_widget = entries.first().query_one(".tl-desc")
        assert "Session started" in _get_text(desc_widget)

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 10. Back navigation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_back_navigation():
    """Escape from detail screen returns to list."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test(size=(120, 40)) as pilot:
        # Go to detail
        app.push_screen(DetailScreen(db, "t1"))
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)

        # Press escape to go back
        await pilot.press("escape")

        # Should be back on the default screen (not DetailScreen)
        assert not isinstance(app.screen, DetailScreen)

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 11. Search filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_filter():
    """Press /, type text, verify tasks are filtered."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test(size=(120, 40)) as pilot:
        # Initially 3 rows
        assert len(app.query(TaskRow)) == 3

        # Open search bar
        list_screen = app.query_one(ListScreen)
        list_screen.action_toggle_search()
        await pilot.pause()

        # Type into search input
        search_input = app.query_one("#search-input")
        search_input.focus()
        await pilot.press("R", "E", "A", "D", "M", "E")
        await pilot.pause()

        # Only the "Update README" task should remain
        rows = app.query(TaskRow)
        assert len(rows) == 1
        assert rows.first().task_data.title == "Update README"

        await pilot.exit(None)


# ---------------------------------------------------------------------------
# 12. Mark done from detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_done_from_detail():
    """Press d on detail screen, verify task status changes."""
    db, path = _make_db()
    _seed(db)
    app = _make_app(path)
    async with app.run_test(size=(120, 40)) as pilot:
        # Navigate to task t1 (action_required)
        app.push_screen(DetailScreen(db, "t1"))
        await pilot.pause()

        # Verify current status
        task_before = db.get_task("t1")
        assert task_before.status == "action_required"

        # Press 'd' to mark done
        await pilot.press("d")
        await pilot.pause()

        # Should pop back from detail screen
        assert not isinstance(app.screen, DetailScreen)

        # Verify DB updated
        task_after = db.get_task("t1")
        assert task_after.status == "done"
        assert task_after.completed_at is not None

        await pilot.exit(None)
