"""Comprehensive end-to-end test suite for Task Pilot.

Covers:
  1. Full hook lifecycle
  2. Scanner + DB integration
  3. Hook -> Scanner coexistence
  4. Summarizer integration
  5. CLI entry point E2E
  6. TUI full flow (Textual headless)
  7. Edge cases
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from task_pilot.app import TaskPilotApp
from task_pilot.cli import main
from task_pilot.db import Database
from task_pilot import hooks as hooks_module
from task_pilot.hooks import (
    HookInstaller,
    handle_heartbeat,
    handle_session_end,
    handle_session_start,
    handle_stop,
)
from task_pilot.models import Task
from task_pilot.scanner import ClaudeScanner
from task_pilot.screens.detail_screen import DetailScreen
from task_pilot.screens.list_screen import ListScreen
from task_pilot.summarizer import Summarizer
from task_pilot.widgets.action_steps import ActionStepRow, ActionSteps
from task_pilot.widgets.header_bar import HeaderBar
from task_pilot.widgets.task_row import TaskRow
from task_pilot.widgets.timeline import Timeline, TimelineEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_heartbeat_throttle():
    """Clear heartbeat throttle cache before each test."""
    hooks_module._last_heartbeat.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Database:
    db_path = tmp_path / "e2e_test.db"
    return Database(db_path)


def _make_app(db_path, claude_home: Path | None = None) -> TaskPilotApp:
    if claude_home is None:
        claude_home = Path(tempfile.mkdtemp())
    return TaskPilotApp(db_path=db_path, claude_home=claude_home)


def _get_text(widget) -> str:
    return str(widget.render())


def _build_fake_claude_home(
    tmp_path: Path,
    sessions: list[dict] | None = None,
    transcripts: dict[str, list[dict]] | None = None,
    history: list[dict] | None = None,
) -> Path:
    """Build a fake ~/.claude/ directory structure for scanner tests."""
    claude_home = tmp_path / "fake_claude"
    claude_home.mkdir()

    # sessions/*.json
    if sessions:
        sessions_dir = claude_home / "sessions"
        sessions_dir.mkdir()
        for sess in sessions:
            sid = sess["sessionId"]
            (sessions_dir / f"{sid}.json").write_text(json.dumps(sess))

    # projects/<project>/<session_id>.jsonl
    if transcripts:
        projects_dir = claude_home / "projects"
        projects_dir.mkdir()
        proj_dir = projects_dir / "my-project"
        proj_dir.mkdir()
        for sid, messages in transcripts.items():
            lines = [json.dumps(m) for m in messages]
            (proj_dir / f"{sid}.jsonl").write_text("\n".join(lines))

    # history.jsonl
    if history:
        lines = [json.dumps(h) for h in history]
        (claude_home / "history.jsonl").write_text("\n".join(lines))

    return claude_home


def _build_transcript_file(tmp_path: Path, messages: list[dict]) -> Path:
    """Write a transcript .jsonl file and return the path."""
    transcript = tmp_path / "transcript.jsonl"
    lines = [json.dumps(m) for m in messages]
    transcript.write_text("\n".join(lines))
    return transcript


# ===========================================================================
# Scenario 1: Full Hook Lifecycle
# ===========================================================================


class TestScenario1FullHookLifecycle:
    """Simulate a complete Claude Code session lifecycle through hook handlers."""

    def test_full_lifecycle_with_heartbeats(self, tmp_path: Path):
        db = _make_db(tmp_path)
        session_id = "e2e-sess-001"
        project_dir = "/tmp/my-awesome-project"
        pid = 54321

        # 1. session-start -> creates task + session, status=working
        task_id = handle_session_start(db, session_id, project_dir, pid)
        assert task_id is not None
        task = db.get_task(task_id)
        assert task.status == "working"
        assert task.title == "my-awesome-project"
        session = db.get_session(session_id)
        assert session.is_active is True
        assert session.pid == pid

        initial_updated = task.updated_at

        # 2. heartbeat -> task stays working (throttled: only first one writes)
        hb_id = handle_heartbeat(db, session_id)
        assert hb_id == task_id
        task = db.get_task(task_id)
        assert task.status == "working"
        assert task.updated_at >= initial_updated

        # Subsequent heartbeats within 30s are throttled (return None)
        hb_id2 = handle_heartbeat(db, session_id)
        assert hb_id2 is None

        # 3. stop -> task becomes action_required
        stop_id = handle_stop(db, session_id)
        assert stop_id == task_id
        task = db.get_task(task_id)
        assert task.status == "action_required"

        # 4. session-start (same session_id, resume) -> back to working
        resume_id = handle_session_start(db, session_id, project_dir, pid)
        assert resume_id == task_id  # same task reused, no duplicate
        task = db.get_task(task_id)
        assert task.status == "working"

        # 5. session-end -> task becomes done, session inactive
        end_id = handle_session_end(db, session_id)
        assert end_id == task_id
        task = db.get_task(task_id)
        assert task.status == "done"
        assert task.completed_at is not None

        session = db.get_session(session_id)
        assert session.is_active is False
        assert session.ended_at is not None

        # 6. Verify: all timeline events recorded in correct order
        events = task.timeline
        event_types = [e.event_type for e in events]
        assert event_types == [
            "session_start",
            "blocked",
            "session_start",
            "session_end",
        ]

        # 7. Verify session_ids on events
        for e in events:
            assert e.session_id == session_id
            assert e.task_id == task_id

        db.close()


# ===========================================================================
# Scenario 2: Scanner + DB Integration
# ===========================================================================


class TestScenario2ScannerDBIntegration:
    """Create fake ~/.claude/ structure, run scanner, verify DB."""

    def test_scanner_discovers_sessions(self, tmp_path: Path):
        # Use a PID that's definitely dead
        dead_pid = 2999999

        # Sessions: one with transcript, one without
        claude_home = _build_fake_claude_home(
            tmp_path,
            sessions=[
                {
                    "sessionId": "scan-sess-1",
                    "pid": dead_pid,
                    "cwd": "/tmp/proj-a",
                    "startedAt": int(time.time() * 1000),
                },
                {
                    "sessionId": "scan-sess-2",
                    "pid": dead_pid,
                    "cwd": "/tmp/proj-b",
                    "startedAt": int(time.time() * 1000),
                },
            ],
            transcripts={
                "scan-sess-1": [
                    {"type": "user", "message": {"content": "Build me a REST API"}},
                    {"type": "assistant", "message": {"content": "Sure, I will build a REST API."}},
                ],
            },
            history=[
                {"sessionId": "scan-sess-2", "display": "Fix database migration"},
            ],
        )

        db = _make_db(tmp_path)
        scanner = ClaudeScanner(claude_home=claude_home, db=db)
        scanner.scan()

        # Both sessions should have created tasks
        all_tasks = db.list_tasks()
        assert len(all_tasks) == 2

        # Verify session-1 title from transcript (first user message)
        sess1_task_id = db.get_task_id_for_session("scan-sess-1")
        assert sess1_task_id is not None
        task1 = db.get_task(sess1_task_id)
        assert task1.title == "Build me a REST API"

        # Verify session-2 title from history
        sess2_task_id = db.get_task_id_for_session("scan-sess-2")
        assert sess2_task_id is not None
        task2 = db.get_task(sess2_task_id)
        assert task2.title == "Fix database migration"

        # Dead PID -> sessions inactive, tasks done
        sess1 = db.get_session("scan-sess-1")
        assert sess1.is_active is False
        assert task1.status == "done"

        sess2 = db.get_session("scan-sess-2")
        assert sess2.is_active is False
        assert task2.status == "done"

        db.close()

    def test_scanner_session_without_transcript_or_history(self, tmp_path: Path):
        """Sessions with neither transcript nor history get 'Untitled'."""
        claude_home = _build_fake_claude_home(
            tmp_path,
            sessions=[
                {
                    "sessionId": "scan-sess-orphan",
                    "pid": 2999999,
                    "cwd": "/tmp/orphan",
                    "startedAt": int(time.time() * 1000),
                },
            ],
        )

        db = _make_db(tmp_path)
        scanner = ClaudeScanner(claude_home=claude_home, db=db)
        scanner.scan()

        task_id = db.get_task_id_for_session("scan-sess-orphan")
        task = db.get_task(task_id)
        assert task.title == "Untitled"

        db.close()

    def test_scanner_transcript_only_no_session_file(self, tmp_path: Path):
        """Transcript exists without a session JSON -> still discovered."""
        claude_home = _build_fake_claude_home(
            tmp_path,
            transcripts={
                "transcript-only-sess": [
                    {"type": "user", "message": {"content": "Deploy to production"}},
                ],
            },
        )

        db = _make_db(tmp_path)
        scanner = ClaudeScanner(claude_home=claude_home, db=db)
        scanner.scan()

        task_id = db.get_task_id_for_session("transcript-only-sess")
        assert task_id is not None
        task = db.get_task(task_id)
        assert task.title == "Deploy to production"

        db.close()


# ===========================================================================
# Scenario 3: Hook -> Scanner Coexistence
# ===========================================================================


class TestScenario3HookScannerCoexistence:
    """Hook-created tasks should not be duplicated by scanner."""

    def test_scanner_does_not_duplicate_hook_created_tasks(self, tmp_path: Path):
        db = _make_db(tmp_path)

        # 1. Create task via hooks
        session_id = "coexist-sess-1"
        task_id = handle_session_start(db, session_id, "/tmp/coexist-proj", 12345)

        task_before = db.get_task(task_id)
        assert task_before is not None

        # 2. Build a fake claude_home that includes the same session
        claude_home = _build_fake_claude_home(
            tmp_path,
            sessions=[
                {
                    "sessionId": session_id,
                    "pid": 2999999,  # dead pid
                    "cwd": "/tmp/coexist-proj",
                    "startedAt": int(time.time() * 1000),
                },
            ],
            transcripts={
                session_id: [
                    {"type": "user", "message": {"content": "Do something cool"}},
                ],
            },
        )

        # 3. Run scanner
        scanner = ClaudeScanner(claude_home=claude_home, db=db)
        scanner.scan()

        # 4. Verify: no duplicate tasks
        all_tasks = db.list_tasks()
        assert len(all_tasks) == 1

        # 5. Verify: scanner updated existing session data (e.g., transcript_path)
        session = db.get_session(session_id)
        assert session.transcript_path is not None
        assert session_id in session.transcript_path

        # Task ID should be the same
        assert db.get_task_id_for_session(session_id) == task_id

        db.close()


# ===========================================================================
# Scenario 4: Summarizer Integration
# ===========================================================================


class TestScenario4SummarizerIntegration:
    """Run summarizer on transcript, store results in DB."""

    def test_summarizer_heuristic_and_action_items(self, tmp_path: Path):
        # Build a realistic transcript
        messages = [
            {"type": "user", "message": {"content": "Set up CI/CD pipeline for the project"}},
            {
                "type": "assistant",
                "message": {
                    "content": (
                        "I've set up the CI/CD pipeline. Here are the remaining steps:\n"
                        "1. Copy the deploy key to the server\n"
                        "2. Run the first deployment manually\n"
                        "3. Verify the webhook is working\n"
                        "\nYou need to run: scp deploy-key.pem user@server:/keys/\n"
                        "Please run `ssh user@server 'systemctl restart deploy'`"
                    )
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": "All done! The pipeline is configured and ready."
                },
            },
        ]
        transcript_path = _build_transcript_file(tmp_path, messages)

        summarizer = Summarizer()
        summary = summarizer.summarize(transcript_path)

        assert summary is not None
        assert "CI/CD" in summary or "Set up" in summary

        # Extract action items
        action_items = summarizer.extract_action_items(transcript_path)
        assert len(action_items) > 0

        # Should find numbered items and command-keyword items
        combined = " ".join(action_items)
        assert "Copy the deploy key" in combined or "deploy key" in combined.lower()

        # Store in DB
        db = _make_db(tmp_path)
        task_id = "summarizer-task-1"
        db.upsert_task(task_id=task_id, title="CI/CD Setup", status="done", summary=summary)

        for item_text in action_items:
            db.add_action_item(task_id, item_text)

        # Verify stored correctly
        task = db.get_task(task_id)
        assert task.summary == summary
        assert len(task.action_items) == len(action_items)
        for ai in task.action_items:
            assert ai.description in action_items

        db.close()

    def test_summarizer_empty_transcript(self, tmp_path: Path):
        """Empty transcript returns None summary and no action items."""
        transcript_path = tmp_path / "empty.jsonl"
        transcript_path.write_text("")

        summarizer = Summarizer()
        summary = summarizer.summarize(transcript_path)
        assert summary is None

        items = summarizer.extract_action_items(transcript_path)
        assert items == []

    def test_summarizer_nonexistent_file(self, tmp_path: Path):
        """Non-existent transcript returns None / empty."""
        fake_path = tmp_path / "nonexistent.jsonl"

        summarizer = Summarizer()
        summary = summarizer.summarize(fake_path)
        assert summary is None

        items = summarizer.extract_action_items(fake_path)
        assert items == []


# ===========================================================================
# Scenario 5: CLI Entry Point E2E
# ===========================================================================


class TestScenario5CLIEntryPoint:
    """Use Click's CliRunner to test all CLI commands end-to-end."""

    def test_install_hooks(self, tmp_path: Path):
        """install-hooks writes hooks config to settings file."""
        settings_file = tmp_path / "settings.json"

        with patch("task_pilot.cli.CLAUDE_SETTINGS_FILE", settings_file):
            runner = CliRunner()
            result = runner.invoke(main, ["install-hooks"])

        assert result.exit_code == 0
        assert "Hooks installed" in result.output

        settings = json.loads(settings_file.read_text())
        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]
        assert "PostToolUse" in settings["hooks"]
        assert "Stop" in settings["hooks"]
        assert "SessionEnd" in settings["hooks"]

    def test_hook_session_lifecycle_via_cli(self, tmp_path: Path):
        """Run hook commands via CLI with env vars, verify DB state."""
        db_path = tmp_path / "cli_test.db"
        session_id = "cli-e2e-sess"

        env = {
            "CLAUDE_SESSION_ID": session_id,
            "CLAUDE_PROJECT_DIR": "/tmp/cli-project",
        }

        runner = CliRunner(env=env)

        with patch("task_pilot.cli.DB_PATH", db_path):
            # session-start
            result = runner.invoke(main, ["hook", "session-start"])
            assert result.exit_code == 0

            # Verify task created
            db = Database(db_path)
            task_id = db.get_task_id_for_session(session_id)
            assert task_id is not None
            task = db.get_task(task_id)
            assert task.status == "working"

            # heartbeat
            result = runner.invoke(main, ["hook", "heartbeat"])
            assert result.exit_code == 0
            task = db.get_task(task_id)
            assert task.status == "working"

            # stop
            result = runner.invoke(main, ["hook", "stop"])
            assert result.exit_code == 0
            task = db.get_task(task_id)
            assert task.status == "action_required"

            # session-end
            result = runner.invoke(main, ["hook", "session-end"])
            assert result.exit_code == 0
            task = db.get_task(task_id)
            assert task.status == "done"

            db.close()

    def test_scan_command_runs(self, tmp_path: Path):
        """scan command completes without error."""
        db_path = tmp_path / "scan_cli.db"
        # Create empty claude home so scan has nothing but succeeds
        claude_home = tmp_path / "empty_claude"
        claude_home.mkdir()

        runner = CliRunner()
        with patch("task_pilot.cli.DB_PATH", db_path):
            # Patch the scanner's default claude_home
            with patch("task_pilot.scanner.Path.home", return_value=tmp_path):
                result = runner.invoke(main, ["scan"])

        assert result.exit_code == 0
        assert "Scan complete" in result.output


