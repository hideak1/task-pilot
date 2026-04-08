"""Dataclasses for Task Pilot's session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Session:
    """Persistent state — exactly one row in the `sessions` table."""
    id: str
    tmux_window: str
    cwd: str
    git_branch: str | None
    started_at: float
    title: str | None


@dataclass
class SessionState:
    """Runtime state — owned by SessionTracker, never persisted."""
    session_id: str
    is_alive: bool = True
    last_activity: float = 0.0
    token_count: int = 0
    claude_session_id: str | None = None
    transcript_path: Path | None = None
    status: str = "initializing"  # initializing | working | idle | unknown
