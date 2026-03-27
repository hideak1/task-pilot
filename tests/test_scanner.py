"""Tests for the ClaudeScanner."""

import json
import time
import os
from pathlib import Path
from unittest import mock

import pytest

from task_pilot.db import Database
from task_pilot.scanner import ClaudeScanner


def setup_fake_claude_home(tmp_path):
    """Create a fake ~/.claude/ structure with test data."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    now_ms = int(time.time() * 1000)

    # Active session
    (sessions_dir / "12345.json").write_text(
        json.dumps(
            {
                "pid": 12345,
                "sessionId": "sess-aaa-bbb",
                "cwd": "/tmp/project",
                "startedAt": now_ms,
            }
        )
    )

    # Project transcript
    proj_dir = tmp_path / "projects" / "-tmp-project"
    proj_dir.mkdir(parents=True)
    transcript = proj_dir / "sess-aaa-bbb.jsonl"
    lines = [
        json.dumps(
            {
                "type": "user",
                "message": {"content": "Build a REST API"},
                "timestamp": now_ms,
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": "I'll create the API..."},
                "timestamp": now_ms + 1000,
            }
        ),
    ]
    transcript.write_text("\n".join(lines))

    # History
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps(
            {
                "display": "Build a REST API",
                "timestamp": now_ms,
                "sessionId": "sess-aaa-bbb",
                "project": "/tmp/project",
            }
        )
    )

    return tmp_path


@pytest.fixture
def fake_claude_home(tmp_path):
    return setup_fake_claude_home(tmp_path)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    yield database
    database.close()


class TestClaudeScanner:
    def test_scan_discovers_sessions_and_creates_tasks(self, fake_claude_home, db):
        """scan() should discover sessions and create tasks in the DB."""
        scanner = ClaudeScanner(claude_home=fake_claude_home, db=db)

        with mock.patch.object(scanner, "_is_pid_alive", return_value=True):
            scanner.scan()

        tasks = db.list_tasks()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.title == "Build a REST API"
        assert task.status == "working"
        assert len(task.sessions) == 1
        assert task.sessions[0].session_id == "sess-aaa-bbb"
        assert task.sessions[0].is_active is True
        assert task.sessions[0].pid == 12345

    def test_scan_inactive_session_when_pid_dead(self, fake_claude_home, db):
        """When PID is dead, session should be inactive and task status done."""
        scanner = ClaudeScanner(claude_home=fake_claude_home, db=db)

        with mock.patch.object(scanner, "_is_pid_alive", return_value=False):
            scanner.scan()

        tasks = db.list_tasks()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.status == "done"
        assert task.sessions[0].is_active is False

    def test_scan_updates_existing_session(self, fake_claude_home, db):
        """Rescanning should update existing sessions, not duplicate tasks."""
        scanner = ClaudeScanner(claude_home=fake_claude_home, db=db)

        # First scan: active
        with mock.patch.object(scanner, "_is_pid_alive", return_value=True):
            scanner.scan()

        tasks_before = db.list_tasks()
        assert len(tasks_before) == 1
        assert tasks_before[0].sessions[0].is_active is True

        # Second scan: PID died
        with mock.patch.object(scanner, "_is_pid_alive", return_value=False):
            scanner.scan()

        tasks_after = db.list_tasks()
        assert len(tasks_after) == 1  # Still one task, not two
        assert tasks_after[0].sessions[0].is_active is False

    def test_title_from_history(self, fake_claude_home, db):
        """Title should be taken from history.jsonl display field."""
        scanner = ClaudeScanner(claude_home=fake_claude_home, db=db)

        with mock.patch.object(scanner, "_is_pid_alive", return_value=False):
            scanner.scan()

        task = db.list_tasks()[0]
        assert task.title == "Build a REST API"

    def test_title_from_transcript_when_no_history(self, tmp_path, db):
        """When history has no entry, title comes from first user message."""
        # Create structure with transcript but no history entry for it
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        proj_dir = tmp_path / "projects" / "-tmp-other"
        proj_dir.mkdir(parents=True)
        transcript = proj_dir / "sess-xxx-yyy.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": {"content": "Fix the login bug"},
                    "timestamp": int(time.time() * 1000),
                }
            )
        )

        # Empty history
        (tmp_path / "history.jsonl").write_text("")

        scanner = ClaudeScanner(claude_home=tmp_path, db=db)
        with mock.patch.object(scanner, "_is_pid_alive", return_value=False):
            scanner.scan()

        task = db.list_tasks()[0]
        assert task.title == "Fix the login bug"

    def test_is_pid_alive_with_current_process(self):
        """_is_pid_alive should return True for the current process."""
        scanner = ClaudeScanner(claude_home=Path("/nonexistent"), db=None)
        assert scanner._is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_with_dead_pid(self):
        """_is_pid_alive should return False for a non-existent PID."""
        scanner = ClaudeScanner(claude_home=Path("/nonexistent"), db=None)
        # Use a very large PID that's unlikely to exist
        assert scanner._is_pid_alive(999999999) is False

    def test_title_from_transcript(self, tmp_path):
        """title_from_transcript should return the first user message content."""
        from task_pilot.summarizer import Summarizer
        transcript = tmp_path / "test.jsonl"
        lines = [
            json.dumps(
                {"type": "user", "message": {"content": "Hello world"}, "timestamp": 1}
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": "Hi there"},
                    "timestamp": 2,
                }
            ),
        ]
        transcript.write_text("\n".join(lines))

        summarizer = Summarizer()
        title = summarizer.title_from_transcript(transcript)
        assert title == "Hello world"

    def test_title_truncates_long_content(self, tmp_path):
        """Long user messages should be truncated to 60 chars."""
        from task_pilot.summarizer import Summarizer
        transcript = tmp_path / "test.jsonl"
        long_msg = "A" * 200
        transcript.write_text(
            json.dumps(
                {"type": "user", "message": {"content": long_msg}, "timestamp": 1}
            )
        )

        summarizer = Summarizer()
        title = summarizer.title_from_transcript(transcript)
        assert len(title) == 60
        assert title.endswith("...")

    def test_scan_empty_claude_home(self, tmp_path, db):
        """Scanning an empty claude home should not crash."""
        scanner = ClaudeScanner(claude_home=tmp_path, db=db)
        scanner.scan()
        assert db.list_tasks() == []

    def test_scan_creates_timeline_event(self, fake_claude_home, db):
        """scan() should create a timeline event for newly discovered sessions."""
        scanner = ClaudeScanner(claude_home=fake_claude_home, db=db)

        with mock.patch.object(scanner, "_is_pid_alive", return_value=True):
            scanner.scan()

        task = db.list_tasks()[0]
        assert len(task.timeline) == 1
        assert task.timeline[0].event_type == "session_discovered"

    def test_find_transcript(self, fake_claude_home):
        """_find_transcript should locate a transcript by session ID."""
        scanner = ClaudeScanner(claude_home=fake_claude_home, db=None)
        result = scanner._find_transcript("sess-aaa-bbb")
        assert result is not None
        assert result.name == "sess-aaa-bbb.jsonl"

    def test_find_transcript_not_found(self, fake_claude_home):
        """_find_transcript should return None for unknown session IDs."""
        scanner = ClaudeScanner(claude_home=fake_claude_home, db=None)
        result = scanner._find_transcript("nonexistent-session")
        assert result is None

    def test_scan_session_without_transcript(self, tmp_path, db):
        """A session file with no matching transcript should still create a task."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        (sessions_dir / "99999.json").write_text(
            json.dumps(
                {
                    "pid": 99999,
                    "sessionId": "sess-no-transcript",
                    "cwd": "/tmp/orphan",
                    "startedAt": int(time.time() * 1000),
                }
            )
        )

        scanner = ClaudeScanner(claude_home=tmp_path, db=db)
        with mock.patch.object(scanner, "_is_pid_alive", return_value=False):
            scanner.scan()

        tasks = db.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Untitled"