# ===========================================================================
# Scenario 6: TUI Full Flow (Textual headless)
# ===========================================================================


def _seed_full(db: Database) -> dict:
    """Seed DB with tasks in all statuses, action items, timeline events.

    Returns dict of task_ids by status for lookup.
    """
    # action_required task with action items
    db.upsert_task("t-action", title="Fix authentication bug", status="action_required",
                    summary="Auth middleware rejects valid tokens")
    db.add_action_item("t-action", "Run database migration", command="python manage.py migrate")
    db.add_action_item("t-action", "Restart auth service", command="systemctl restart auth")
    db.upsert_session("s-action", task_id="t-action", started_at=time.time())
    db.add_timeline_event("t-action", session_id="s-action", event_type="session_start",
                          description="Session started in /projects/auth")
    db.add_timeline_event("t-action", session_id="s-action", event_type="blocked",
                          description="User interrupted - needs manual migration")

    # working task
    db.upsert_task("t-working", title="Build REST API endpoints", status="working",
                    summary="Implementing CRUD for users and orders")
    db.upsert_session("s-working", task_id="t-working", started_at=time.time())
    db.add_timeline_event("t-working", session_id="s-working", event_type="session_start",
                          description="Session started in /projects/api")

    # done task
    db.upsert_task("t-done", title="Update project README", status="done",
                    summary="Added installation and usage instructions")

    # pending task
    db.upsert_task("t-pending", title="Write integration tests", status="pending")

    return {
        "action_required": "t-action",
        "working": "t-working",
        "done": "t-done",
        "pending": "t-pending",
    }


