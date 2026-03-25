"""Scanner for Claude Code sessions and transcripts."""

import json
import logging
import os
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
        # Step 1: Read active sessions (pid files)
        active_sessions = self._scan_sessions()

        # Step 2: Read history for display titles
        history_titles = self._scan_history()

        # Step 3: Discover all transcripts
        transcript_sessions = self._scan_transcripts()

        # Step 4: Merge all known session IDs
        all_session_ids = set(active_sessions.keys()) | set(transcript_sessions.keys())

        for session_id in all_session_ids:
            active_info = active_sessions.get(session_id)
            transcript_path = transcript_sessions.get(session_id)

            # Determine if PID is alive
            pid = active_info["pid"] if active_info else None
            is_active = False
            if pid is not None:
                is_active = self._is_pid_alive(pid)

            # Determine title
            title = history_titles.get(session_id)
            if not title and transcript_path:
                title = self._extract_title(transcript_path)
            if not title:
                title = "Untitled"

            # Determine cwd and started_at
            cwd = active_info.get("cwd") if active_info else None
            started_at = None
            if active_info and active_info.get("startedAt"):
                started_at = active_info["startedAt"] / 1000.0  # ms to seconds

            # Check if session already exists in DB
            existing_task_id = self.db.get_task_id_for_session(session_id)
            if existing_task_id:
                # Update session active status only — no summary generation
                self.db.upsert_session(
                    session_id=session_id,
                    task_id=existing_task_id,
                    pid=pid,
                    cwd=cwd,
                    is_active=is_active,
                    transcript_path=str(transcript_path) if transcript_path else None,
                )
            else:
                # New session: generate summary once (heuristic only, no CLI)
                summary = None
                if transcript_path:
                    summary = self.summarizer.from_transcript(
                        transcript_path, use_cli=False
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
                    description=f"Session discovered by scanner",
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
            # The filename (without extension) is the session ID
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
                        results[session_id] = self._clean_title(display)
                except json.JSONDecodeError:
                    continue
        except OSError as e:
            logger.warning(f"Failed to read history file: {e}")
        return results

    def _is_pid_alive(self, pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _extract_title(self, transcript_path: Path) -> str | None:
        """Extract a short title from the first user message in a transcript.

        Strips command tags (e.g. <command-name>...</command-name>) and
        takes only the first meaningful line, truncated to 80 chars.
        """
        try:
            text = transcript_path.read_text().strip()
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    msg_type = entry.get("type")
                    if msg_type not in ("user", "human"):
                        continue
                    message = entry.get("message", {})
                    content = message.get("content", "")
                    # Handle list-of-blocks format (Anthropic API style)
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                content = block["text"]
                                break
                        else:
                            continue
                    if not isinstance(content, str) or not content.strip():
                        continue
                    return self._clean_title(content)
                except json.JSONDecodeError:
                    continue
        except OSError as e:
            logger.warning(f"Failed to read transcript {transcript_path}: {e}")
        return None

    @staticmethod
    def _clean_title(raw: str) -> str:
        """Clean raw user message into a short title."""
        import re
        # Strip XML-style command tags
        text = re.sub(r"<[^>]+>", "", raw)
        # Take first non-empty line
        for line in text.strip().splitlines():
            line = line.strip()
            if line:
                text = line
                break
        # Truncate
        if len(text) > 80:
            text = text[:77] + "..."
        return text

    def _find_transcript(self, session_id: str) -> Path | None:
        """Search projects/ directories for a transcript matching the session ID."""
        if not self.projects_dir.exists():
            return None
        for jsonl_file in self.projects_dir.glob(f"*/{session_id}.jsonl"):
            return jsonl_file
        return None
