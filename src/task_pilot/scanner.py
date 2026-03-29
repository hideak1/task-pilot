"""Scanner for Claude Code sessions and transcripts."""

import json
import logging
import os
import re
import uuid
from pathlib import Path

from task_pilot.db import Database
from task_pilot.summarizer import Summarizer

logger = logging.getLogger(__name__)


class ClaudeScanner:
    """Scans ~/.claude/ for sessions, transcripts, and history to populate the task DB."""

    def __init__(self, claude_home: Path | None = None, db: Database | None = None):
        if claude_home is None:
            claude_home = Path.home() / ".claude"
        self.claude_home = claude_home
        self.db = db
        self.summarizer = Summarizer()

        self.sessions_dir = self.claude_home / "sessions"
        self.projects_dir = self.claude_home / "projects"
        self.history_file = self.claude_home / "history.jsonl"

    def scan(self):
        """Run a full scan: sessions, history, transcripts, then reconcile."""
        active_sessions = self._scan_sessions()
        history_titles = self._scan_history()
        transcript_sessions = self._scan_transcripts()

        all_session_ids = set(active_sessions.keys()) | set(transcript_sessions.keys())

        for session_id in all_session_ids:
            active_info = active_sessions.get(session_id)
            transcript_path = transcript_sessions.get(session_id)

            pid = active_info["pid"] if active_info else None
            is_active = pid is not None and self._is_pid_alive(pid)

            cwd = active_info.get("cwd") if active_info else None
            started_at = None
            if active_info and active_info.get("startedAt"):
                started_at = active_info["startedAt"] / 1000.0

            existing_task_id = self.db.get_task_id_for_session(session_id)
            if existing_task_id:
                self.db.upsert_session(
                    session_id=session_id,
                    task_id=existing_task_id,
                    pid=pid,
                    cwd=cwd,
                    is_active=is_active,
                    transcript_path=str(transcript_path) if transcript_path else None,
                )
            else:
                # New session: try AI for active, heuristic for historical
                use_ai = is_active

                # Title: history > AI > first message
                title = history_titles.get(session_id)
                if not title and transcript_path:
                    title = self.summarizer.generate_title(
                        transcript_path, use_ai=use_ai
                    )
                if not title:
                    title = "Untitled"

                # Summary
                summary = None
                if transcript_path:
                    summary = self.summarizer.summarize(
                        transcript_path, use_ai=use_ai
                    )

                task_id = str(uuid.uuid4())
                self.db.upsert_task(
                    task_id=task_id,
                    title=title,
                    status="working" if is_active else "done",
                    summary=summary,
                )
                self.db.upsert_session(
                    session_id=session_id,
                    task_id=task_id,
                    pid=pid,
                    cwd=cwd,
                    started_at=started_at,
                    is_active=is_active,
                    transcript_path=str(transcript_path) if transcript_path else None,
                )
                self.db.add_timeline_event(
                    task_id=task_id,
                    session_id=session_id,
                    event_type="session_discovered",
                    description="Session discovered by scanner",
                )

    def _scan_sessions(self) -> dict:
        """Read sessions/*.json and return {session_id: {pid, cwd, startedAt, ...}}."""
        results = {}
        if not self.sessions_dir.exists():
            return results
        for session_file in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(session_file.read_text())
                session_id = data.get("sessionId")
                if session_id:
                    results[session_id] = data
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to read session file {session_file}: {e}")
        return results

    def _scan_transcripts(self) -> dict:
        """Read projects/*/*.jsonl and return {session_id: Path}."""
        results = {}
        if not self.projects_dir.exists():
            return results
        for jsonl_file in self.projects_dir.glob("*/*.jsonl"):
            session_id = jsonl_file.stem
            results[session_id] = jsonl_file
        return results

    def _scan_history(self) -> dict:
        """Read history.jsonl and return {session_id: display_title}."""
        results = {}
        if not self.history_file.exists():
            return results
        try:
            text = self.history_file.read_text().strip()
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    session_id = entry.get("sessionId")
                    display = entry.get("display")
                    if session_id and display:
                        results[session_id] = Summarizer._clean_title(display)
                except json.JSONDecodeError:
                    continue
        except OSError as e:
            logger.warning(f"Failed to read history file: {e}")
        return results

    def _is_pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _find_transcript(self, session_id: str) -> Path | None:
        if not self.projects_dir.exists():
            return None
        for jsonl_file in self.projects_dir.glob(f"*/{session_id}.jsonl"):
            return jsonl_file
        return None