@pytest.mark.asyncio
async def test_scenario6_tui_list_screen_renders(tmp_path: Path):
    """Launch app -> verify list screen renders all sections."""
    db = _make_db(tmp_path)
    _seed_full(db)
    app = _make_app(db.db_path)

    async with app.run_test(size=(120, 40)) as pilot:
        # All 4 tasks should appear as TaskRows
        rows = app.query(TaskRow)
        assert len(rows) == 4

        # Section labels should be present
        section_labels = app.query(".section-label")
        combined = " ".join(_get_text(lbl) for lbl in section_labels)
        assert "需要你操作" in combined
        assert "Claude 工作中" in combined
        assert "已完成" in combined

        await pilot.exit(None)


@pytest.mark.asyncio
async def test_scenario6_tui_navigate_to_detail(tmp_path: Path):
    """Navigate to a task with action items -> verify detail screen."""
    db = _make_db(tmp_path)
    _seed_full(db)
    app = _make_app(db.db_path)

    async with app.run_test(size=(120, 40)) as pilot:
        # Push detail screen for action_required task
        app.push_screen(DetailScreen(db, "t-action"))
        await pilot.pause()

        assert isinstance(app.screen, DetailScreen)

        # Title
        title_w = app.screen.query_one(".detail-title")
        assert "Fix authentication bug" in _get_text(title_w)

        # Summary
        summary_widgets = app.screen.query(".summary-text")
        assert len(summary_widgets) > 0
        assert "Auth middleware" in _get_text(summary_widgets.first())

        # Action steps
        steps = app.screen.query(ActionStepRow)
        assert len(steps) == 2

        # Timeline
        timeline = app.screen.query_one(Timeline)
        assert timeline is not None
        entries = app.screen.query(TimelineEntry)
        assert len(entries) == 2

        await pilot.exit(None)


