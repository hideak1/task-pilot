"""Hook system for integrating Task Pilot with Claude Code."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from task_pilot.db import Database

HOOKS_CONFIG = {
    "SessionStart": [
        {
            "matcher": "*",
            "hooks": [
                {
                    "type": "command",
                    "command": "task-pilot hook session-start",
                    "timeout": 5,
                }
            ],
        }
    ],
    "PostToolUse": [
        {
            "matcher": "*",
            "hooks": [
                {
                    "type": "command",
                    "command": "task-pilot hook heartbeat",
                    "timeout": 3,
                }
            ],
        }
    ],
    "Stop": [
        {
            "matcher": "*",
            "hooks": [
                {
                    "type": "command",
                    "command": "task-pilot hook stop",
                    "timeout": 5,
                }
            ],
        }
    ],
    "SessionEnd": [
        {
            "matcher": "*",
            "hooks": [
                {
                    "type": "command",
                    "command": "task-pilot hook session-end",
                    "timeout": 5,
                }
            ],
        }
    ],
}


class HookInstaller:
    """Reads Claude Code settings.json, merges Task Pilot hooks, writes back."""

    def __init__(self, settings_path: str | Path | None = None):
        if settings_path is None:
            settings_path = (
                Path.home() / ".claude" / "settings.json"
            )
        self.settings_path = Path(settings_path)

    def install(self) -> None:
        """Install Task Pilot hooks into Claude Code settings."""
        settings = self._read_settings()
        settings["hooks"] = HOOKS_CONFIG
        self._write_settings(settings)

    def uninstall(self) -> None:
        """Remove Task Pilot hooks from Claude Code settings."""
        settings = self._read_settings()
        settings.pop("hooks", None)
        self._write_settings(settings)

    def _read_settings(self) -> dict:
        if self.settings_path.exists():
            return json.loads(self.settings_path.read_text())
        return {}

    def _write_settings(self, settings: dict) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(settings, indent=2) + "\n")


def handle_session_start(
    db: Database, session_id: str, project_dir: str, pid: int
) -> str:
    """Handle a Claude Code session starting.

    Returns the task_id associated with the session.
    """
    # Check if session already has a task
    task_id = db.get_task_id_for_session(session_id)

    if task_id is None:
        # Create a new task
        task_id = uuid.uuid4().hex[:12]
        title = os.path.basename(project_dir) or "Untitled"
        db.upsert_task(task_id=task_id, title=title, status="working")
    else:
        # Existing task — set status to working
        db.update_task_status(task_id, "working")

    # Upsert session record
    db.upsert_session(
        session_id=session_id,
        task_id=task_id,
        pid=pid,
        cwd=project_dir,
        is_active=True,
    )

    # Add timeline event
    db.add_timeline_event(
        task_id=task_id,
        session_id=session_id,
        event_type="session_start",
        description=f"Session started in {project_dir}",
    )

    return task_id


def handle_session_end(db: Database, session_id: str) -> str | None:
    """Handle a Claude Code session ending.

    Returns the task_id, or None if session not found.
    """
    task_id = db.get_task_id_for_session(session_id)
    if task_id is None:
        return None

    db.mark_session_inactive(session_id)
    db.mark_task_done(task_id)

    # Generate heuristic summary (zero cost, no external calls)
    session = db.get_session(session_id)
    if session and session.transcript_path:
        try:
            from pathlib import Path

            from task_pilot.summarizer import Summarizer

            summarizer = Summarizer()
            transcript_path = Path(session.transcript_path)
            if transcript_path.exists():
                task = db.get_task(task_id)
                if task and not task.summary:
                    summary = summarizer.summarize(
                        transcript_path, use_ai=False
                    )
                    if summary:
                        db.upsert_task(
                            task_id=task_id,
                            title=task.title,
                            status="done",
                            summary=summary,
                        )
        except Exception:
            pass

    db.add_timeline_event(
        task_id=task_id,
        session_id=session_id,
        event_type="session_end",
        description="Session ended",
    )

    return task_id


def handle_stop(db: Database, session_id: str) -> str | None:
    """Handle a Claude Code stop (user interrupted).

    Returns the task_id, or None if session not found.
    """
    task_id = db.get_task_id_for_session(session_id)
    if task_id is None:
        return None

    db.update_task_status(task_id, "action_required")

    db.add_timeline_event(
        task_id=task_id,
        session_id=session_id,
        event_type="blocked",
        description="User interrupted — action required",
    )

    return task_id


_last_heartbeat: dict[str, float] = {}
HEARTBEAT_THROTTLE_SECONDS = 30


def handle_heartbeat(db: Database, session_id: str) -> str | None:
    """Handle a heartbeat from a Claude Code session.

    Throttled: writes to DB at most once per 30 seconds per session.
    Returns the task_id, or None if session not found or throttled.
    """
    import time

    now = time.time()
    last = _last_heartbeat.get(session_id, 0)
    if now - last < HEARTBEAT_THROTTLE_SECONDS:
        return None  # throttled, skip DB write

    task_id = db.get_task_id_for_session(session_id)
    if task_id is None:
        return None

    db.update_task_status(task_id, "working")
    _last_heartbeat[session_id] = now

    return task_id
