"""Tests for the hook system."""

import json

from task_pilot.db import Database
from task_pilot.hooks import (
    HookInstaller,
    handle_heartbeat,
    handle_session_end,
    handle_session_start,
    handle_stop,
)


def test_hook_installer_generates_config(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}")
    installer = HookInstaller(settings_path=settings_path)
    installer.install()
    settings = json.loads(settings_path.read_text())
    assert "hooks" in settings
    assert "SessionStart" in settings["hooks"]
    assert "SessionEnd" in settings["hooks"]
    assert "PostToolUse" in settings["hooks"]
    assert "Stop" in settings["hooks"]


def test_hook_installer_preserves_existing(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"env": {"FOO": "bar"}}))
    installer = HookInstaller(settings_path=settings_path)
    installer.install()
    settings = json.loads(settings_path.read_text())
    assert settings["env"]["FOO"] == "bar"
    assert "hooks" in settings


def test_hook_installer_creates_file_if_missing(tmp_path):
    settings_path = tmp_path / "subdir" / "settings.json"
    installer = HookInstaller(settings_path=settings_path)
    installer.install()
    assert settings_path.exists()
    settings = json.loads(settings_path.read_text())
    assert "hooks" in settings


def test_hook_installer_uninstall(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}")
    installer = HookInstaller(settings_path=settings_path)
    installer.install()
    installer.uninstall()
    settings = json.loads(settings_path.read_text())
    assert "hooks" not in settings


def test_handle_session_start(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        task_id = handle_session_start(
            db, session_id="sess-1", project_dir="/home/user/myproject", pid=1234
        )
        assert task_id is not None

        # Verify task was created
        task = db.get_task(task_id)
        assert task is not None
        assert task.title == "myproject"
        assert task.status == "working"

        # Verify session was created
        session = db.get_session("sess-1")
        assert session is not None
        assert session.task_id == task_id
        assert session.pid == 1234
        assert session.cwd == "/home/user/myproject"
        assert session.is_active is True

        # Verify timeline event
        assert len(task.timeline) == 1
        assert task.timeline[0].event_type == "session_start"
    finally:
        db.close()


def test_handle_session_start_existing_session(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        # First start
        task_id = handle_session_start(
            db, session_id="sess-1", project_dir="/home/user/myproject", pid=1234
        )
        # Second start with same session (reconnect)
        task_id_2 = handle_session_start(
            db, session_id="sess-1", project_dir="/home/user/myproject", pid=5678
        )
        assert task_id == task_id_2
    finally:
        db.close()


def test_handle_session_end(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        task_id = handle_session_start(
            db, session_id="sess-1", project_dir="/home/user/myproject", pid=1234
        )
        result = handle_session_end(db, session_id="sess-1")
        assert result == task_id

        # Verify task is done
        task = db.get_task(task_id)
        assert task.status == "done"
        assert task.completed_at is not None

        # Verify session is inactive
        session = db.get_session("sess-1")
        assert session.is_active is False
        assert session.ended_at is not None

        # Verify timeline events (start + end)
        assert len(task.timeline) == 2
        assert task.timeline[1].event_type == "session_end"
    finally:
        db.close()


def test_handle_session_end_unknown_session(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        result = handle_session_end(db, session_id="nonexistent")
        assert result is None
    finally:
        db.close()


def test_handle_stop_marks_action_required(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        task_id = handle_session_start(
            db, session_id="sess-1", project_dir="/home/user/myproject", pid=1234
        )
        result = handle_stop(db, session_id="sess-1")
        assert result == task_id

        # Verify task is action_required
        task = db.get_task(task_id)
        assert task.status == "action_required"

        # Verify timeline event
        assert len(task.timeline) == 2
        assert task.timeline[1].event_type == "blocked"
    finally:
        db.close()


def test_handle_stop_unknown_session(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        result = handle_stop(db, session_id="nonexistent")
        assert result is None
    finally:
        db.close()


def test_handle_heartbeat_marks_working(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        task_id = handle_session_start(
            db, session_id="sess-1", project_dir="/home/user/myproject", pid=1234
        )
        # Simulate stop first
        handle_stop(db, session_id="sess-1")
        task = db.get_task(task_id)
        assert task.status == "action_required"

        # Heartbeat should restore working status
        result = handle_heartbeat(db, session_id="sess-1")
        assert result == task_id

        task = db.get_task(task_id)
        assert task.status == "working"
    finally:
        db.close()


def test_handle_heartbeat_unknown_session(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        result = handle_heartbeat(db, session_id="nonexistent")
        assert result is None
    finally:
        db.close()