@pytest.mark.asyncio
async def test_scenario6_tui_toggle_action_item(tmp_path: Path):
    """Toggle an action item -> verify DB updated."""
    db = _make_db(tmp_path)
    _seed_full(db)
    app = _make_app(db.db_path)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(DetailScreen(db, "t-action"))
        await pilot.pause()

        # Get the first action item's ID
        task = db.get_task("t-action")
        first_item_id = task.action_items[0].id
        assert task.action_items[0].is_done is False

        # Toggle it via the DB directly (simulating what click handler does)
        db.toggle_action_item(first_item_id)

        # Verify DB updated
        task = db.get_task("t-action")
        assert task.action_items[0].is_done is True

        await pilot.exit(None)


@pytest.mark.asyncio
async def test_scenario6_tui_mark_done(tmp_path: Path):
    """Press d (done) -> verify task marked done, returns to list."""
    db = _make_db(tmp_path)
    _seed_full(db)
    app = _make_app(db.db_path)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(DetailScreen(db, "t-action"))
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)

        # Press 'd'
        await pilot.press("d")
        await pilot.pause()

        # Should be back on list
        assert not isinstance(app.screen, DetailScreen)

        # DB should reflect done
        task = db.get_task("t-action")
        assert task.status == "done"
        assert task.completed_at is not None

        await pilot.exit(None)


