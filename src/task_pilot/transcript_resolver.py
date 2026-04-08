"""Resolve a session's transcript .jsonl path."""

from __future__ import annotations

from pathlib import Path

import psutil


def cwd_to_slug(cwd: str) -> str:
    """Claude Code stores transcripts under projects/<slug>/."""
    return cwd.replace("/", "-")


def resolve_by_pid(shell_pid: int) -> str | None:
    """Walk children of shell_pid to find a `claude` process; return its claude session id."""
    try:
        proc = psutil.Process(shell_pid)
        for child in proc.children(recursive=True):
            try:
                name = child.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if name == "claude" or (child.cmdline() and child.cmdline()[0].endswith("claude")):
                return _claude_session_id_for_pid(child.pid)
    except psutil.NoSuchProcess:
        return None
    return None


def _claude_session_id_for_pid(pid: int) -> str | None:
    import json
    sessions_dir = Path.home() / ".claude" / "sessions"
    if not sessions_dir.exists():
        return None
    for f in sessions_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("pid") == pid:
            return data.get("sessionId")
    return None


def resolve_by_cwd_and_time(
    cwd: str, started_at: float, claude_home: Path | None = None
) -> Path | None:
    """Find the .jsonl in projects/<slug>/ whose ctime is after started_at - 2s."""
    if claude_home is None:
        claude_home = Path.home() / ".claude"
    proj_dir = claude_home / "projects" / cwd_to_slug(cwd)
    if not proj_dir.exists():
        return None
    candidates = []
    for f in proj_dir.glob("*.jsonl"):
        try:
            ct = f.stat().st_ctime
        except OSError:
            continue
        if ct >= started_at - 2:
            candidates.append((ct, f))
    if not candidates:
        return None
    return min(candidates, key=lambda x: abs(x[0] - started_at))[1]