@pytest.mark.asyncio
async def test_scenario6_tui_go_back(tmp_path: Path):
    """Go back from detail -> verify list updated."""
    db = _make_db(tmp_path)
    _seed_full(db)
    app = _make_app(db.db_path)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(DetailScreen(db, "t-action"))
        await pilot.pause()

        await pilot.press("escape")
        assert not isinstance(app.screen, DetailScreen)

        # List should still show tasks
        rows = app.query(TaskRow)
        assert len(rows) >= 1

        await pilot.exit(None)


@pytest.mark.asyncio
async def test_scenario6_tui_search(tmp_path: Path):
    """Search for a task -> verify filter works. Escape -> search cleared."""
    db = _make_db(tmp_path)
    _seed_full(db)
    app = _make_app(db.db_path)

    async with app.run_test(size=(120, 40)) as pilot:
        # Initially 4 rows
        assert len(app.query(TaskRow)) == 4

        # Open search
        list_screen = app.query_one(ListScreen)
        list_screen.action_toggle_search()
        await pilot.pause()

        # Type search query
        search_input = app.query_one("#search-input")
        search_input.focus()
        await pilot.press("R", "E", "A", "D", "M", "E")
        await pilot.pause()

        # Only "Update project README" should match
        rows = app.query(TaskRow)
        assert len(rows) == 1
        assert "README" in rows.first().task_data.title

        # Close search with escape
        list_screen.action_close_search()
        await pilot.pause()

        # All tasks should be back
        rows = app.query(TaskRow)
        assert len(rows) == 4

        await pilot.exit(None)


# ===========================================================================
# Scenario 7: Edge Cases
# ===========================================================================


class TestScenario7EdgeCases:
    """Edge case handling."""

    @pytest.mark.asyncio
    async def test_empty_db_shows_empty_state(self, tmp_path: Path):
        """Empty DB -> app shows empty state."""
        db = _make_db(tmp_path)
        app = _make_app(db.db_path)

        async with app.run_test(size=(120, 40)) as pilot:
            hints = app.query(".empty-hint")
            assert len(hints) == 1
            assert "No tasks yet" in _get_text(hints.first())
            await pilot.exit(None)

    @pytest.mark.asyncio
    async def test_task_with_no_sessions(self, tmp_path: Path):
        """Task with no sessions -> detail screen handles gracefully."""
        db = _make_db(tmp_path)
        db.upsert_task("t-nosess", title="No Sessions Task", status="pending")
        app = _make_app(db.db_path)

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(DetailScreen(db, "t-nosess"))
            await pilot.pause()

            # Should show 0 sessions
            badge = app.screen.query_one(".badge-row")
            assert "0 session" in _get_text(badge)

            await pilot.exit(None)

    @pytest.mark.asyncio
    async def test_task_with_no_action_items(self, tmp_path: Path):
        """Task with no action items -> detail shows summary only, no ActionSteps."""
        db = _make_db(tmp_path)
        db.upsert_task("t-noitems", title="No Items", status="done",
                        summary="Everything is done")
        app = _make_app(db.db_path)

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(DetailScreen(db, "t-noitems"))
            await pilot.pause()

            # Summary should appear
            summary_widgets = app.screen.query(".summary-text")
            assert len(summary_widgets) > 0
            assert "Everything is done" in _get_text(summary_widgets.first())

            # ActionSteps widget should NOT exist
            action_steps = app.screen.query(ActionSteps)
            assert len(action_steps) == 0

            await pilot.exit(None)

    @pytest.mark.asyncio
    async def test_very_long_task_title_truncated(self, tmp_path: Path):
        """Very long task title -> truncated in list view."""
        db = _make_db(tmp_path)
        long_title = "A" * 200
        db.upsert_task("t-long", title=long_title, status="working")
        app = _make_app(db.db_path)

        async with app.run_test(size=(120, 40)) as pilot:
            rows = app.query(TaskRow)
            assert len(rows) == 1

            # TaskRow truncates at 60 chars -> 57 + "..."
            title_widget = rows.first().query_one(".title")
            rendered = _get_text(title_widget)
            assert len(rendered) <= 61  # 57 + "..." = 60
            assert rendered.endswith("...")

            await pilot.exit(None)

    @pytest.mark.asyncio
    async def test_multiple_sessions_for_one_task(self, tmp_path: Path):
        """Multiple sessions for one task -> detail shows correct count."""
        db = _make_db(tmp_path)
        db.upsert_task("t-multi", title="Multi Sessions", status="working")
        db.upsert_session("sess-a", task_id="t-multi", started_at=time.time())
        db.upsert_session("sess-b", task_id="t-multi", started_at=time.time())
        db.upsert_session("sess-c", task_id="t-multi", started_at=time.time())
        app = _make_app(db.db_path)

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(DetailScreen(db, "t-multi"))
            await pilot.pause()

            badge = app.screen.query_one(".badge-row")
            assert "3 session" in _get_text(badge)

            await pilot.exit(None)

    def test_hook_with_empty_session_id(self, tmp_path: Path):
        """Hook called with empty session_id -> handles gracefully."""
        db = _make_db(tmp_path)

        # session-start with empty session_id - should still create a task
        # (the function doesn't guard against empty, but it shouldn't crash)
        task_id = handle_session_start(db, "", "/tmp/empty-sess", 12345)
        assert task_id is not None

        # heartbeat / stop / end with empty session_id on unknown session
        # should return None (no crash)
        result = handle_heartbeat(db, "nonexistent-empty")
        assert result is None

        result = handle_stop(db, "nonexistent-empty")
        assert result is None

        result = handle_session_end(db, "nonexistent-empty")
        assert result is None

        db.close()

    def test_scanner_with_empty_claude_home(self, tmp_path: Path):
        """Scanner with completely empty claude home -> no crash."""
        empty_home = tmp_path / "empty_claude_home"
        empty_home.mkdir()

        db = _make_db(tmp_path)
        scanner = ClaudeScanner(claude_home=empty_home, db=db)
        scanner.scan()

        assert db.list_tasks() == []
        db.close()

    def test_scanner_with_malformed_json(self, tmp_path: Path):
        """Scanner handles malformed JSON files gracefully."""
        claude_home = tmp_path / "bad_claude"
        claude_home.mkdir()
        sessions_dir = claude_home / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "bad.json").write_text("NOT VALID JSON{{{")

        db = _make_db(tmp_path)
        scanner = ClaudeScanner(claude_home=claude_home, db=db)
        scanner.scan()  # should not raise

        assert db.list_tasks() == []
        db.close()
